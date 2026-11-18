"""Versioned SQLite repository. Transactions serialize approvals and executions."""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from agentflow.config import DATA
from agentflow.domain import AgentFlowError


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def redact(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if any(s in k.lower() for s in ("secret", "password", "token", "authorization"))
            else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class Store:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.connection.row_factory = sqlite3.Row
        # One connection is guarded for thread reuse; SQLite also locks across processes.
        import threading

        self.lock = threading.RLock()
        with self.lock:
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA journal_mode=WAL")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise AgentFlowError("DATABASE_VERSION", "Database is newer than this application.")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS plan_versions(id TEXT, version INTEGER, body TEXT,
                    PRIMARY KEY(id, version));
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals(plan_id TEXT, step_id TEXT, body TEXT,
                    PRIMARY KEY(plan_id,step_id));
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, fingerprint TEXT,
                    run_id TEXT NOT NULL REFERENCES runs(id));
                CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, run_id TEXT,
                    created_at TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, kind TEXT,
                    created_at TEXT, body TEXT);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, payload TEXT,
                    payload_digest TEXT, signature_digest TEXT UNIQUE, persona TEXT,
                    status TEXT, attempts INTEGER, next_attempt_at REAL, trace_id TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS eval_runs(id TEXT PRIMARY KEY, body TEXT);
                PRAGMA user_version=1;
            """)
        self.seed()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise

    def seed(self) -> None:
        with self.transaction() as db:
            for doc in json.loads((DATA / "knowledge_base.json").read_text())["documents"]:
                db.execute(
                    "INSERT OR IGNORE INTO documents VALUES (?,?)", (doc["id"], canonical(doc))
                )
            for item in json.loads((DATA / "sample_business_records.json").read_text())["invoices"]:
                db.execute(
                    "INSERT OR IGNORE INTO items VALUES (?,?)", (item["id"], canonical(item))
                )

    def rows(self, query: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.connection.execute(query, args)]

    def bodies(self, table: str) -> list[dict]:
        if table not in {"plans", "documents", "items", "runs", "eval_runs"}:
            raise ValueError("Unapproved table")
        return [
            json.loads(row["body"]) for row in self.rows(f"SELECT body FROM {table} ORDER BY rowid")
        ]

    def body(self, table: str, key: str) -> dict:
        if table not in {"plans", "runs", "eval_runs"}:
            raise ValueError("Unapproved table")
        rows = self.rows(f"SELECT body FROM {table} WHERE id=?", (key,))
        if not rows:
            raise AgentFlowError("NOT_FOUND", f"{table} record not found.", 404)
        return json.loads(rows[0]["body"])

    @staticmethod
    def audit(db: sqlite3.Connection, kind: str, details: dict) -> None:
        db.execute(
            "INSERT INTO audit(kind,created_at,body) VALUES (?,?,?)",
            (kind, now_iso(), canonical(redact(details))),
        )

    def record(self, kind: str, details: dict) -> None:
        with self.transaction() as db:
            self.audit(db, kind, details)

    def close(self) -> None:
        with self.lock:
            self.connection.close()

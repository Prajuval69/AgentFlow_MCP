"""In-process adapters only. No sockets, credentials, URLs or external tenants."""

import json
import sqlite3
import time
from collections.abc import Callable

from agentflow.domain import AgentFlowError
from agentflow.storage import canonical, redact


class LocalAdapters:
    @staticmethod
    def lookup(db: sqlite3.Connection, item_id: str) -> dict:
        row = db.execute("SELECT body FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise AgentFlowError("ITEM_NOT_FOUND", "Local invoice not found.", 404)
        return json.loads(row[0])

    @staticmethod
    def write(
        db: sqlite3.Connection, item_id: str, fields: dict, create: bool, timestamp: str
    ) -> dict:
        if len(canonical(fields).encode()) > 16_384:
            raise AgentFlowError("PAYLOAD_TOO_LARGE", "Local item fields exceed 16KB.")
        if create:
            if db.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
                raise AgentFlowError("ITEM_EXISTS", "Local item already exists.", 409)
            body = {"id": item_id, **fields, "updated_at": timestamp, "mode": "simulated"}
            db.execute("INSERT INTO items VALUES (?,?)", (item_id, canonical(body)))
        else:
            body = {
                **LocalAdapters.lookup(db, item_id),
                **fields,
                "updated_at": timestamp,
                "mode": "simulated",
            }
            db.execute("UPDATE items SET body=? WHERE id=?", (canonical(body), item_id))
        return body

    @staticmethod
    def notify(db: sqlite3.Connection, run_id: str, inputs: dict, timestamp: str) -> dict:
        body = {**inputs, "mode": "simulated", "sent_externally": False}
        db.execute(
            "INSERT INTO outbox(run_id,created_at,body) VALUES (?,?,?)",
            (run_id, timestamp, canonical(redact(body))),
        )
        return {"outbox_id": db.execute("SELECT last_insert_rowid()").fetchone()[0], **body}


class InternalStub:
    """Explicit dispatch instead of HTTP avoids SSRF altogether.

    Two attempts, bounded 1s synchronous processing, no retry for policy failures.
    A synchronous function cannot be forcibly interrupted; stub work is bounded SQL only.
    """

    def __init__(self, handler: Callable | None = None):
        self.handler = handler or self.summary

    @staticmethod
    def summary(db: sqlite3.Connection, payload: dict) -> dict:
        if payload:
            raise AgentFlowError("STUB_PAYLOAD", "Invoice summary accepts an empty payload only.")
        rows = db.execute("SELECT body FROM items ORDER BY id").fetchall()
        return {
            "mode": "simulated",
            "item_count": len(rows),
            "total_amount": sum(float(json.loads(row[0]).get("total_amount", 0)) for row in rows),
        }

    def call(self, db: sqlite3.Connection, endpoint: str, payload: dict) -> dict:
        if endpoint != "internal://invoice-summary":
            raise AgentFlowError(
                "ENDPOINT_NOT_ALLOWLISTED", "Only the internal invoice summary stub is allowed."
            )
        if len(canonical(payload).encode()) > 4096:
            raise AgentFlowError("PAYLOAD_TOO_LARGE", "Stub payload exceeds 4KB.")
        for attempt in range(2):
            started = time.monotonic()
            try:
                result = self.handler(db, payload)
                if time.monotonic() - started > 1:
                    raise TimeoutError("Internal stub exceeded budget")
                return {**result, "attempts": attempt + 1}
            except (TimeoutError, ConnectionError):
                if attempt == 1:
                    raise AgentFlowError(
                        "STUB_UNAVAILABLE", "Internal stub failed after two attempts.", 503
                    ) from None
        raise AssertionError("Unreachable")

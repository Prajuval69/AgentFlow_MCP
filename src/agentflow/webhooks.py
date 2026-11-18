"""Signed local event ingestion and a durable queue with bounded retry/leases."""

import hashlib
import hmac
import re
import time
from collections.abc import Callable

from pydantic import ValidationError

from agentflow.domain import (
    AgentFlowError,
    EventEnvelope,
    EventReceipt,
    EventRecord,
    SimulationRequest,
)
from agentflow.service import Service
from agentflow.storage import digest

MAX_BODY = 16_384


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return (
        "sha256="
        + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )


class Webhooks:
    def __init__(self, service: Service, clock: Callable[[], float] = time.time):
        self.service = service
        self.clock = clock

    def records(self) -> list[EventRecord]:
        return [
            self.record(row)
            for row in self.service.store.rows("SELECT * FROM events ORDER BY rowid DESC LIMIT 200")
        ]

    @staticmethod
    def record(row: dict) -> EventRecord:
        return EventRecord(**{key: row[key] for key in EventRecord.model_fields})

    def get(self, event_id: str) -> EventRecord:
        rows = self.service.store.rows("SELECT * FROM events WHERE id=?", (event_id,))
        if not rows:
            raise AgentFlowError("NOT_FOUND", "Event not found.", 404)
        return self.record(rows[0])

    def accept(self, body: bytes, timestamp: str, event_id: str, signature: str) -> EventReceipt:
        secret = self.service.settings.webhook_secret
        if not secret:
            raise AgentFlowError(
                "WEBHOOK_DISABLED",
                "Configure a local webhook secret of at least 32 characters.",
                503,
            )
        if len(body) > MAX_BODY:
            raise AgentFlowError("PAYLOAD_TOO_LARGE", "Event exceeds 16KB.", 413)
        if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12:
            raise AgentFlowError("INVALID_TIMESTAMP", "Expected integer Unix timestamp.", 401)
        if abs(self.clock() - int(timestamp)) > 300:
            raise AgentFlowError(
                "STALE_SIGNATURE", "Timestamp is outside the 300-second tolerance.", 401
            )
        if not re.fullmatch(r"sha256=[a-f0-9]{64}", signature) or not hmac.compare_digest(
            sign(secret, timestamp, body), signature
        ):
            raise AgentFlowError("INVALID_SIGNATURE", "Signature verification failed.", 401)
        try:
            event = EventEnvelope.model_validate_json(body)
        except ValidationError:
            raise AgentFlowError("EVENT_SCHEMA", "Event body failed strict validation.") from None
        if event.id != event_id:
            raise AgentFlowError(
                "EVENT_ID_MISMATCH", "Header event ID must match signed body.", 409
            )
        payload_digest = digest(event.model_dump())
        signature_digest = hashlib.sha256(signature.encode()).hexdigest()
        with self.service.store.transaction() as db:
            existing = db.execute("SELECT * FROM events WHERE id=?", (event.id,)).fetchone()
            if existing:
                if existing["payload_digest"] != payload_digest:
                    raise AgentFlowError(
                        "EVENT_CONFLICT", "Event ID already has a different payload.", 409
                    )
                return EventReceipt(duplicate=True, event=self.record(dict(existing)))
            if db.execute(
                "SELECT 1 FROM events WHERE signature_digest=?", (signature_digest,)
            ).fetchone():
                raise AgentFlowError("SIGNATURE_REPLAY", "Signature has already been used.", 409)
            # Webhook caller cannot supply an admin/reviewer persona.
            db.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,'pending',0,?,NULL,NULL)",
                (
                    event.id,
                    event.model_dump_json(),
                    payload_digest,
                    signature_digest,
                    "editor",
                    self.clock(),
                ),
            )
            self.service.store.audit(
                db, "webhook_received", {"event_id": event.id, "mode": "simulated"}
            )
        return EventReceipt(duplicate=False, event=self.get(event.id))

    def process_due(self, limit: int = 20) -> list[EventRecord]:
        if not 1 <= limit <= 100:
            raise AgentFlowError("QUEUE_LIMIT", "Queue batch limit must be 1–100.")
        processed = []
        for _ in range(limit):
            with self.service.store.transaction() as db:
                row = db.execute(
                    """SELECT * FROM events WHERE
                    status IN ('pending','retry','processing') AND next_attempt_at<=?
                    ORDER BY next_attempt_at,id LIMIT 1""",
                    (self.clock(),),
                ).fetchone()
                if row is None:
                    break
                if row["attempts"] >= 3:
                    db.execute(
                        "UPDATE events SET status='dead_letter',error='WORKER_LEASE_EXHAUSTED' WHERE id=?",
                        (row["id"],),
                    )
                    self.service.store.audit(
                        db,
                        "webhook_dead_letter",
                        {"event_id": row["id"], "error": "WORKER_LEASE_EXHAUSTED"},
                    )
                    processed.append(
                        self.record(
                            {
                                **dict(row),
                                "status": "dead_letter",
                                "error": "WORKER_LEASE_EXHAUSTED",
                            }
                        )
                    )
                    continue
                event_id, attempts = row["id"], row["attempts"] + 1
                db.execute(
                    "UPDATE events SET status='processing',attempts=?,next_attempt_at=? WHERE id=?",
                    (attempts, self.clock() + 60, event_id),
                )
            event = EventEnvelope.model_validate_json(row["payload"])
            trace_id, error = None, None
            status = "completed"
            try:
                run = self.service.simulate(
                    event.plan_id,
                    SimulationRequest(data=event.data, idempotency_key=event.idempotency_key),
                    "editor",
                )
                trace_id = run.id
                if run.status != "completed":
                    status, error = "dead_letter", run.errors[0].code if run.errors else run.outcome
            except AgentFlowError as exc:
                error = exc.code
                status = "retry" if attempts < 3 and exc.status in {404, 503} else "dead_letter"
            except Exception:
                error = "PROCESSING_FAILURE"
                status = "retry" if attempts < 3 else "dead_letter"
            with self.service.store.transaction() as db:
                db.execute(
                    "UPDATE events SET status=?,next_attempt_at=?,trace_id=?,error=? WHERE id=?",
                    (status, self.clock() + 2**attempts, trace_id, error, event_id),
                )
                self.service.store.audit(
                    db,
                    "webhook_processed",
                    {
                        "event_id": event_id,
                        "status": status,
                        "attempt": attempts,
                        "trace_id": trace_id,
                        "error": error,
                    },
                )
            processed.append(self.get(event_id))
        return processed

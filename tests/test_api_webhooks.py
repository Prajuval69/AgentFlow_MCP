import json

import pytest
from fastapi.testclient import TestClient

from agentflow.api import create_app
from agentflow.cli import INVOICE_PROMPT
from agentflow.domain import AgentFlowError
from agentflow.service import Service
from agentflow.webhooks import Webhooks, sign

EDITOR = {"X-Mock-Persona": "editor"}
REVIEWER = {"X-Mock-Persona": "reviewer"}


def event_body(plan_id, event_id="event-test", key=None):
    return json.dumps(
        {
            "id": event_id,
            "type": "simulate_plan",
            "plan_id": plan_id,
            "data": {"total_amount": 25000},
            "idempotency_key": key or event_id,
        }
    ).encode()


def headers(service, body, timestamp="2000", event_id="event-test"):
    return {
        "X-AgentFlow-Timestamp": timestamp,
        "X-AgentFlow-Event-Id": event_id,
        "X-AgentFlow-Signature": sign(service.settings.webhook_secret, timestamp, body),
    }


def test_rest_full_workflow(client):
    assert (
        client.get("/api/v1/health").json()["identity"] == "LOCAL_MOCK_PERSONAS_NOT_AUTHENTICATION"
    )
    assert client.post("/api/v1/plans", json={"prompt": INVOICE_PROMPT}).status_code == 403
    response = client.post("/api/v1/plans", json={"prompt": INVOICE_PROMPT}, headers=EDITOR)
    assert response.status_code == 201
    assert response.headers["X-Request-ID"]
    plan = response.json()
    pid = plan["id"]
    assert client.get("/api/v1/plans/" + pid).json() == plan
    assert client.post(f"/api/v1/plans/{pid}/validate").json()["valid"]
    assert (
        client.post(
            f"/api/v1/plans/{pid}/approvals",
            json={"step_id": "approve", "decision": "approved"},
            headers=EDITOR,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/plans/{pid}/approvals",
            json={"step_id": "approve", "decision": "approved"},
            headers=REVIEWER,
        ).status_code
        == 200
    )
    response = client.post(
        f"/api/v1/plans/{pid}/simulate", json={"data": {"total_amount": 75000}}, headers=EDITOR
    )
    run = response.json()
    assert run["outcome"] == "finance_notified_simulated"
    assert client.get("/api/v1/runs/" + run["id"]).json() == run
    assert len(client.get("/api/v1/outbox").json()) == 1
    assert client.get("/api/v1/plans").json()
    assert client.get("/api/v1/plans/" + pid + "/versions").json() == [plan]
    assert client.get("/api/v1/audit").json()
    assert client.get("/api/v1/items").json()
    assert client.get("/api/v1/integrations").json()[0]["mode"] == "simulated"
    assert client.get("/api/v1/catalog?query=approval").json()["actions"]
    assert client.get("/api/v1/documents").json()
    assert client.get("/api/v1/documents/search?query=approval&k=3").status_code == 200
    assert client.get("/api/v1/schema").json()["$defs"]["Step"]["allOf"]
    assert "/api/v1/plans" in client.get("/openapi.json").json()["paths"]
    assert client.get("/docs").status_code == 200


@pytest.mark.parametrize(
    "payload", [{"prompt": " "}, {"prompt": "x", "token": "private"}, {"prompt": 100}]
)
def test_rest_invalid_inputs(client, payload):
    response = client.post("/api/v1/plans", json=payload, headers=EDITOR)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SCHEMA_INVALID"
    assert "private" not in response.text


def test_rest_structured_not_found_and_guard(client, service):
    assert client.get("/api/v1/plans/missing").json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/v1/health", headers={"Host": "evil.test"}).status_code == 400
    assert client.get("/api/v1/health", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/v1/plans", content=b"a" * 100001, headers=EDITOR).status_code == 413
    with TestClient(create_app(service), client=("192.168.1.10", 1234)) as external:
        assert external.get("/api/v1/health").status_code == 403
    assert client.post(
        "/api/v1/plans/validate", json={"steps": [{"action_type": "arbitrary"}]}
    ).json()["requires_manual_review"]


def test_webhook_signature_dedup_worker_persistence(client, invoice, service):
    hooks = Webhooks(service, clock=lambda: 2000)
    client.app.state.webhooks = hooks
    body = event_body(invoice.id)
    signed = headers(service, body)
    assert client.post("/api/v1/webhooks", content=body, headers=signed).status_code == 202
    duplicate = client.post("/api/v1/webhooks", content=body, headers=signed).json()
    assert duplicate["duplicate"]
    processed = client.post("/api/v1/events/process", headers=EDITOR).json()
    assert processed[0]["status"] == "completed"
    assert hooks.process_due() == []
    assert client.get("/api/v1/events").json()[0]["attempts"] == 1
    second = Service(service.settings)
    try:
        restarted = Webhooks(second, clock=lambda: 2000)
        assert restarted.accept(
            body, "2000", "event-test", signed["X-AgentFlow-Signature"]
        ).duplicate
        assert second.trace(processed[0]["trace_id"]).outcome == "below_threshold_simulated"
    finally:
        second.store.close()


@pytest.mark.parametrize(
    "change,status,code",
    [
        ({"X-AgentFlow-Signature": "sha256=wrong"}, 401, "INVALID_SIGNATURE"),
        ({"X-AgentFlow-Timestamp": "1000"}, 401, "STALE_SIGNATURE"),
        ({"X-AgentFlow-Timestamp": "3001"}, 401, "STALE_SIGNATURE"),
        ({"X-AgentFlow-Timestamp": "not-a-time"}, 401, "INVALID_TIMESTAMP"),
        ({"X-AgentFlow-Timestamp": "２０００"}, 401, "INVALID_TIMESTAMP"),
        ({"X-AgentFlow-Event-Id": "another"}, 409, "EVENT_ID_MISMATCH"),
    ],
)
def test_webhook_invalid(client, invoice, service, change, status, code):
    client.app.state.webhooks = Webhooks(service, clock=lambda: 2000)
    body = event_body(invoice.id)
    # Unicode headers cannot be encoded by HTTP clients; test the service for that case.
    if not change.get("X-AgentFlow-Timestamp", "").isascii():
        with pytest.raises(AgentFlowError) as exc:
            client.app.state.webhooks.accept(
                body, change["X-AgentFlow-Timestamp"], "event-test", "bad"
            )
        assert exc.value.code == code
        return
    response = client.post(
        "/api/v1/webhooks", content=body, headers={**headers(service, body), **change}
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert not service.store.rows("SELECT * FROM events")


def test_webhook_payload_conflict_tamper_size_and_schema(client, invoice, service):
    hooks = Webhooks(service, clock=lambda: 2000)
    client.app.state.webhooks = hooks
    body = event_body(invoice.id)
    hooks.accept(body, "2000", "event-test", sign(service.settings.webhook_secret, "2000", body))
    changed = event_body("different-plan")
    assert (
        client.post(
            "/api/v1/webhooks", content=changed, headers=headers(service, changed)
        ).status_code
        == 409
    )
    assert (
        client.post("/api/v1/webhooks", content=changed, headers=headers(service, body)).status_code
        == 401
    )
    large = b"a" * 16385
    assert (
        client.post("/api/v1/webhooks", content=large, headers=headers(service, large)).status_code
        == 413
    )
    invalid = b'{"id":"another","shell":"cmd"}'
    assert (
        client.post(
            "/api/v1/webhooks",
            content=invalid,
            headers=headers(service, invalid, event_id="another"),
        ).status_code
        == 422
    )
    assert client.post("/api/v1/webhooks", content=body).status_code == 401


def test_webhook_retries_dead_letters_and_late_plan(service):
    clock = [2000.0]
    hooks = Webhooks(service, clock=lambda: clock[0])
    body = event_body("missing-plan")
    hooks.accept(body, "2000", "event-test", sign(service.settings.webhook_secret, "2000", body))
    first = hooks.process_due()[0]
    assert first.status == "retry" and first.attempts == 1
    assert hooks.process_due() == []
    clock[0] += 2
    assert hooks.process_due()[0].status == "retry"
    clock[0] += 4
    third = hooks.process_due()[0]
    assert third.status == "dead_letter" and third.attempts == 3
    assert hooks.process_due() == []


def test_webhook_business_failure_is_dead_letter(service, invoice):
    hooks = Webhooks(service, clock=lambda: 2000)
    event = json.loads(event_body(invoice.id))
    event["data"] = {"total_amount": 75000}
    body = json.dumps(event).encode()
    hooks.accept(body, "2000", "event-test", sign(service.settings.webhook_secret, "2000", body))
    record = hooks.process_due()[0]
    assert record.status == "dead_letter"
    assert record.error == "APPROVAL_MISSING"
    assert service.trace(record.trace_id).status == "blocked"
    assert not service.outbox()


def test_eval_api_isolated_and_persistent(client):
    response = client.post("/api/v1/eval/runs", headers=EDITOR)
    assert response.status_code == 201
    report = response.json()
    assert report["metrics"]["execution_fidelity"]["numerator"] == 5
    assert client.get("/api/v1/eval/runs/" + report["id"]).json() == report
    assert len(client.get("/api/v1/eval/runs").json()) == 1
    assert client.get("/api/v1/plans").json() == []

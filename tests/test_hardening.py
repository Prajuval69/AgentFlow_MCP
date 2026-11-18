import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agentflow.config import Settings
from agentflow.domain import AgentFlowError, ApprovalRequest, PlanRequest, SimulationRequest
from agentflow.service import Service
from agentflow.webhooks import Webhooks, sign


@pytest.mark.parametrize(
    "prompt",
    [
        "If invoice total exceeds 50000 request manager approval and notify finance and charge a credit card",
        "If invoice total exceeds 50000 request manager approval and notify finance then update local invoice",
        "If invoice total exceeds -50000 request manager approval and notify finance",
        "Wait 2 simulated days and notify the owner",
        "Wait a simulated day and notify finance",
        "Create a local invoice item and notify reviewer and log event",
        "Unknown workflow with unsupported tools",
    ],
)
def test_no_silent_partial_mapping(service, prompt):
    plan = service.generate(PlanRequest(prompt=prompt))
    assert plan.requires_manual_review
    assert not plan.steps


def test_create_conflict_missing_item_and_write_rejection(service):
    create = service.generate(
        PlanRequest(prompt="Create a local SharePoint-like invoice item and notify reviewer")
    )
    service.approve(create.id, ApprovalRequest(step_id="work", decision="rejected"), "reviewer")
    assert service.simulate(create.id, SimulationRequest()).outcome == "rejected_simulated"
    assert len(service.store.bodies("items")) == 2
    service.approve(create.id, ApprovalRequest(step_id="work", decision="approved"), "reviewer")
    assert service.simulate(create.id, SimulationRequest()).status == "completed"
    conflict = service.simulate(create.id, SimulationRequest())
    assert conflict.status == "failed" and conflict.errors[0].code == "ITEM_EXISTS"
    assert len(service.outbox()) == 1
    lookup = service.generate(
        PlanRequest(prompt="Look up local invoice INV-9999 and record the result")
    )
    missing = service.simulate(lookup.id, SimulationRequest())
    assert missing.status == "failed" and missing.errors[0].code == "ITEM_NOT_FOUND"


def test_input_cannot_grant_approval(service, invoice):
    run = service.simulate(
        invoice.id,
        SimulationRequest(data={"total_amount": 75000, "approved": True, "decision": "approved"}),
    )
    assert run.errors[0].code == "APPROVAL_MISSING"
    assert not service.outbox()


def test_failure_branch_does_not_claim_success(service, invoice):
    raw = invoice.model_copy(deep=True)
    raw.steps[1].next_on_failure = "unchanged"
    service.update_plan(invoice.id, raw, "editor")
    run = service.simulate(invoice.id, SimulationRequest(data={"total_amount": "invalid"}))
    assert run.status == "failed"
    assert run.errors
    assert run.steps[-1].action_type == "terminate"


def test_body_size_depth_and_empty_evidence(service, invoice):
    raw = invoice.model_dump()
    raw["evidence"][0]["passage"] = ""
    assert "INVALID_EVIDENCE" in [i.code for i in service.validate(raw).issues]
    raw = invoice.model_dump()
    raw["warnings"] = ["x" * 100001]
    assert service.validate(raw).issues[0].code == "PLAN_SIZE"
    raw = invoice.model_dump()
    raw["steps"] = [{"id": "start", "action_type": "manual_trigger", "next_on_success": "s0"}]
    raw["steps"].extend(
        {
            "id": f"s{i}",
            "action_type": "log_event",
            "inputs": {"text": "x"},
            "next_on_success": f"s{i + 1}",
        }
        for i in range(52)
    )
    raw["steps"].append({"id": "s52", "action_type": "terminate"})
    assert "DEPTH_LIMIT" in [i.code for i in service.validate(raw).issues]


def test_local_stub_bounded_payload_and_transient_recovery(service):
    with service.store.transaction() as db:
        with pytest.raises(AgentFlowError) as exc:
            service.stub.call(db, "internal://invoice-summary", {"x": "a" * 5000})
        assert exc.value.code == "PAYLOAD_TOO_LARGE"
        with pytest.raises(AgentFlowError) as exc:
            service.stub.call(db, "internal://invoice-summary", {"unknown": True})
        assert exc.value.code == "STUB_PAYLOAD"


def test_queue_concurrent_delivery_and_processing(service):
    plan = service.generate(PlanRequest(prompt="Wait a simulated day and then notify the owner"))
    second = Service(service.settings)
    try:
        first_hooks, second_hooks = Webhooks(service, lambda: 2000), Webhooks(second, lambda: 2000)
        body = json.dumps(
            {
                "id": "concurrent",
                "type": "simulate_plan",
                "plan_id": plan.id,
                "data": {},
                "idempotency_key": "concurrent",
            }
        ).encode()
        signature = sign(service.settings.webhook_secret, "2000", body)
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(
                pool.map(
                    lambda i: (first_hooks if i % 2 else second_hooks).accept(
                        body, "2000", "concurrent", signature
                    ),
                    range(12),
                )
            )
        assert sum(not r.duplicate for r in receipts) == 1
        with ThreadPoolExecutor(max_workers=2) as pool:
            batches = list(pool.map(lambda hooks: hooks.process_due(), (first_hooks, second_hooks)))
        assert sum(len(batch) for batch in batches) == 1
        assert len(service.outbox()) == 1
    finally:
        second.store.close()


def test_queue_recovers_expired_worker_lease_and_invalid_signature(service):
    plan = service.generate(PlanRequest(prompt="Wait a simulated day and then notify the owner"))
    hooks = Webhooks(service, lambda: 2000)
    body = json.dumps(
        {
            "id": "lease",
            "type": "simulate_plan",
            "plan_id": plan.id,
            "data": {},
            "idempotency_key": "lease",
        }
    ).encode()
    hooks.accept(body, "2000", "lease", sign(service.settings.webhook_secret, "2000", body))
    with service.store.transaction() as db:
        db.execute("UPDATE events SET status='processing',next_attempt_at=1999,attempts=1")
    recovered = hooks.process_due()[0]
    assert recovered.status == "completed" and recovered.attempts == 2
    with pytest.raises(AgentFlowError) as exc:
        hooks.accept(body, "2000", "lease", "signature-非ascii")
    assert exc.value.code == "INVALID_SIGNATURE"


def test_webhooks_disabled_and_env_validation(monkeypatch, tmp_path):
    service = Service(Settings(db_path=str(tmp_path / "disabled.sqlite3")))
    try:
        assert not service.health().webhook_enabled
        with pytest.raises(AgentFlowError) as exc:
            Webhooks(service).accept(b"{}", "2000", "event", "bad")
        assert exc.value.code == "WEBHOOK_DISABLED"
    finally:
        service.store.close()
    monkeypatch.setenv("AGENTFLOW_ALLOW_REAL_CLOUD", "true")
    with pytest.raises(ValueError, match="Real cloud"):
        Settings.from_env()
    monkeypatch.setenv("AGENTFLOW_ALLOW_REAL_CLOUD", "false")
    monkeypatch.setenv("AGENTFLOW_DB_URL", "postgres://remote")
    with pytest.raises(ValueError, match="SQLite"):
        Settings.from_env()


def test_injectable_simulation_clock(tmp_path):
    fixed = "2026-01-01T00:00:00+00:00"
    service = Service(Settings(db_path=str(tmp_path / "clock.sqlite3")), clock=lambda: fixed)
    try:
        plan = service.generate(
            PlanRequest(prompt="Wait a simulated day and then notify the owner")
        )
        run = service.simulate(plan.id, SimulationRequest())
        assert run.started_at == fixed
        assert run.steps[-1].virtual_seconds == 86400
        assert service.outbox()[0]["created_at"] == fixed
    finally:
        service.store.close()

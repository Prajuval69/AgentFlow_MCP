"""Local seed, planning, explicit review, simulation, queue worker and offline demo."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from agentflow.domain import ApprovalRequest, PlanRequest, SimulationRequest
from agentflow.service import Service
from agentflow.webhooks import Webhooks, sign

INVOICE_PROMPT = "If invoice amount exceeds INR 50000, request manager approval and notify finance"


def offline_demo(service: Service) -> dict:
    plan = service.generate(PlanRequest(prompt=INVOICE_PROMPT))
    assert service.validate(plan).valid
    missing = service.simulate(plan.id, SimulationRequest(data={"total_amount": 75000}))
    assert missing.status == "blocked"
    service.approve(plan.id, ApprovalRequest(step_id="approve", decision="approved"), "reviewer")
    approved = service.simulate(plan.id, SimulationRequest(data={"total_amount": 75000}))
    assert approved.outcome == "finance_notified_simulated"
    service.approve(plan.id, ApprovalRequest(step_id="approve", decision="rejected"), "reviewer")
    rejected = service.simulate(plan.id, SimulationRequest(data={"total_amount": 75000}))
    assert rejected.outcome == "rejected_simulated"
    low = service.simulate(plan.id, SimulationRequest(data={"total_amount": 25000}))
    assert low.outcome == "below_threshold_simulated"
    unsupported = service.generate(
        PlanRequest(prompt="Send a real email from my Microsoft 365 account now")
    )
    assert unsupported.requires_manual_review
    webhook_result = None
    if service.settings.webhook_secret:
        hooks = Webhooks(service)
        event_id = "event-" + uuid4().hex
        body = json.dumps(
            {
                "id": event_id,
                "type": "simulate_plan",
                "plan_id": plan.id,
                "data": {"total_amount": 25000},
                "idempotency_key": event_id,
            }
        ).encode()
        timestamp = str(int(time.time()))
        signature = sign(service.settings.webhook_secret, timestamp, body)
        hooks.accept(body, timestamp, event_id, signature)
        duplicate = hooks.accept(body, timestamp, event_id, signature)
        assert duplicate.duplicate
        processed = hooks.process_due()
        webhook_result = {"duplicate": True, "events": [e.model_dump() for e in processed]}
    return {
        "mode": "simulated",
        "notice": service.health().notice,
        "plan_id": plan.id,
        "valid": True,
        "blocked_without_decision": missing.model_dump(),
        "approved": approved.model_dump(),
        "rejected": rejected.model_dump(),
        "low_amount": low.model_dump(),
        "unsupported_review": unsupported.requires_manual_review,
        "webhooks": webhook_result,
        "outbox": service.outbox(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline simulated AgentFlow")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    demo = sub.add_parser("demo")
    demo.add_argument("--output", type=Path)
    plan = sub.add_parser("plan")
    plan.add_argument("prompt")
    review = sub.add_parser("approve")
    review.add_argument("plan_id")
    review.add_argument("step_id")
    review.add_argument("decision", choices=["approved", "rejected"])
    sim = sub.add_parser("simulate")
    sim.add_argument("plan_id")
    sim.add_argument("--data", default="{}")
    sim.add_argument(
        "--persona", default="editor", choices=["viewer", "editor", "reviewer", "admin"]
    )
    sub.add_parser("process-events")
    args = parser.parse_args()
    service = Service()
    try:
        if args.command == "seed":
            service.store.seed()
            result = {
                "mode": "simulated",
                "items": service.store.bodies("items"),
                "documents": len(service.documents()),
            }
        elif args.command == "demo":
            result = offline_demo(service)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        elif args.command == "plan":
            result = service.generate(PlanRequest(prompt=args.prompt)).model_dump()
        elif args.command == "approve":
            result = service.approve(
                args.plan_id,
                ApprovalRequest(step_id=args.step_id, decision=args.decision),
                "reviewer",
            ).model_dump()
        elif args.command == "simulate":
            result = service.simulate(
                args.plan_id, SimulationRequest(data=json.loads(args.data)), args.persona
            ).model_dump()
        else:
            result = [e.model_dump() for e in Webhooks(service).process_due()]
        print(json.dumps(result, indent=2))
    finally:
        service.store.close()


if __name__ == "__main__":
    main()

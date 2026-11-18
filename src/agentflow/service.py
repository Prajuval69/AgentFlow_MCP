"""Shared boundary for REST, MCP, CLI, evaluation and webhook workers."""

import json
from collections.abc import Callable
from uuid import uuid4

from agentflow.config import DATA, Settings
from agentflow.domain import (
    INPUT_MODELS,
    AgentFlowError,
    Analysis,
    ApprovalRecord,
    ApprovalRequest,
    AuditRecord,
    Catalog,
    CatalogAction,
    Connection,
    Document,
    Health,
    Issue,
    Plan,
    PlanRequest,
    Predicate,
    Role,
    RunTrace,
    SimulationRequest,
    TraceStep,
    Verdict,
)
from agentflow.integrations import InternalStub, LocalAdapters
from agentflow.planner import OllamaProvider, classify, mock_plan
from agentflow.policy import PROTECTED, WRITES, evaluate, validate
from agentflow.retrieval import retrieve, tokens
from agentflow.storage import Store, digest, now_iso, redact


class Service:
    def __init__(self, settings: Settings | None = None, clock: Callable[[], str] = now_iso):
        self.settings = settings or Settings.from_env()
        self.clock = clock
        self.store = Store(self.settings.db_path)
        source = json.loads((DATA / "action_catalog.json").read_text())
        self.catalog = Catalog(
            version=source["version"],
            actions=[
                CatalogAction(
                    **action, input_schema=INPUT_MODELS[action["type"]].model_json_schema()
                )
                for action in source["actions"]
            ],
        )
        self.stub = InternalStub()
        self.provider = (
            OllamaProvider(self.settings) if self.settings.provider == "ollama" else None
        )

    def health(self) -> Health:
        available = self.provider.health() if self.provider else True
        return Health(
            status="ok" if available else "degraded",
            provider=self.settings.provider,
            provider_available=available,
            webhook_enabled=bool(self.settings.webhook_secret),
        )

    def documents(self) -> list[Document]:
        return [Document.model_validate(doc) for doc in self.store.bodies("documents")]

    def evidence(self, prompt: str, k: int = 5):
        prompt = PlanRequest(prompt=prompt).prompt
        if not 1 <= k <= 5:
            raise AgentFlowError("RETRIEVAL_LIMIT", "k must be between 1 and 5.")
        return retrieve(prompt, self.documents(), k)

    def search_catalog(self, query: str) -> Catalog:
        query = PlanRequest(prompt=query).prompt
        words = set(tokens(query))
        scored = [
            (len(words & set(tokens(a.type + " " + a.description))), a)
            for a in self.catalog.actions
        ]
        return Catalog(
            version=self.catalog.version,
            actions=[
                a
                for score, a in sorted(scored, key=lambda pair: (-pair[0], pair[1].type))
                if score > 0
            ],
        )

    def analyze(self, prompt: str) -> Analysis:
        prompt = PlanRequest(prompt=prompt).prompt
        intent, reason = classify(prompt)
        return Analysis(supported=intent is not None, reason=reason, evidence=self.evidence(prompt))

    @staticmethod
    def require(role: Role, allowed: set[str]) -> None:
        if role not in allowed:
            raise AgentFlowError(
                "RBAC_DENIED", "Local mock persona is not permitted for this operation.", 403
            )

    def generate(self, request: PlanRequest, role: Role = "editor") -> Plan:
        self.require(role, {"editor", "admin"})
        try:
            evidence = self.evidence(request.prompt)
            if self.provider and classify(request.prompt)[0] is not None:
                plan = self.provider.generate(request.prompt, evidence, self.catalog.model_dump())
            else:
                plan = mock_plan(request.prompt, evidence)
            verdict = self.validate(plan)
            if not verdict.valid and not plan.requires_manual_review:
                plan.requires_manual_review = True
                plan.warnings.extend(issue.code + ": " + issue.message for issue in verdict.issues)
            with self.store.transaction() as db:
                body = plan.model_dump_json()
                db.execute("INSERT INTO plans VALUES (?,?)", (plan.id, body))
                db.execute(
                    "INSERT INTO plan_versions VALUES (?,?,?)", (plan.id, plan.version, body)
                )
                self.store.audit(
                    db,
                    "plan_created",
                    {
                        "plan_id": plan.id,
                        "persona": role,
                        "provider": plan.provider,
                        "manual_review": plan.requires_manual_review,
                    },
                )
            return plan
        except AgentFlowError as exc:
            self.store.record("planning_failed", {"code": exc.code, "persona": role})
            raise

    def plan(self, plan_id: str) -> Plan:
        return Plan.model_validate(self.store.body("plans", plan_id))

    def plans(self) -> list[Plan]:
        return [Plan.model_validate(p) for p in self.store.bodies("plans")]

    def validate(self, raw: dict | Plan) -> Verdict:
        return validate(raw, self.catalog, self.documents())

    def update_plan(self, plan_id: str, plan: Plan, role: Role) -> Plan:
        self.require(role, {"editor", "admin"})
        verdict = self.validate(plan)
        if plan.id != plan_id or not verdict.valid:
            raise AgentFlowError("INVALID_PLAN", "Updated plan ID/validation is invalid.")
        with self.store.transaction() as db:
            current = self.plan(plan_id)
            if plan.version != current.version:
                raise AgentFlowError(
                    "VERSION_CONFLICT", "Refresh the current plan before editing.", 409
                )
            plan.version += 1
            body = plan.model_dump_json()
            db.execute("UPDATE plans SET body=? WHERE id=?", (body, plan_id))
            db.execute("INSERT INTO plan_versions VALUES (?,?,?)", (plan_id, plan.version, body))
            db.execute("DELETE FROM approvals WHERE plan_id=?", (plan_id,))
            self.store.audit(
                db,
                "plan_updated",
                {"plan_id": plan_id, "version": plan.version, "approvals_revoked": True},
            )
        return plan

    def approvals(self, plan_id: str) -> list[ApprovalRecord]:
        self.plan(plan_id)
        return [
            ApprovalRecord.model_validate_json(row["body"])
            for row in self.store.rows(
                "SELECT body FROM approvals WHERE plan_id=? ORDER BY step_id", (plan_id,)
            )
        ]

    def approve(self, plan_id: str, request: ApprovalRequest, role: Role) -> ApprovalRecord:
        self.require(role, {"reviewer", "admin"})
        with self.store.transaction() as db:
            plan = self.plan(plan_id)
            step = next((s for s in plan.steps if s.id == request.step_id), None)
            if not step or not step.approval_required:
                raise AgentFlowError(
                    "INVALID_APPROVAL", "Approval must reference a declared protected step."
                )
            approval = ApprovalRecord(
                plan_id=plan_id,
                step_id=step.id,
                decision=request.decision,
                persona=role,
                plan_digest=digest(plan.model_dump()),
                created_at=self.clock(),
            )
            db.execute(
                "INSERT OR REPLACE INTO approvals VALUES (?,?,?)",
                (plan_id, step.id, approval.model_dump_json()),
            )
            self.store.audit(db, "reviewer_decision", approval.model_dump())
        return approval

    def simulate(self, plan_id: str, request: SimulationRequest, role: Role = "editor") -> RunTrace:
        with self.store.transaction() as db:
            plan = self.plan(plan_id)
            fingerprint = digest({"plan": plan.model_dump(), "data": request.data, "persona": role})
            key = request.idempotency_key
            if key:
                previous = db.execute(
                    "SELECT fingerprint,run_id FROM idempotency WHERE key=?", (key,)
                ).fetchone()
                if previous:
                    if previous[0] != fingerprint:
                        raise AgentFlowError(
                            "IDEMPOTENCY_CONFLICT",
                            "Key already belongs to a different operation.",
                            409,
                        )
                    return RunTrace.model_validate(self.store.body("runs", previous[1]))
            run = RunTrace(
                id="run-" + uuid4().hex,
                plan_id=plan_id,
                persona=role,
                status="blocked",
                outcome="blocked",
                started_at=self.clock(),
                steps=[],
            )
            verdict = self.validate(plan)
            if not verdict.valid:
                run.errors = verdict.issues
                run.outcome = "manual_review"
            else:
                data = request.data.copy()
                approvals = {a.step_id: a for a in self.approvals(plan_id)}
                by_id = {s.id: s for s in plan.steps}
                current = plan.steps[0].id
                virtual_seconds = 0
                while current:
                    step = by_id[current]
                    status, details = "succeeded", {}
                    try:
                        if step.action_type in WRITES or step.action_type in PROTECTED:
                            self.require(role, {"editor", "admin"})
                        if step.approval_required:
                            decision = approvals.get(step.id)
                            if not decision or decision.plan_digest != digest(plan.model_dump()):
                                raise AgentFlowError(
                                    "APPROVAL_MISSING", "Explicit reviewer decision required.", 403
                                )
                            details = {
                                "decision": decision.decision,
                                "reviewer_persona": decision.persona,
                            }
                            if decision.decision == "rejected":
                                status = "rejected"
                        if status == "succeeded":
                            action = step.action_type
                            inputs = INPUT_MODELS[action].model_validate(step.inputs).model_dump()
                            if action == "compare_number":
                                status = (
                                    "succeeded"
                                    if evaluate(Predicate.model_validate(inputs["predicate"]), data)
                                    else "false"
                                )
                            elif action == "lookup_list_item":
                                item = LocalAdapters.lookup(db, inputs["item_id"])
                                data.update(item)
                                details = {"item": redact(item)}
                            elif action in {"create_list_item", "update_list_item"}:
                                item = LocalAdapters.write(
                                    db,
                                    inputs["item_id"],
                                    inputs["fields"],
                                    action == "create_list_item",
                                    self.clock(),
                                )
                                data.update(item)
                                details = {"item": redact(item)}
                            elif action == "send_notification":
                                details = LocalAdapters.notify(db, run.id, inputs, self.clock())
                            elif action == "delay_simulated":
                                virtual_seconds += inputs["seconds"]
                                details = {"seconds": inputs["seconds"]}
                            elif action == "log_event":
                                details = {"text": inputs["text"]}
                            elif action == "custom_api":
                                details = self.stub.call(db, inputs["endpoint"], inputs["payload"])
                                data["summary"] = details
                            elif action == "terminate":
                                run.status = "failed" if run.errors else "completed"
                                run.outcome = inputs["outcome"]
                        run.steps.append(
                            TraceStep(
                                step_id=step.id,
                                action_type=step.action_type,
                                status=status,
                                virtual_seconds=virtual_seconds,
                                details=redact(details),
                            )
                        )
                        if step.action_type == "terminate":
                            break
                        if status == "rejected" and not step.next_on_failure:
                            run.outcome = "rejected_simulated"
                            break
                        current = (
                            step.next_on_success if status == "succeeded" else step.next_on_failure
                        )
                    except Exception as exc:
                        code = (
                            exc.code
                            if isinstance(exc, AgentFlowError)
                            else (
                                "INVALID_DATA"
                                if isinstance(exc, (ValueError, TypeError, OverflowError))
                                else "STEP_FAILURE"
                            )
                        )
                        blocked = code in {"RBAC_DENIED", "APPROVAL_MISSING"}
                        run.status = "blocked" if blocked else "failed"
                        run.outcome = code.lower()
                        message = (
                            exc.message
                            if isinstance(exc, AgentFlowError)
                            else "Step input/data could not be evaluated."
                        )
                        run.errors.append(Issue(code=code, message=message, step_id=step.id))
                        run.steps.append(
                            TraceStep(
                                step_id=step.id,
                                action_type=step.action_type,
                                status="blocked" if blocked else "failed",
                                virtual_seconds=virtual_seconds,
                            )
                        )
                        if not blocked and step.next_on_failure:
                            current = step.next_on_failure
                            continue
                        break
            db.execute("INSERT INTO runs VALUES (?,?)", (run.id, run.model_dump_json()))
            if key:
                db.execute("INSERT INTO idempotency VALUES (?,?,?)", (key, fingerprint, run.id))
            self.store.audit(
                db,
                "simulation",
                {
                    "run_id": run.id,
                    "plan_id": plan_id,
                    "persona": role,
                    "status": run.status,
                    "outcome": run.outcome,
                    "steps": [s.model_dump() for s in run.steps],
                },
            )
        return run

    def trace(self, run_id: str) -> RunTrace:
        return RunTrace.model_validate(self.store.body("runs", run_id))

    def audit(self, limit: int = 100) -> list[AuditRecord]:
        return [
            AuditRecord(
                id=r["id"],
                kind=r["kind"],
                created_at=r["created_at"],
                details=json.loads(r["body"]),
            )
            for r in self.store.rows("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        ]

    def outbox(self) -> list[dict]:
        return [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "created_at": r["created_at"],
                **json.loads(r["body"]),
            }
            for r in self.store.rows("SELECT * FROM outbox ORDER BY id DESC LIMIT 200")
        ]

    def connections(self) -> list[Connection]:
        return [
            Connection(id="mock-" + name, provider=name)
            for name in ("sharepoint", "m365", "azure", "internal")
        ]

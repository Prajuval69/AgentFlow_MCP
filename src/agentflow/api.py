"""Versioned, loopback-only REST API for a visibly simulated local demonstration."""

import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from agentflow.domain import (
    AgentFlowError,
    Analysis,
    ApprovalRecord,
    ApprovalRequest,
    AuditRecord,
    Catalog,
    Connection,
    Document,
    EvaluationReport,
    EventReceipt,
    EventRecord,
    Evidence,
    Health,
    Plan,
    PlanRequest,
    Role,
    RunTrace,
    SimulationRequest,
    Verdict,
)
from agentflow.service import Service
from agentflow.webhooks import Webhooks

logger = logging.getLogger("agentflow.requests")


def create_app(service: Service | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if service is None:
            app.state.service = Service()
        app.state.webhooks = Webhooks(app.state.service)
        yield
        if service is None:
            app.state.service.store.close()

    app = FastAPI(
        title="AgentFlow MCP — LOCAL SIMULATION",
        version="0.1.0",
        lifespan=lifespan,
        description="SIMULATION — NOT CONNECTED TO MICROSOFT TENANT. X-Mock-Persona is a local dev role switch, not authentication.",
    )
    if service:
        app.state.service = service
        app.state.webhooks = Webhooks(service)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"]
    )
    rates = defaultdict(deque)

    @app.middleware("http")
    async def local_guard(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        peer = request.client.host if request.client else ""
        error = None
        if peer not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            error = (403, "LOCAL_ONLY", "API only accepts local loopback clients.")
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc not in {
            "127.0.0.1:8501",
            "localhost:8501",
            "127.0.0.1:8000",
            "localhost:8000",
        }:
            error = (403, "ORIGIN_DENIED", "Cross-origin dev API access is not allowed.")
        if request.headers.get("sec-fetch-site") == "cross-site":
            error = (403, "ORIGIN_DENIED", "Cross-site dev API access is not allowed.")
        window = rates[peer]
        while window and window[0] < time.monotonic() - 60:
            window.popleft()
        if len(window) >= 300:
            error = (429, "RATE_LIMIT", "Local rate limit: 300 requests per minute.")
        if len(window) < 300:
            window.append(time.monotonic())
        if request.method in {"POST", "PUT", "PATCH"} and not error:
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 100_000:
                    error = (413, "PAYLOAD_TOO_LARGE", "Request exceeds 100KB.")
                    break
                chunks.append(chunk)
            if not error:
                request._body = b"".join(chunks)
        if error:
            response = JSONResponse(
                status_code=error[0],
                content={
                    "error": {"code": error[1], "message": error[2]},
                    "request_id": request_id,
                    "mode": "simulated",
                },
            )
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-AgentFlow-Mode"] = "simulated"
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
        )
        if response.status_code >= 400 and hasattr(app.state, "service"):
            app.state.service.store.record(
                "request_rejected",
                {
                    "request_id": request_id,
                    "status": response.status_code,
                    "method": request.method,
                },
            )
        return response

    @app.exception_handler(AgentFlowError)
    async def domain_error(request: Request, exc: AgentFlowError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": exc.as_dict(),
                "request_id": request.state.request_id,
                "mode": "simulated",
            },
        )

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def schema_error(request: Request, exc: RequestValidationError | ValidationError):
        # ValidationError.input can contain passwords; never serialize it.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "SCHEMA_INVALID",
                    "message": "Request failed strict validation.",
                    "fields": [".".join(map(str, e["loc"])) for e in exc.errors()],
                },
                "request_id": request.state.request_id,
                "mode": "simulated",
            },
        )

    def svc(request: Request) -> Service:
        return request.app.state.service

    def persona(x_mock_persona: Role = Header(default="viewer")) -> Role:
        return x_mock_persona

    prefix = "/api/v1"

    @app.get(prefix + "/health", response_model=Health)
    def health(s: Service = Depends(svc)):
        return s.health()

    @app.get(prefix + "/catalog", response_model=Catalog)
    def catalog(query: str | None = None, s: Service = Depends(svc)):
        return s.search_catalog(query) if query else s.catalog

    @app.get(prefix + "/documents", response_model=list[Document])
    def documents(s: Service = Depends(svc)):
        return s.documents()

    @app.get(prefix + "/documents/search", response_model=list[Evidence])
    def search_documents(
        query: str, k: int = Query(default=5, ge=1, le=5), s: Service = Depends(svc)
    ):
        return s.evidence(query, k)

    @app.get(prefix + "/schema", response_model=dict)
    def schema():
        return Plan.model_json_schema()

    @app.post(prefix + "/analyze", response_model=Analysis)
    def analyze(request: PlanRequest, s: Service = Depends(svc)):
        return s.analyze(request.prompt)

    @app.post(prefix + "/plans", response_model=Plan, status_code=201)
    def create_plan(request: PlanRequest, role: Role = Depends(persona), s: Service = Depends(svc)):
        return s.generate(request, role)

    @app.get(prefix + "/plans", response_model=list[Plan])
    def plans(s: Service = Depends(svc)):
        return s.plans()

    @app.post(prefix + "/plans/validate", response_model=Verdict)
    def validate_raw(raw: dict, s: Service = Depends(svc)):
        return s.validate(raw)

    @app.get(prefix + "/plans/{plan_id}", response_model=Plan)
    def plan(plan_id: str, s: Service = Depends(svc)):
        return s.plan(plan_id)

    @app.put(prefix + "/plans/{plan_id}", response_model=Plan)
    def update_plan(
        plan_id: str, plan: Plan, role: Role = Depends(persona), s: Service = Depends(svc)
    ):
        return s.update_plan(plan_id, plan, role)

    @app.get(prefix + "/plans/{plan_id}/versions", response_model=list[Plan])
    def versions(plan_id: str, s: Service = Depends(svc)):
        s.plan(plan_id)
        return [
            Plan.model_validate_json(r["body"])
            for r in s.store.rows(
                "SELECT body FROM plan_versions WHERE id=? ORDER BY version", (plan_id,)
            )
        ]

    @app.post(prefix + "/plans/{plan_id}/validate", response_model=Verdict)
    def validate_plan(plan_id: str, s: Service = Depends(svc)):
        return s.validate(s.plan(plan_id))

    @app.get(prefix + "/plans/{plan_id}/approvals", response_model=list[ApprovalRecord])
    def approvals(plan_id: str, s: Service = Depends(svc)):
        return s.approvals(plan_id)

    @app.post(prefix + "/plans/{plan_id}/approvals", response_model=ApprovalRecord)
    def approve(
        plan_id: str,
        request: ApprovalRequest,
        role: Role = Depends(persona),
        s: Service = Depends(svc),
    ):
        return s.approve(plan_id, request, role)

    @app.post(prefix + "/plans/{plan_id}/simulate", response_model=RunTrace)
    def simulate(
        plan_id: str,
        request: SimulationRequest,
        role: Role = Depends(persona),
        s: Service = Depends(svc),
    ):
        return s.simulate(plan_id, request, role)

    @app.get(prefix + "/runs/{run_id}", response_model=RunTrace)
    def trace(run_id: str, s: Service = Depends(svc)):
        return s.trace(run_id)

    @app.get(prefix + "/audit", response_model=list[AuditRecord])
    def audit(limit: int = Query(default=100, ge=1, le=1000), s: Service = Depends(svc)):
        return s.audit(limit)

    @app.get(prefix + "/integrations", response_model=list[Connection])
    def integrations(s: Service = Depends(svc)):
        return s.connections()

    @app.get(prefix + "/items", response_model=list[dict])
    def items(s: Service = Depends(svc)):
        return s.store.bodies("items")

    @app.get(prefix + "/outbox", response_model=list[dict])
    def outbox(s: Service = Depends(svc)):
        return s.outbox()

    @app.post(prefix + "/webhooks", response_model=EventReceipt, status_code=202)
    async def webhook(request: Request):
        return app.state.webhooks.accept(
            await request.body(),
            request.headers.get("X-AgentFlow-Timestamp", ""),
            request.headers.get("X-AgentFlow-Event-Id", ""),
            request.headers.get("X-AgentFlow-Signature", ""),
        )

    @app.get(prefix + "/events", response_model=list[EventRecord])
    def events():
        return app.state.webhooks.records()

    @app.post(prefix + "/events/process", response_model=list[EventRecord])
    def process(role: Role = Depends(persona), s: Service = Depends(svc)):
        s.require(role, {"editor", "admin"})
        return app.state.webhooks.process_due()

    @app.get(prefix + "/eval/runs", response_model=list[EvaluationReport])
    def eval_runs(s: Service = Depends(svc)):
        return s.store.bodies("eval_runs")

    @app.get(prefix + "/eval/runs/{run_id}", response_model=EvaluationReport)
    def eval_run(run_id: str, s: Service = Depends(svc)):
        return s.store.body("eval_runs", run_id)

    @app.post(prefix + "/eval/runs", response_model=EvaluationReport, status_code=201)
    def evaluate_cases(role: Role = Depends(persona), s: Service = Depends(svc)):
        s.require(role, {"editor", "admin"})
        from agentflow.config import DATA
        from agentflow.eval.run import evaluate_dataset

        report = evaluate_dataset(
            DATA / "eval_cases.jsonl", provider=s.settings.provider, settings=s.settings
        )
        with s.store.transaction() as db:
            db.execute("INSERT INTO eval_runs VALUES (?,?)", (report["id"], json.dumps(report)))
            s.store.audit(
                db, "evaluation", {"eval_id": report["id"], "case_count": len(report["cases"])}
            )
        return report

    return app


app = create_app()

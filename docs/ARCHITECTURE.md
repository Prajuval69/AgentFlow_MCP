# Architecture

Implementation note: flat modules implement the layers below, with no empty service packages. REST/MCP share `Service` and SQLite. Evaluation uses isolated databases and embeds traces. SQLite migration version 1 refuses newer versions; BEGIN IMMEDIATE serializes mutations/idempotency across connections. Events use processing leases and persisted identities. Simulation uses an injectable timestamp clock and virtual delay counter; audit timestamps use UTC wall time. MCP tests initialize real SDK stdio subprocess sessions. Streamlit AppTest tests talk over real HTTP to a running loopback Uvicorn server. Mock mode has no outbound sockets; the custom API stub is entirely in-process. See README and IMPLEMENTATION_STATUS for executed evidence.

Browser (Streamlit) -> FastAPI -> application services <- MCP server using official SDK

Service layer: catalog, retriever, plan generator, strict validator, simulator, approval/policy, event processor, evaluation.
Persistence: SQLite (plans, versions, documents, simulations, approvals, traces, processed event IDs, retry/dead-letter queue). Data access via repository layer.
Providers: DeterministicMockProvider (required), OllamaProvider (optional). Dependency injection prevents network in mock mode.
Adapters: simulated SharePoint lists, simulated mail/Teams notifications, mock Azure role personas; strict typed interfaces allow future real adapters, but no real adapter is required.

Agent policy: allowlisted tools -> explicit user role check -> dry-run -> approval for protected actions -> execute in simulator -> append immutable-ish audit event. Reject unsafe/unknown actions. Do not infer approvals automatically.

Suggested src layout (Codex should implement):
```
src/agentflow/{api,config,domain,storage,agent,retrieval,tools,mcp_server,integrations,simulator,eval,security}/
ui/app.py
scripts/{seed.py,demo.py,run_eval.py}
tests/{unit,integration,mcp,security,eval}/
```

Security assumptions: local demonstration uses dev-only persona switching (visibly MOCK). Never call it authenticated identity. In production, real auth requires issuer/audience/signature/JWKS validation, scope checks and secret lifecycle management.

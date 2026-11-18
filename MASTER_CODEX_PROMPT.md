# MASTER CODEX PROMPT — Build AgentFlow MCP autonomously

## Role and outcome
Act as principal Python AI/LLM platform engineer. Build a demonstrable **MCP-Based AI Workflow Automation & Integration Copilot** from the specification in this repository. Work end to end without asking for standard design decisions. Make sensible choices and record them.

## Product
User describes an enterprise workflow in natural language (for example, invoice > INR 50,000 -> manager approval -> finance notification). Agent retrieves allowlisted documentation, generates a **schema-constrained plan** composed of supported actions, invokes MCP tools for action lookup/plan validation/simulation, exposes REST and webhook APIs, records audit traces, and reports test/evaluation outcomes. Provide usable Streamlit dashboard and CLI.

## Functional requirements
1. Backend: FastAPI API with health, catalogs, documents, plans (create, validate, simulate, list, detail), eval runs, events, audit logs. OpenAPI docs. Explicit `/api/v1` versioning and response validation.
2. Typed domain: Pydantic v2 models for conditions, actions, connections, plans, validation issues, run trace, event envelope, tool input/output, verdict, document provenance. Reject missing/extra or invalid fields; normalize IDs.
3. Local MCP server: official Python MCP SDK with **executable** tools `search_action_catalog`, `analyze_workflow`, `generate_workflow_plan`, `validate_workflow_plan`, `simulate_workflow`, `get_run_trace`, resources for allowlisted catalog/docs, plus clear description and sample client. Tools share the same service-layer logic as REST. Test MCP protocol invocation via a real SDK client (in-memory transport or subprocess as documented by chosen SDK version).
4. Agent/planning: deterministic mock provider produces valid plans for at least 5 seeded scenarios, and reasoned unsupported/manual-review for at least 3. Optional Ollama provider behind configuration and health check; no requirement for paid APIs. Strict output schema + retries only on transport/schema failures, capped; never silently fabricate completion.
5. Retrieval: bundled curated documents, per-document version and source ID; lexical TF-IDF/BM25/SQLite FTS or local-only embeddings when available; grounded passages/citations for mapping decisions; instruction-injection resistant treatment of retrieved text. Seed catalog/docs included.
6. Simulators: SharePoint-like lists/items, M365-like notifications, and Azure identity mock persona roles with explicit simulation mode; persist operations and timestamps; no external tenant calls. Do not present mock tokens as real Azure verified JWTs. Enforce simulation RBAC policy per tool; credentials not used.
7. REST integration: support custom API action against an internal stub service only. Strict endpoint allowlist, bounded payload, timeouts and retries; no SSRF or arbitrary outbound requests.
8. Webhooks: signed local HMAC-SHA256 event delivery, timestamp tolerance and replay protection, idempotency keys, controlled retry with backoff, dead-letter records. Constant-time signature comparison. Include fixture-driven tests for valid/invalid/replayed/duplicate events.
9. Evaluation: offline cases test catalog mapping accuracy, schema-valid outputs, plan/tool execution fidelity, unsupported-detection precision/recall, tool call failure responses, retrieval source correctness, simulated business outcomes and latency. Each metric denominator documented; seeded targets only become achievements after measurement.
10. Dashboard: clear controls for planning, retrieved evidence, graphical/stepwise flow, validation, simulation event timeline, approvals, webhooks, model provider and mode status, evaluation metrics and case inspection. Every action wired to working backend.
11. Engineering: structured logs, request IDs, durable SQLite migrations/initialization, clean config with .env.example, protected local dev routes, human review and auditability, responsive error handling, type-check optional, CI pytest/lint.
12. Developer experience: instructions for Windows PowerShell and macOS/Linux, seeds, working demos, OpenAPI examples, unit/integration/e2e tests and security considerations.

## Milestones (complete all)
M0. Read docs, choose architecture, set up venv/pyproject and verify offline install approach.
M1. Models, catalog, fixtures, deterministic provider, reproducible seeding.
M2. Retrieval, planner, policy/validation engine and simulator with audit trace.
M3. FastAPI, SQLite, webhook HMAC, mock enterprise adapters and typed errors.
M4. Official MCP server/client with protocol-level tests.
M5. Streamlit dashboard plus documented CLI demos.
M6. Evaluation harness, fixtures, report output, security/edge-case tests, CI and README.
M7. Run everything, fix failures, include actual measured metrics and limitations. Do not stop after scaffolding.

## Hard constraints and reality checks
- No paid services, no mandatory Docker, no Azure account or Nintex or M365 access. The offline fixture scenarios are **synthetic**.
- This project is NOT a real M365 agent, authentic Azure AD flow, nor an importable Power Automate converter; it demonstrates engineering patterns using mock enterprise adapters.
- Do not hardcode vendor API credentials or misleading compatibility claims. Optional real integration contract may be documented as future work and isolated by feature flags, never required by tests.
- MCP support means real protocol implementation, not an HTTP endpoint merely named MCP.
- LLM must not be allowed to execute arbitrary unapproved tools. Protected actions must require approvals.
- Every failure case produces a structured error and a durable trace, not false PASS.

## Definition of Done
1. Fresh machine installs and starts with documented commands and no API keys.
2. Demo for invoice approval can be generated, validated, simulated, and audited via UI/API/MCP.
3. Three more supported workflows; unsupported cases correctly routed to review.
4. Webhook signing/replay/idempotency and RBAC negative tests pass.
5. Golden eval suite produces JSON and readable report with actual results.
6. Unit, integration and real MCP protocol smoke tests pass with no cloud access.
7. README, docs, examples and STATUS truthfully reflect what has and has not been tested.

Start implementing now. Maintain the status file and finish the deliverable autonomously.

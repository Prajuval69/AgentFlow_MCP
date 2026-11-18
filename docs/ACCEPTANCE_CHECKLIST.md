# Acceptance criteria

- [x] Clean isolated wheel installation and startup verified on Windows/Python 3.12.4 without paid credentials or Docker; socket-blocked runtime smoke passed.
- [x] FastAPI OpenAPI and typed endpoints/errors exercised through TestClient and actual HTTP startup.
- [x] Official SDK MCP stdio server/client tool and resource invocation verified with subprocess protocol tests.
- [x] Deterministic planner produces valid plans for five supported golden fixtures, plus local update/summary templates; unsupported cases require review.
- [x] Retrieval provides stable source IDs/versions/hashes and untrusted evidence; malicious passage test passed.
- [x] Simulator has deterministic paths/virtual delays and an injectable clock; records outcomes and explicit reviewer decisions.
- [x] SQLite items/outbox/approvals/plans/versions/runs persist; no real tenant effects.
- [x] Signed webhook timestamp/signature/dedup/conflict/retry/dead-letter tests and concurrent delivery/processing checks passed.
- [x] Mock RBAC, missing approval, approval bypass and stale version tests passed.
- [x] Evaluator generated real JSON/Markdown metrics, per-case evidence/traces and four negative tool probes.
- [x] Streamlit controls exercised against a running local REST backend; installed server startup verified.
- [x] Local test suite passed (104 tests, no skips, 94% coverage) and Ruff passed. CI matrix is configured; hosted CI has **not** run in this non-Git workspace.
- [x] README/status include platform commands, actual proof and explicit limitations. Live Ollama and non-Windows environments remain unverified.

# AgentFlow MCP implementation status

Updated 2026-10-14. Read AGENTS.md, MASTER_CODEX_PROMPT.md and all repository docs completely.

- [x] M0: Python 3.12 isolated .venv; editable install with development dependencies executed.
- [x] M1: strict Pydantic v2 contracts, catalog schemas, five golden supported scenarios and three review cases, idempotent seeds.
- [x] M2: local TF-IDF retrieval with source hashes; conservative deterministic planner; DAG policy; stored reviewer decisions and RBAC; durable simulations.
- [x] M3: versioned FastAPI routes, SQLite migration version 1, simulated adapters, in-process allowlisted API stub, signed webhook queue.
- [x] M4: official MCP SDK stdio server/client, six tools and three resources; real subprocess protocol tests executed.
- [x] M5: Streamlit and CLI; all dashboard views, plan edits, approval decisions and simulations exercised against a running REST backend; installed Streamlit startup verified.
- [x] M6: measured evaluation with explicit fixture data/decisions, JSON/Markdown reports, security/edge cases, real MCP tests, CI matrix and Windows/Unix README.
- [x] M7: failures fixed; full tests, coverage, Ruff, socket-blocked smoke, benchmark, offline clean-venv installation, installed MCP client and actual API/UI startup verified on Windows/Python 3.12.4.

## Decisions

REST/MCP share one Service. SQLite BEGIN IMMEDIATE serializes executions and idempotency across workers. Approvals bind to plan hashes; edits preserve versions and revoke decisions. Mock personas are explicitly not authentication. API restricts loopback, Host and browser origins; no tenant token verification. Default provider is mock and all integrations are simulated. Retrieved passages are never evaluated as instructions. Custom API calls dispatch to an in-process allowlisted stub, with two attempts and a bounded processing budget; no socket or arbitrary URL access. Webhooks use HMAC over timestamp + '.' + raw body, persistent event IDs/signatures, idempotency, leases and a three-attempt queue. Event processing is explicit via API/CLI/dashboard.

## Final executed checks

- `.venv/Scripts/python.exe -m pip install -e '.[dev]'`: succeeded; MCP SDK 1.30.0 installed.
- `.venv/Scripts/python.exe -m agentflow.mcp_client`: succeeded; initialized real SDK subprocess session, listed six tools, read resource, generated/validated/simulated workflow and fetched trace.
- `.venv/Scripts/python.exe -m pytest -q --cov=agentflow --cov=ui --cov-report=term-missing --cov-report=xml:reports/coverage.xml`: **104 passed**, **0 skipped**, **94% statement coverage** (agentflow + UI), **21.47s**. One upstream Starlette TestClient/httpx deprecation warning; it is not suppressed. Earlier plain `python -m pytest -q` runs also passed; final coverage command runs the entire suite.
- `.venv/Scripts/python.exe -m ruff check .`: **All checks passed**. Import/format/zip issues fixed.
- `.venv/Scripts/python.exe scripts/offline_smoke.py`: **passed** with every socket connection attempt blocked during application work; invoice approval/rejection/threshold branches, review routing, signed-event duplication and all eight evaluation cases exercised. Windows asyncio self-pipe initializes before the guard; regression covered by a subprocess test.
- `.venv/Scripts/python.exe -m agentflow.eval.run --dataset fixtures/eval_cases.jsonl --output reports/eval.json`: **passed**; actual JSON and Markdown reports generated. Metrics below.
- `.venv/Scripts/python.exe -m pip wheel '.[dev]' --wheel-dir reports/wheelhouse`: **built** project and all runtime/dev dependency wheels for this Windows/Python environment. Rebuilt the project wheel after the final runtime fix.
- `python -m venv reports/clean-venv`, followed by `reports/clean-venv/Scripts/python.exe -m pip install --no-index --find-links reports/wheelhouse 'agentflow-mcp[dev]'`: **succeeded** without an index. Updated the final project wheel with `--no-index --no-deps --force-reinstall`.
- `reports/clean-venv/Scripts/python.exe -m pip check`: **No broken requirements found**.
- `reports/clean-venv/Scripts/python.exe scripts/offline_smoke.py`: **passed** against the installed wheel, not the editable checkout. Verified package modules match wheel contents byte-for-byte.
- Installed-wheel SDK sample client, run outside the repository import root: **passed**; module path confirmed `reports/clean-venv/Lib/site-packages/agentflow`, real stdio initialization/resource/tool calls completed.
- `reports/clean-venv/Scripts/python.exe scripts/verify_startup.py`: **passed**; actual Uvicorn and Streamlit subprocesses started on ephemeral loopback ports, health checks succeeded, and invoice approval over real HTTP ended `finance_notified_simulated`. Owned subprocesses were stopped; pre-existing services on 8000/8501 were untouched. Proof in `reports/startup.json`.

## Actual benchmark (eight synthetic cases)

| Metric | Observed result |
|---|---:|
| Schema validity (including review plans) | 8 / 8 |
| Ordered unique action mapping | 5 / 5 supported cases |
| Unsupported precision / recall / F1 | 1.0 / 1.0 / 1.0 (TP=3, FP=0, FN=0) |
| Tool dispatch correctness | 21 / 21 expected path positions |
| Retrieval: all required source IDs in top 3 | 8 / 8 |
| Completed business outcome fidelity | 5 / 5 supported cases |
| Structured negative SDK-handler responses | 4 / 4 |
| Observed nearest-rank latency p50 / p95 | 4.7642 ms / 8.4873 ms (8 samples) |

Reports contain definitions, expected/predicted actions, full plans/citations, verdicts, reviewer-fixture decisions through traces, scores and measured case durations. Evaluation traces are embedded in isolated reports; they are not IDs in the dashboard run store. The arbitrary external endpoint label `rejected` is implemented as non-executable manual review; unsupported detection is scored, not a fabricated terminal business outcome. Negative handler probes supplement actual subprocess protocol tests.

Validated fixes include SDK constructor/schema enforcement, AppTest path resolution, approval/version binding, no false successful failure branches, mixed workflow requests routing to review, safe numeric parsing, cross-worker idempotency, webhook invalid signatures/duplicates/retries/dead letters and Windows asyncio IPC handling. A no-build-isolation wheel attempt failed because setuptools was absent from the venv; the standard isolated build succeeded and the resulting wheel was reinstalled and reverified.

## Versions and artifacts

Executed on Windows, Python 3.12.4, MCP 1.30.0, Pydantic 2.14.1, FastAPI 0.143.1, Starlette 1.8.0, Streamlit 1.65.0, pytest 9.1.1 and Ruff 0.17.0. Proof artifacts: `reports/eval.json`, `reports/eval.md`, `reports/offline_smoke.json`, `reports/coverage.xml`, `reports/startup.json`, startup logs and the platform-specific wheelhouse. These generated files are ignored by Git.

## Boundaries

No real Microsoft tenant, Graph/Entra authentication, external email or Power Automate export. Local personas are not authentication. The planner supports a conservative bounded grammar and routes unknown or mixed capabilities to review. Golden scenarios are synthetic and their scores are not live LLM accuracy. Optional Ollama has controlled transport/schema tests; a live model has not been tested. Hosted CI, Python 3.11, Linux and macOS have not been executed locally; CI is configured for Windows/Linux and Python 3.11/3.12. Package acquisition may require internet; the verified platform-specific wheelhouse enables offline installation and mock runtime needs no outbound network. This workspace has no Git repository, so no commit/PR or hosted CI execution is claimed.

Webhook processing is explicit rather than an always-running worker. The in-process stub budget is measured after execution, not a cancellable hard deadline, and only bounded local SQL is registered. Audit redaction recognizes sensitive key names, not arbitrary free-text secrets; use synthetic data. Audit is application-append-only, not tamper-proof against DB owners. Simulations retain earlier local side effects if a later step fails, and durably report failures rather than pretending to roll back a whole workflow.


## Publication — 2026-11-18

Published the source to the public repository https://github.com/Prajuval69/AgentFlow_MCP on main. Git was initialized in this workspace for publication; earlier statements that the workspace had no Git repository describe the October verification session. Generated reports, virtual environments, SQLite databases, build outputs and egg-info were excluded. A scan of all 57 staged source/document files found no common credential patterns; .env.example contains placeholders only.

Re-ran `.venv/Scripts/python.exe -m pytest -q`: **104 passed**, one upstream Starlette/httpx deprecation warning, **33.03s**, no skips. Source push and the public repository file listing were verified. GitHub Actions was triggered by the push; no hosted CI success is claimed in this publication record.

A live deployment was investigated. Sites hosting does not run this Python/FastAPI/Streamlit stack directly. Streamlit Community Cloud reached a sign-in page that requires agreeing to deployment terms, so no account agreement or deployment was completed. The user's authorized GitHub-only fallback is delivered. No free-tier exhaustion was observed and no hosting charges were incurred.

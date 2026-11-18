# AgentFlow MCP

An offline workflow copilot with a versioned FastAPI backend, official Python MCP SDK server, local retrieval, typed workflow plans, SQLite audit records, signed webhooks, a CLI and a Streamlit dashboard.

**SIMULATION — NOT CONNECTED TO MICROSOFT TENANT.** SharePoint, M365 and Azure identity examples are local simulators. Personas are local role switches, not authentication. Plans are internal schemas, not Power Automate packages. All records and evaluation cases are synthetic.

## Install and start

Python **3.11+** is required. No API keys, Docker, paid service, model download or cloud account is needed. Installation downloads Python dependencies unless you prepare the offline wheelhouse below. Mock runtime uses no outbound network; the UI talks only to the local API.

Windows PowerShell, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
$env:PROVIDER = 'mock'
$env:INTEGRATIONS = 'simulated'
.\.venv\Scripts\python.exe -m agentflow.cli seed
.\.venv\Scripts\python.exe -m uvicorn agentflow.api:app --host 127.0.0.1 --port 8000 --no-access-log
```

In another PowerShell terminal at the same repository root:

```powershell
.\.venv\Scripts\python.exe -m streamlit run ui/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export PROVIDER=mock INTEGRATIONS=simulated
python -m agentflow.cli seed
python -m uvicorn agentflow.api:app --host 127.0.0.1 --port 8000 --no-access-log
# In another terminal, activate the same environment:
python -m streamlit run ui/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open [dashboard](http://127.0.0.1:8501), [OpenAPI docs](http://127.0.0.1:8000/docs), or [health](http://127.0.0.1:8000/api/v1/health). Run from the repository root so Streamlit loads the checked-in configuration disabling usage telemetry. API startup seeds missing records without overwriting existing data. SQLite is created in `data/agentflow.sqlite3` by default.

## Demonstrate the workflow

1. Select **editor** in the dashboard and generate the invoice approval example.
2. Inspect document IDs, versions, hashes and passages. Validate the plan and inspect both branches.
3. Simulate with `{"total_amount":75000}`. It blocks without an explicit reviewer decision.
4. Switch to **reviewer**, record `approved` for the `approve` step, switch back to **editor**, and simulate. Inspect the local outbox and audit log.
5. Record `rejected` and simulate again: the rejection branch produces no notification. An amount of `25000` follows the below-threshold branch.
6. Try a real M365 email request: it produces an empty, non-executable manual-review plan.
7. Use the other views for persisted records, signed events, queue processing, evaluation metrics and case inspection.

Run the same branches and signed webhook checks with outbound sockets blocked:

```powershell
.\.venv\Scripts\python.exe scripts/offline_smoke.py
.\.venv\Scripts\python.exe -m agentflow.cli demo --output reports/demo.json
.\.venv\Scripts\python.exe -m agentflow.mcp_client
```

On Unix, use `python` in the activated environment. The smoke script creates an ephemeral secret and in-memory database; it always exercises webhooks. The ordinary CLI demo only exercises webhooks when a secret is configured, and reports `webhooks: null` otherwise.

## Supported planning templates

The deterministic mock provider is a **bounded grammar**, not a general LLM. Unrecognized vocabulary, mixed capabilities, real integrations and unsafe requests require review. Examples:

| Request | Actions | Outcome |
|---|---|---|
| If invoice amount exceeds INR 50000, request manager approval and notify finance | trigger, compare, approval, notification, terminal branches | finance notified or rejected, locally |
| For invoices below INR 50000 log an event and close | trigger, compare, log, terminal branches | closed or above threshold |
| Create a local SharePoint-like invoice item and notify reviewer | trigger, create, notification, terminate | synthetic item created |
| Look up local invoice INV-1002 and record the result | trigger, lookup, log, terminate | lookup recorded |
| Wait a simulated day and then notify the owner | trigger, virtual delay, notification, terminate | local notification after 86400 virtual seconds |
| Update a local invoice INV-1002 | trigger, update, notification, terminate | fixed synthetic status update |
| Query the internal invoice summary | trigger, allowlisted stub, terminate | local summary |

Create/update templates visibly disclose synthetic defaults. Use the plan editor to change typed item fields, notification text, delay or branching. Plan edits increment the version, preserve history and revoke all approvals. Malformed/unknown actions return a review verdict and cannot execute. Numeric conditions safely coerce bounded numeric strings; missing/nonfinite/invalid data fails with a durable trace. No expressions are evaluated as Python or JavaScript.

## MCP

Start the official SDK **stdio** server:

```powershell
.\.venv\Scripts\python.exe -m agentflow.mcp_server
```

An MCP host should launch that command with its absolute Python executable, working directory and `AGENTFLOW_DB_URL` pointing at the same SQLite database as REST. `agentflow-mcp` is also an installed console entrypoint. No listening MCP port or tenant token is used. The sample client launches a subprocess, initializes the real protocol, reads a resource and invokes tools:

```powershell
.\.venv\Scripts\python.exe -m agentflow.mcp_client
```

Tools: `search_action_catalog`, `analyze_workflow`, `generate_workflow_plan`, `validate_workflow_plan`, `simulate_workflow`, `get_run_trace`. Resources: `agentflow://catalog`, `agentflow://documents`, `agentflow://schema`. Tool schemas reject extra fields and raw type errors before SDK convenience coercion. Domain errors include structured codes and durable audit trace IDs. Unknown tools return MCP errors. Tools cannot choose a persona, grant approvals, access paths, execute shell commands or send arbitrary HTTP requests. The fixed server persona defaults to editor and is configured by the trusted operator with `AGENTFLOW_MCP_PERSONA`.

## REST and CLI

All application endpoints use `/api/v1`. [API examples](docs/API_EXAMPLES.md) show complete PowerShell and curl flows.

| Endpoint | Behavior |
|---|---|
| `GET /health`, `/catalog`, `/documents`, `/documents/search`, `/schema` | mode, provider status, catalog, local evidence, JSON Schema |
| `POST /analyze`, `POST /plans`, `GET /plans`, `GET /plans/{id}` | analyze, generate and inspect plans |
| `PUT /plans/{id}`, `GET /plans/{id}/versions` | versioned editing; approvals revoked |
| `POST /plans/validate`, `POST /plans/{id}/validate` | raw or saved plan validation |
| `GET/POST /plans/{id}/approvals` | explicit local reviewer decisions |
| `POST /plans/{id}/simulate`, `GET /runs/{id}` | durable simulation and trace |
| `GET /items`, `/outbox`, `/integrations`, `/audit` | local adapters and audit records |
| `POST /webhooks`, `GET /events`, `POST /events/process` | signed enqueue and explicit processing |
| `GET/POST /eval/runs`, `GET /eval/runs/{id}` | isolated evaluation and persisted reports |

Mutating dev routes default to viewer and require `X-Mock-Persona: editor` or `admin`; reviewer decisions require `reviewer` or `admin`. This is demonstration RBAC, not access control against other local users. API checks client loopback, Host, browser Origin and a per-process 300/minute rate limit. It does not trust forwarded headers for identity. Do not expose this demonstration as a public service.

CLI commands:

```bash
python -m agentflow.cli plan 'If invoice amount exceeds INR 50000, request manager approval and notify finance'
python -m agentflow.cli approve PLAN_ID approve approved
python -m agentflow.cli simulate PLAN_ID --data '{"total_amount":75000}'
python -m agentflow.cli process-events
```

Use actual returned IDs. PowerShell REST examples avoid shell JSON quoting differences. Failed/blocked runs remain retrievable; an idempotency key always returns its original trace for the same plan version, data and persona. Reusing it for different inputs returns 409. After recording a new decision, use a new key or omit it.

## Webhooks and configuration

`.env.example` documents environment variables; the app does **not** automatically load `.env`. Export variables in the shell that launches each process. `PROVIDER` and `INTEGRATIONS` take precedence over their `AGENTFLOW_` aliases. Only `simulated` integrations and `offline` mode are supported; enabling real cloud access fails startup.

Webhooks are disabled until `AGENTFLOW_WEBHOOK_SECRET` is set to a locally generated secret of at least 32 characters. Generate it without putting a real secret in source or command history:

```powershell
$env:AGENTFLOW_WEBHOOK_SECRET = (& .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
# Start/restart the API in this terminal so it inherits the value.
```

Unix equivalent:

```bash
export AGENTFLOW_WEBHOOK_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Provide the same local secret to the dashboard's password field when manually signing events. It is never returned by REST. The request headers are `X-AgentFlow-Timestamp`, `X-AgentFlow-Event-Id` and `X-AgentFlow-Signature`. Sign exactly `timestamp + '.' + raw_body` using HMAC-SHA256 with the `sha256=` prefix. Timestamp tolerance is ±300 seconds; valid duplicates acknowledge idempotently, modified duplicates conflict, and stale/invalid signatures fail. Event bodies are capped at 16KB; general requests/plans at 100KB.

The queue is durable and **processed explicitly** via the dashboard, CLI or REST route. Retryable lookup/transport failures back off for 2 and 4 seconds before the third attempt; business/policy failures immediately dead-letter with a trace. Processing leases recover interrupted workers. Events do not grant approvals. Sending an event is an in-process local integration demo, not a delivery service for arbitrary destinations.

Optional Ollama: explicitly set `PROVIDER=ollama`, `AGENTFLOW_OLLAMA_MODEL` and a loopback HTTP `AGENTFLOW_OLLAMA_BASE_URL`. Health checks verify that the configured model exists. Transport/schema failures retry once; policy-invalid plans go to review. No model is downloaded automatically. This path has tests with controlled responses; live-model quality and availability have not been measured.

## Verification and offline installation

With the environment activated:

```bash
python -m pytest -q
python -m pytest -q --cov=agentflow --cov=ui --cov-report=term-missing
ruff check .
python scripts/offline_smoke.py
python scripts/verify_startup.py
python -m agentflow.eval.run --dataset fixtures/eval_cases.jsonl --output reports/eval.json
```

The evaluator writes JSON and Markdown with exact denominators, per-case plans, evidence, validation, complete traces, four negative tool probes and observed p50/p95 latency. Cases run in isolated databases so evaluations do not mutate dashboard records. Embedded evaluation trace IDs refer to the report, not the application's `/runs` store. Zero-denominator metrics are `null`, not fabricated zero or 100%. Synthetic fixture scores do not establish general LLM performance.

Prepare an offline wheelhouse **on an internet-connected machine with the same OS/Python version**:

```bash
python -m pip wheel '.[dev]' --wheel-dir wheelhouse
```

Copy it and the repository to the offline machine, create a fresh venv, then install the built package without contacting an index:

```bash
python -m pip install --no-index --find-links wheelhouse 'agentflow-mcp[dev]'
python scripts/offline_smoke.py
```

Tested commands/results and limitations are tracked in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). CI is configured for Windows/Linux and Python 3.11/3.12, including protocol, security, dashboard integration tests, coverage, lint and offline smoke. Hosted CI and macOS have not been executed in this workspace.

## Architecture and boundaries

`src/agentflow/service.py` owns application operations. `policy.py` validates catalog membership, typed inputs, evidence hashes, unique IDs, reachability, terminal paths, cycles, path depth and approvals. `storage.py` initializes SQLite migration version 1 and uses transactional event/idempotency records. `planner.py` never interprets retrieved prose as instructions. `integrations.py` performs local SQL/outbox writes and dispatches only `internal://invoice-summary`, with a 4KB payload cap and two attempts. Its one-second synchronous processing budget is checked after execution; it cannot interrupt arbitrary code, and only the bounded in-process SQL handler is registered.

Audit records are append-only through application routes but not tamper-proof against filesystem/database owners. Simulations retain any prior local side effects when a later step fails and record that failure; they are not transactional workflow rollback. Role switches, local rate limits and development guards are not production authentication. Real Entra/Graph integration would require independently implemented token verification, tenant consent, scopes, credential lifecycle and throttling. No such integration is claimed here.

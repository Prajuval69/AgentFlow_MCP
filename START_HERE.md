# AgentFlow MCP — Codex-ready project kit

A working **local-first AI Workflow Automation & Integration Copilot**. Follow [README.md](README.md) to install and start FastAPI, Streamlit and the official MCP SDK server. Actual verification and limitations are tracked in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Start
1. Extract this archive into its own repository.
2. Open the repository root in Codex.
3. Follow the README setup commands, then run `python scripts/offline_smoke.py` and the evaluation command.
4. Work in a Python 3.11+ environment. No Docker, external API keys, Azure tenant, or M365 subscription required.
5. Optional local LLM: install Ollama and pull a small model; without it use deterministic `mock` provider for fully testable behavior.

## Intended deliverable
FastAPI backend, official Python MCP SDK server, SQLite persistence, local semantic knowledge retrieval with deterministic lexical fallback, enterprise service simulators, webhook ingestion with retries/idempotency, Pydantic schemas, evaluation harness, Streamlit dashboard, pytest suite, demos, documentation and CI.

## Integrity rules
* Simulated SharePoint/M365, mocked Azure identity, and local workflows **must never** be represented as real cloud execution.
* No access to real tenants or subscriptions is assumed. Real cloud integrations are optional gated adapters, out of scope for the offline acceptance gate.
* Generated workflow plan is an **internal, typed plan**, not a deployable Power Automate package.
* Do not claim live LLM accuracy or benchmark results without actually executing and recording them.

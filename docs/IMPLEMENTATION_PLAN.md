# Detailed task breakdown for Codex

## Phase 1 Foundation
Build pyproject.toml with extras `[ollama]`, strict config defaults and type-annotated models. Seed local docs and business objects. Write parser for fixture cases and gold plan schema. Unit tests first.

## Phase 2 Core reasoning
Implement retrieval scoring and evidence link; deterministic intent classifier/rule planner with failure reasons. Optional real Ollama adapter; enforce output JSON validation. Add business rule validator and deterministic simulator. Demonstrate branching invoice threshold.

## Phase 3 Integration architecture
Introduce storage; simulated SharePoint and messaging adapters, clear mode labels, mock personas and role checks. FastAPI endpoints. HMAC webhook signing and processing, dedup/retries/dead-letter. Test concurrency/race where feasible.

## Phase 4 MCP
Use MCP Python SDK proper transport (stdio or streamable HTTP), define typed tools and resources. One service layer for both MCP and REST. Include CLI demo that uses the protocol and checks one tool/result.

## Phase 5 Demo UI
Streamlit pages for scenario input, evidence, plan editing/review, validation, simulation timeline, mock list/outbox, audit log, eval comparisons. No inert buttons. Make seeded workflows clickable examples.

## Phase 6 Harden
Evaluation runner with reports, abuse and protocol tests, CI, walkthrough, screenshots optional, README and status. Run tests before declaring completion.

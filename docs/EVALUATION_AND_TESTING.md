# Evaluation and testing specification

Implementation note: mapping compares ordered unique action types (branch terminals may duplicate). Dispatch correctness counts typed successful/false/rejected steps in their expected path positions over sum(max(expected, actual path length)); failed generations still contribute expected calls. Retrieval requires all source labels within top 3. Execution fidelity uses completed outcomes on supported cases. Four negative probes call official SDK handlers and check expected structured errors and durable audit IDs; actual stdio transport is independently tested. Case stores are isolated, complete traces are embedded, latency includes initialization/retrieval/planning/decisions/simulation, and nearest-rank percentiles are observed over eight synthetic cases. Zero denominators return null. The arbitrary-endpoint 'rejected' fixture is interpreted as a blocked manual-review disposition; unsupported detection is scored without inventing a business outcome. The smoke script blocks outbound sockets and includes signed events. Dashboard tests call a running local API. Refer to status for executed platforms and coverage.

Implement `python -m agentflow.eval.run --dataset fixtures/eval_cases.jsonl --output reports/eval.json` and a human-readable companion Markdown report. Evaluate deterministic mock by default; optional Ollama run explicitly labeled provider/model/version.

Required calculations (with actual denominators):
- schema validity rate = schema_valid / generated
- mapping exact match on labeled supported cases = matches / supported_labeled
- unsupported detection precision/recall/F1 using ground-truth flags
- tool call correctness = valid tool calls / expected+unexpected calls (document precise definition)
- retrieval hit@k = cases with required document in top k / retrieval cases
- execution fidelity = matching expected simulated terminal outcome / executable cases
- p50/p95 end-to-end latency observed at test time, never invented

Store per-case input, expected outcome, predicted plan, retrieved citations, validation issues, trace ID, score and duration. No divide-by-zero masking; mark N/A when denominator zero.

Test categories: schemas and malformed output, known/unknown action mapping, conditions, missing/unknown fields, empty prompts, long inputs, malicious document instructions, SSRF rejection, signed/unsigned webhooks, timestamp skew, replay, duplicates, retry exhaustion, RBAC, approval bypass, MCP tool invocation and error shapes, REST status codes, database persistence, non-interference/no external network in default configuration.

Minimum CI: unit and integration test suites, lint, test coverage summary. Add a fresh-install offline smoke test and write platform-specific commands.

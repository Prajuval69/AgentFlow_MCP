# Interview demo script

Executable entrypoints: follow README setup, start `python -m uvicorn agentflow.api:app --host 127.0.0.1 --port 8000 --no-access-log`, then `python -m streamlit run ui/app.py --server.address 127.0.0.1 --browser.gatherUsageStats false`. Use mock editor/reviewer switches for explicit decisions. Run `python -m agentflow.mcp_client` for real SDK invocation, `python scripts/offline_smoke.py` for the network-blocked demo including ephemeral webhook signing, and `python -m agentflow.eval.run --dataset fixtures/eval_cases.jsonl --output reports/eval.json` for real metrics. Ordinary API/CLI/UI webhooks require a separately configured secret and explicit processing. See API_EXAMPLES.md for full requests.

1. Start backend, Streamlit and MCP server per generated README.
2. Show offline/mock mode badge and local fixture catalog.
3. Enter: "When invoice total exceeds INR 50000 request manager approval, then notify finance".
4. Display retrieved action references and schema-valid plan.
5. Validate plan; run deterministic simulator twice with approve and reject decisions; inspect branches and audit trace.
6. Show fake SharePoint-style invoice record and mock message outbox; explicitly state these are local simulations.
7. Call MCP `search_action_catalog` and `simulate_workflow` via real MCP client.
8. Replay a signed webhook and show dedup; invalid signature rejected.
9. Run eval suite and point out actual metrics; show unsupported case routed to manual review.
10. State boundaries: no real Graph/Entra/Power Automate execution, optional Ollama model, synthetic examples.

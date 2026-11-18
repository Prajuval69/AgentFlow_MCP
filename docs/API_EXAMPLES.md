# Local REST examples

Start the API and use only loopback. These calls exercise **simulated** enterprise adapters. IDs are returned by the server; no token or cloud account is involved.

## PowerShell

```powershell
$base = 'http://127.0.0.1:8000/api/v1'
$editor = @{ 'X-Mock-Persona' = 'editor' }
$reviewer = @{ 'X-Mock-Persona' = 'reviewer' }
$plan = Invoke-RestMethod -Method Post -Uri "$base/plans" -Headers $editor -ContentType 'application/json' -Body (@{ prompt = 'If invoice amount exceeds INR 50000, request manager approval and notify finance' } | ConvertTo-Json)
Invoke-RestMethod -Method Post -Uri "$base/plans/$($plan.id)/validate"
Invoke-RestMethod -Method Post -Uri "$base/plans/$($plan.id)/approvals" -Headers $reviewer -ContentType 'application/json' -Body (@{ step_id = 'approve'; decision = 'approved' } | ConvertTo-Json)
$run = Invoke-RestMethod -Method Post -Uri "$base/plans/$($plan.id)/simulate" -Headers $editor -ContentType 'application/json' -Body (@{ data = @{ total_amount = 75000 }; idempotency_key = 'invoice-demo-approved' } | ConvertTo-Json)
Invoke-RestMethod -Uri "$base/runs/$($run.id)"
Invoke-RestMethod -Uri "$base/outbox"
Invoke-RestMethod -Uri "$base/audit"
# Same request/key returns the same run; changed data/key ownership conflicts (409).
```

## curl (Unix)

```bash
curl -s http://127.0.0.1:8000/api/v1/health
curl -s -H 'X-Mock-Persona: editor' -H 'Content-Type: application/json' \
  -d '{"prompt":"Wait a simulated day and then notify the owner"}' \
  http://127.0.0.1:8000/api/v1/plans
# Replace PLAN_ID with the actual id:
curl -s -H 'X-Mock-Persona: editor' -H 'Content-Type: application/json' \
  -d '{"data":{},"idempotency_key":"delay-demo"}' \
  http://127.0.0.1:8000/api/v1/plans/PLAN_ID/simulate
```

## Signed fixture event

From Python, with the same local webhook secret in the environment as the API:

```python
import json, os, time
from uuid import uuid4
import httpx
from agentflow.webhooks import sign

event_id = "event-" + uuid4().hex
body = json.dumps(
    {
        "id": event_id,
        "type": "simulate_plan",
        "plan_id": "ACTUAL_PLAN_ID",
        "data": {"total_amount": 25000},
        "idempotency_key": event_id,
    }
).encode()
timestamp = str(int(time.time()))
headers = {
    "Content-Type": "application/json",
    "X-AgentFlow-Timestamp": timestamp,
    "X-AgentFlow-Event-Id": event_id,
    "X-AgentFlow-Signature": sign(os.environ["AGENTFLOW_WEBHOOK_SECRET"], timestamp, body),
}
with httpx.Client(timeout=5, trust_env=False) as client:
    response = client.post("http://127.0.0.1:8000/api/v1/webhooks", content=body, headers=headers)
    response.raise_for_status()
    print(response.json())
    duplicate = client.post("http://127.0.0.1:8000/api/v1/webhooks", content=body, headers=headers)
    print(duplicate.json()["duplicate"])  # True; no second operation queued
    print(
        client.post(
            "http://127.0.0.1:8000/api/v1/events/process", headers={"X-Mock-Persona": "editor"}
        ).json()
    )
```

The body schema is also published through OpenAPI. Missing approval yields a dead-letter record with a blocked trace; it never auto-approves. Event processing is explicit. Changing a signed byte rejects authenticity; an expired replay rejects timestamp freshness.

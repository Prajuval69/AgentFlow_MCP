import asyncio
import json
import subprocess
import sys
from pathlib import Path

from agentflow import cli
from agentflow.mcp_client import demo


def test_cli_commands_persist_and_require_review(service, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("AGENTFLOW_DB_URL", "sqlite:///" + service.settings.db_path)
    monkeypatch.setenv("AGENTFLOW_WEBHOOK_SECRET", service.settings.webhook_secret)
    monkeypatch.setenv("PROVIDER", "mock")

    def command(*args):
        monkeypatch.setattr(sys, "argv", ["agentflow", *args])
        cli.main()
        return json.loads(capsys.readouterr().out)

    assert len(command("seed")["items"]) == 2
    plan = command("plan", cli.INVOICE_PROMPT)
    blocked = command("simulate", plan["id"], "--data", '{"total_amount":75000}')
    assert blocked["status"] == "blocked"
    assert command("approve", plan["id"], "approve", "approved")["persona"] == "reviewer"
    completed = command("simulate", plan["id"], "--data", '{"total_amount":75000}')
    assert completed["outcome"] == "finance_notified_simulated"
    assert command("process-events") == []
    output = tmp_path / "demo.json"
    result = command("demo", "--output", str(output))
    assert result["webhooks"]["duplicate"]
    assert json.loads(output.read_text())["rejected"]["outcome"] == "rejected_simulated"


def test_sample_mcp_client_is_executable(service, monkeypatch):
    monkeypatch.setenv("AGENTFLOW_DB_URL", "sqlite:///" + service.settings.db_path)
    monkeypatch.setenv("PROVIDER", "mock")
    monkeypatch.setenv("AGENTFLOW_MCP_PERSONA", "editor")
    result = asyncio.run(demo())
    assert result["resource_read"]
    assert len(result["tools"]) == 6
    assert result["run"]["outcome"] == "notified_simulated"


def test_socket_blocked_smoke_script(tmp_path):
    result = subprocess.run(
        [sys.executable, str(Path("scripts/offline_smoke.py").resolve())],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert proof["offline_network_guard"] == "passed"
    assert proof["webhook_duplicate"]
    assert proof["cases"] == 8

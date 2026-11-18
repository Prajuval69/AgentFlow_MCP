"""Disable outbound network at the socket boundary while executing the demo/eval."""

import asyncio
import json
import secrets
import socket
from pathlib import Path
from unittest.mock import patch

from agentflow.cli import offline_demo
from agentflow.config import DATA, Settings
from agentflow.eval.run import evaluate_dataset
from agentflow.service import Service


def no_network(*args, **kwargs):
    raise AssertionError("Mock runtime attempted network access")


if __name__ == "__main__":
    # Windows builds asyncio's internal self-pipe using a loopback socketpair.
    # Initialize that IPC before denying every connection during application work.
    runner = asyncio.Runner()
    runner.get_loop()
    with (
        runner,
        patch.object(socket.socket, "connect", no_network),
        patch.object(socket, "create_connection", no_network),
    ):
        service = Service(Settings(db_path=":memory:", webhook_secret=secrets.token_hex(32)))
        try:
            result = offline_demo(service)
            evaluation = evaluate_dataset(DATA / "eval_cases.jsonl", async_runner=runner.run)
            assert all(c["score"] == 1 for c in evaluation["cases"])
            result["evaluation_metrics"] = evaluation["metrics"]
            Path("reports").mkdir(exist_ok=True)
            Path("reports/offline_smoke.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "offline_network_guard": "passed",
                        "approved": result["approved"]["outcome"],
                        "rejected": result["rejected"]["outcome"],
                        "webhook_duplicate": result["webhooks"]["duplicate"],
                        "cases": len(evaluation["cases"]),
                    }
                )
            )
        finally:
            service.store.close()

"""Verify installed API/Streamlit entrypoints on ephemeral loopback ports, then stop them."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(client: httpx.Client, url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Startup process exited; inspect reports/startup_*.log")
        try:
            if client.get(url).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise TimeoutError("Local startup health check timed out")


def main() -> None:
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    api_port, ui_port = free_port(), free_port()
    base = f"http://127.0.0.1:{api_port}/api/v1"
    env = {
        **os.environ,
        "PROVIDER": "mock",
        "INTEGRATIONS": "simulated",
        "AGENTFLOW_DB_URL": "sqlite:///" + str(reports / "startup.sqlite3"),
        "AGENTFLOW_API_URL": f"http://127.0.0.1:{api_port}",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
    }
    processes = []
    try:
        with (
            (reports / "startup_api.log").open("w") as api_log,
            (reports / "startup_ui.log").open("w") as ui_log,
        ):
            for args, log in [
                (
                    [
                        "-m",
                        "uvicorn",
                        "agentflow.api:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                        "--no-access-log",
                    ],
                    api_log,
                ),
                (
                    [
                        "-m",
                        "streamlit",
                        "run",
                        "ui/app.py",
                        "--server.address",
                        "127.0.0.1",
                        "--server.port",
                        str(ui_port),
                        "--browser.gatherUsageStats",
                        "false",
                    ],
                    ui_log,
                ),
            ]:
                processes.append(
                    subprocess.Popen(
                        [sys.executable, *args],
                        cwd=ROOT,
                        env=env,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                )
            with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
                wait_ready(client, base + "/health", processes[0])
                wait_ready(client, f"http://127.0.0.1:{ui_port}/_stcore/health", processes[1])
                health = client.get(base + "/health").json()
                response = client.post(
                    base + "/plans",
                    headers={"X-Mock-Persona": "editor"},
                    json={
                        "prompt": "If invoice amount exceeds INR 50000, request manager approval and notify finance"
                    },
                )
                response.raise_for_status()
                plan = response.json()
                reviewed = client.post(
                    base + f"/plans/{plan['id']}/approvals",
                    headers={"X-Mock-Persona": "reviewer"},
                    json={"step_id": "approve", "decision": "approved"},
                )
                reviewed.raise_for_status()
                simulation = client.post(
                    base + f"/plans/{plan['id']}/simulate",
                    headers={"X-Mock-Persona": "editor"},
                    json={"data": {"total_amount": 75000}},
                )
                simulation.raise_for_status()
                assert simulation.json()["outcome"] == "finance_notified_simulated"
                report = {
                    "mode": "simulated",
                    "health": health,
                    "api_started": True,
                    "streamlit_started": True,
                    "run": simulation.json(),
                    "python": sys.executable,
                    "scope": "Real subprocess startup/health and REST approval execution. UI controls are independently exercised by AppTest.",
                }
                (reports / "startup.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8"
                )
                print(
                    json.dumps(
                        {
                            "api_started": True,
                            "streamlit_started": True,
                            "outcome": simulation.json()["outcome"],
                        }
                    )
                )
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()

"""Streamlit AppTest exercises real HTTP against a running local FastAPI server."""

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from streamlit.testing.v1 import AppTest

from agentflow.api import create_app


@pytest.fixture
def live_backend(service, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(service), log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "Local backend did not start"
    monkeypatch.setenv("AGENTFLOW_API_URL", f"http://127.0.0.1:{port}")
    yield service
    server.should_exit = True
    thread.join(timeout=10)
    sock.close()
    assert not thread.is_alive()


def click(app, label):
    next(button for button in app.button if button.label == label).click().run(timeout=30)
    assert not app.exception
    assert not app.error


def test_dashboard_workflow_review_records_events_eval(live_backend):
    app = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=30).run()
    assert not app.exception
    assert not app.error
    click(app, "Analyze & retrieve")
    click(app, "Generate plan")
    click(app, "Validate saved plan")
    click(app, "Simulate saved plan")
    assert app.session_state["run"]["status"] == "blocked"
    app.sidebar.selectbox[0].set_value("reviewer").run()
    click(app, "Record reviewer decision")
    app.sidebar.selectbox[0].set_value("editor").run()
    click(app, "Simulate saved plan")
    assert app.session_state["run"]["outcome"] == "finance_notified_simulated"
    plan_id = app.session_state["plan"]["id"]
    app.sidebar.radio[0].set_value("Records & outbox").run()
    assert not app.exception
    assert len(live_backend.outbox()) == 1
    app.sidebar.radio[0].set_value("Webhooks").run()
    next(widget for widget in app.text_input if widget.label == "Plan ID").set_value(plan_id)
    next(
        widget for widget in app.text_input if widget.label == "Local webhook signing secret"
    ).set_value(live_backend.settings.webhook_secret)
    click(app, "Send signed local event")
    click(app, "Process due events")
    assert live_backend.store.rows("SELECT status FROM events")[0]["status"] == "completed"
    app.sidebar.radio[0].set_value("Evaluations").run()
    click(app, "Run golden evaluation")
    assert len(live_backend.store.bodies("eval_runs")) == 1
    app.sidebar.radio[0].set_value("Audit & catalog").run()
    assert not app.exception
    assert len(app.json) >= 2


def test_dashboard_edit_and_load(live_backend):
    app = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=30).run()
    click(app, "Use example")
    click(app, "Generate plan")
    click(app, "Load saved plan")
    import json

    plan = app.session_state["plan"].copy()
    plan["title"] = "UI edited plan"
    next(widget for widget in app.text_area if widget.label == "Plan JSON").set_value(
        json.dumps(plan)
    )
    click(app, "Save plan edit")
    assert app.session_state["plan"]["version"] == 2
    assert app.session_state["plan"]["title"] == "UI edited plan"

"""Streamlit dashboard backed entirely by the loopback REST application."""

import json
import os
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import streamlit as st

from agentflow.config import DATA
from agentflow.webhooks import sign

st.set_page_config(page_title="AgentFlow MCP — Simulation", layout="wide")
st.title("AgentFlow MCP")
st.warning(
    "SIMULATION — NOT CONNECTED TO MICROSOFT TENANT. Personas are local mock roles, not authenticated identities."
)
base = os.getenv("AGENTFLOW_API_URL", "http://127.0.0.1:8000")
parsed = urlsplit(base)
if (
    parsed.scheme != "http"
    or parsed.hostname not in {"localhost", "127.0.0.1"}
    or parsed.username
    or parsed.password
    or parsed.path not in {"", "/"}
    or parsed.query
    or parsed.fragment
):
    st.error("Dashboard API URL must be a loopback HTTP origin.")
    st.stop()
role = st.sidebar.selectbox(
    "LOCAL MOCK persona", ["viewer", "editor", "reviewer", "admin"], index=1
)
page = st.sidebar.radio(
    "View", ["Workspace", "Records & outbox", "Webhooks", "Evaluations", "Audit & catalog"]
)


def api(method: str, path: str, **kwargs):
    try:
        with httpx.Client(timeout=120, trust_env=False, follow_redirects=False) as client:
            response = client.request(
                method,
                base.rstrip("/") + "/api/v1" + path,
                headers={"X-Mock-Persona": role, **kwargs.pop("headers", {})},
                **kwargs,
            )
        if response.is_error:
            st.error(response.json())
            return None
        return response.json()
    except (httpx.HTTPError, ValueError):
        st.error("Backend unavailable or returned invalid JSON. Start the local API per README.")
        return None


health = api("GET", "/health")
if health:
    st.sidebar.json(health)

if page == "Workspace":
    examples = [
        json.loads(line)["input"] for line in (DATA / "eval_cases.jsonl").read_text().splitlines()
    ]
    example = st.selectbox("Seeded example", examples)
    if st.button("Use example"):
        st.session_state["prompt"] = example
    prompt = st.text_area("Workflow request", value=examples[0], key="prompt", height=100)
    left, right = st.columns(2)
    if left.button("Analyze & retrieve"):
        analysis = api("POST", "/analyze", json={"prompt": prompt})
        if analysis:
            st.json(analysis)
    if right.button("Generate plan", disabled=role not in {"editor", "admin"}):
        plan = api("POST", "/plans", json={"prompt": prompt})
        if plan:
            st.session_state["plan"] = plan
            st.session_state.pop("plan_json", None)
    plans = api("GET", "/plans") or []
    if plans:
        selected = st.selectbox(
            "Saved plan",
            [p["id"] for p in plans],
            format_func=lambda pid: next(
                p["title"] + " · " + pid[-8:] for p in plans if p["id"] == pid
            ),
        )
        if st.button("Load saved plan"):
            st.session_state["plan"] = api("GET", "/plans/" + selected)
            st.session_state.pop("plan_json", None)
    plan = st.session_state.get("plan")
    if plan:
        st.subheader(plan["title"])
        st.caption(
            f"Version {plan['version']} · provider {plan['provider']} · internal plan schema {plan['schema_version']}"
        )
        for warning in plan["warnings"]:
            st.info(warning)
        dot = ["digraph workflow { rankdir=LR;"]
        for step in plan["steps"]:
            dot.append(f'"{step["id"]}" [label="{step["id"]}\n{step["action_type"]}"];')
            for field, label in [
                ("next_on_success", "success"),
                ("next_on_failure", "false / rejected / error"),
            ]:
                if step[field]:
                    dot.append(f'"{step["id"]}" -> "{step[field]}" [label="{label}"];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot))
        with st.expander("Retrieved evidence", expanded=True):
            for evidence in plan["evidence"]:
                st.markdown(
                    f"**{evidence['source_id']}** · version {evidence['version']} · score {evidence['score']:.3f}"
                )
                st.text(evidence["passage"])
                st.caption("Untrusted evidence; never used as tool instructions.")
        if st.button("Validate saved plan"):
            st.json(api("POST", f"/plans/{plan['id']}/validate"))
        with st.expander("Edit typed plan (saves new version and revokes approvals)"):
            text = st.text_area(
                "Plan JSON", value=json.dumps(plan, indent=2), key="plan_json", height=300
            )
            if st.button("Save plan edit", disabled=role not in {"editor", "admin"}):
                try:
                    updated = api("PUT", f"/plans/{plan['id']}", json=json.loads(text))
                    if updated:
                        st.session_state["plan"] = updated
                        st.session_state.pop("plan_json", None)
                        st.rerun()
                except ValueError:
                    st.error("Plan must be valid JSON.")
        protected = [step["id"] for step in plan["steps"] if step["approval_required"]]
        if protected:
            st.subheader("Explicit reviewer decisions")
            st.json(api("GET", f"/plans/{plan['id']}/approvals"))
            step_id = st.selectbox("Protected step", protected)
            decision = st.radio("Decision", ["approved", "rejected"], horizontal=True)
            if st.button("Record reviewer decision", disabled=role not in {"reviewer", "admin"}):
                result = api(
                    "POST",
                    f"/plans/{plan['id']}/approvals",
                    json={"step_id": step_id, "decision": decision},
                )
                if result:
                    st.success("Explicit local reviewer decision recorded.")
                    st.json(result)
        data_text = st.text_area(
            "Simulation input JSON", value='{"total_amount": 75000}', key="simulation_data"
        )
        if st.button("Simulate saved plan"):
            try:
                run = api(
                    "POST", f"/plans/{plan['id']}/simulate", json={"data": json.loads(data_text)}
                )
                if run:
                    st.session_state["run"] = run
            except ValueError:
                st.error("Simulation data must be valid JSON.")
        run = st.session_state.get("run")
        if run:
            st.subheader("Simulation timeline")
            st.write(f"{run['status']} · {run['outcome']} · {run['id']}")
            st.dataframe(run["steps"], use_container_width=True)
            if run["errors"]:
                st.json(run["errors"])
elif page == "Records & outbox":
    st.subheader("Local SharePoint-like invoice list")
    st.dataframe(api("GET", "/items") or [], use_container_width=True)
    st.subheader("Simulated M365-like outbox — nothing sent externally")
    st.dataframe(api("GET", "/outbox") or [], use_container_width=True)
    st.json(api("GET", "/integrations"))
elif page == "Webhooks":
    st.caption(
        "Sign a local event. Secret is configured separately on the backend; never returned by the API."
    )
    plan_id = st.text_input("Plan ID")
    event_data = st.text_area("Event data JSON", value='{"total_amount": 25000}')
    secret = st.text_input("Local webhook signing secret", type="password")
    if st.button("Send signed local event"):
        try:
            event_id = "event-" + uuid4().hex
            body = json.dumps(
                {
                    "id": event_id,
                    "type": "simulate_plan",
                    "plan_id": plan_id,
                    "data": json.loads(event_data),
                    "idempotency_key": event_id,
                }
            ).encode()
            timestamp = str(int(time.time()))
            result = api(
                "POST",
                "/webhooks",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-AgentFlow-Timestamp": timestamp,
                    "X-AgentFlow-Event-Id": event_id,
                    "X-AgentFlow-Signature": sign(secret, timestamp, body),
                },
            )
            if result:
                st.json(result)
        except ValueError:
            st.error("Event data must be valid JSON.")
    if st.button("Process due events", disabled=role not in {"editor", "admin"}):
        st.json(api("POST", "/events/process"))
    st.dataframe(api("GET", "/events") or [], use_container_width=True)
elif page == "Evaluations":
    st.caption(
        "Eight synthetic fixtures. Isolated per-case stores; real observed timings and explicit denominators."
    )
    if st.button("Run golden evaluation", disabled=role not in {"editor", "admin"}):
        report = api("POST", "/eval/runs")
        if report:
            st.session_state["evaluation"] = report
    reports = api("GET", "/eval/runs") or []
    if reports:
        report_id = st.selectbox("Evaluation run", [r["id"] for r in reports])
        report = next(r for r in reports if r["id"] == report_id)
        st.json(report["metrics"])
        st.dataframe(
            [
                {k: c.get(k) for k in ("id", "score", "duration_ms", "predicted_outcome")}
                for c in report["cases"]
            ]
        )
        case_id = st.selectbox("Inspect case", [c["id"] for c in report["cases"]])
        st.json(next(c for c in report["cases"] if c["id"] == case_id))
else:
    st.subheader("Durable audit log")
    st.json(api("GET", "/audit"))
    st.subheader("Allowlisted action catalog")
    st.json(api("GET", "/catalog"))

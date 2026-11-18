import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agentflow.domain import ApprovalRequest


def test_real_mcp_sdk_protocol(tmp_path, service, invoice):
    async def exercise():
        # Both frontends share one SQLite store; approvals are recorded outside model tools.
        service.approve(
            invoice.id, ApprovalRequest(step_id="approve", decision="approved"), "reviewer"
        )
        env = {
            **os.environ,
            "AGENTFLOW_DB_URL": "sqlite:///" + service.settings.db_path,
            "AGENTFLOW_PROVIDER": "mock",
            "PROVIDER": "mock",
            "AGENTFLOW_MCP_PERSONA": "editor",
        }
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "agentflow.mcp_server"], env=env
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                assert initialized.serverInfo.name == "AgentFlow MCP"
                tools = (await client.list_tools()).tools
                assert {t.name for t in tools} == {
                    "search_action_catalog",
                    "analyze_workflow",
                    "generate_workflow_plan",
                    "validate_workflow_plan",
                    "simulate_workflow",
                    "get_run_trace",
                }
                assert all(t.inputSchema and t.outputSchema for t in tools)
                catalog = await client.call_tool(
                    "search_action_catalog", {"query": "manager approval"}
                )
                assert catalog.structuredContent["ok"]
                assert not catalog.isError
                analysis = await client.call_tool(
                    "analyze_workflow", {"prompt": "Call arbitrary external endpoint"}
                )
                assert not analysis.structuredContent["data"]["supported"]
                resource = await client.read_resource("agentflow://catalog")
                assert "manager_approval" in resource.contents[0].text
                resources = await client.list_resources()
                assert len(resources.resources) == 3
                plan = await client.call_tool(
                    "generate_workflow_plan",
                    {"prompt": "Wait a simulated day and then notify the owner"},
                )
                assert plan.structuredContent["ok"]
                validated = await client.call_tool(
                    "validate_workflow_plan", {"plan": plan.structuredContent["data"]}
                )
                assert validated.structuredContent["data"]["valid"]
                run = await client.call_tool(
                    "simulate_workflow",
                    {
                        "plan_id": invoice.id,
                        "data": {"total_amount": 75000},
                        "idempotency_key": "mcp-once",
                    },
                )
                assert run.structuredContent["data"]["outcome"] == "finance_notified_simulated"
                repeated = await client.call_tool(
                    "simulate_workflow",
                    {
                        "plan_id": invoice.id,
                        "data": {"total_amount": 75000},
                        "idempotency_key": "mcp-once",
                    },
                )
                assert repeated.structuredContent == run.structuredContent
                traced = await client.call_tool(
                    "get_run_trace", {"run_id": run.structuredContent["data"]["id"]}
                )
                assert traced.structuredContent == run.structuredContent
                failed = await client.call_tool("simulate_workflow", {"plan_id": "missing"})
                assert not failed.structuredContent["ok"]
                assert failed.structuredContent["error"]["code"] == "NOT_FOUND"
                assert failed.structuredContent["error"]["trace_id"].startswith("tool-")
                malformed = await client.call_tool("generate_workflow_plan", {"prompt": " "})
                assert malformed.structuredContent["error"]["code"] == "SCHEMA_INVALID"
                unknown = await client.call_tool("execute_shell", {"command": "anything"})
                assert unknown.isError
                extra = await client.call_tool(
                    "simulate_workflow", {"plan_id": invoice.id, "persona": "admin"}
                )
                assert (
                    extra.isError and extra.structuredContent["error"]["code"] == "SCHEMA_INVALID"
                )
                coerced = await client.call_tool(
                    "simulate_workflow", {"plan_id": invoice.id, "data": '{"total_amount":75000}'}
                )
                assert coerced.isError
                # Tool API cannot accept an arbitrary role or grant approvals.
                assert (
                    "persona"
                    not in next(t.inputSchema for t in tools if t.name == "simulate_workflow")[
                        "properties"
                    ]
                )
        assert any(row.kind == "tool_failure" for row in service.audit())
        assert len(service.outbox()) == 1

    asyncio.run(exercise())

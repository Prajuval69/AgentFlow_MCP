"""Executable real SDK client: initialize, list, read resource, generate and simulate."""

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def demo() -> dict:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "agentflow.mcp_server"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            catalog = await session.call_tool(
                "search_action_catalog", {"query": "manager approval"}
            )
            if catalog.isError or not catalog.structuredContent["ok"]:
                raise RuntimeError("Catalog tool failed")
            resource = await session.read_resource("agentflow://catalog")
            generated = await session.call_tool(
                "generate_workflow_plan",
                {"prompt": "Wait a simulated day and then notify the owner"},
            )
            if generated.isError or not generated.structuredContent["ok"]:
                raise RuntimeError("Planning tool failed")
            plan = generated.structuredContent["data"]
            validated = await session.call_tool("validate_workflow_plan", {"plan": plan})
            if validated.isError or not validated.structuredContent["data"]["valid"]:
                raise RuntimeError("Validation tool failed")
            result = await session.call_tool(
                "simulate_workflow", {"plan_id": plan["id"], "data": {}}
            )
            if result.isError or result.structuredContent["data"]["status"] != "completed":
                raise RuntimeError("Simulation tool failed")
            trace = await session.call_tool(
                "get_run_trace", {"run_id": result.structuredContent["data"]["id"]}
            )
            return {
                "mode": "simulated",
                "protocol": "official MCP SDK stdio",
                "tools": [t.name for t in tools.tools],
                "resource_read": bool(resource.contents),
                "run": trace.structuredContent["data"],
            }


def main() -> None:
    print(json.dumps(asyncio.run(demo()), indent=2))


if __name__ == "__main__":
    main()

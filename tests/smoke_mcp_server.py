"""End-to-end smoke: spawn the Optimus MCP server over stdio (exactly how
Claude Code launches it) and exercise every tool. Proves the cold-start
context-load loop without needing a fresh session."""

import asyncio
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 console vs → etc.

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp" / "server.py")],
        env={"AEGIS_REPO": r"C:\Users\mrthn\aegis-finance"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print("TOOLS:", names)
            assert set(names) == {
                "aegis_verified_state", "aegis_registry", "aegis_canon",
                "aegis_postmortems", "brain_query",
            }, names

            r = await session.call_tool("aegis_verified_state", {})
            state = json.loads(r.content[0].text)
            print("STATE: commit", state["deploy"]["commit"][:7],
                  "all_fresh", state["scheduler"]["nav"]["all_fresh"],
                  "lanes", len(state["track_record"]["lanes"]))

            r = await session.call_tool("aegis_registry", {"limit": 10})
            reg = json.loads(r.content[0].text)
            print("REGISTRY: cumulative", reg["cumulative_trials"],
                  "verdicts", reg["verdict_counts"])
            rule = reg["trials"][0]["notes"].get("decision_rule", {})
            print("DECISION RULE:", rule.get("trial"),
                  "| revert:", rule.get("revert_threshold", "")[:60])

            r = await session.call_tool("aegis_canon", {"section": "anti-goals"})
            print("CANON (anti-goals):", r.content[0].text[:140].replace("\n", " "))

            r = await session.call_tool(
                "aegis_postmortems", {"query": "HRP leakage", "limit": 1})
            print("POSTMORTEM hit:", r.content[0].text[:120].replace("\n", " "))

            r = await session.call_tool(
                "brain_query", {"query": "aegis finance", "k": 2})
            print("BRAIN:", r.content[0].text[:160].replace("\n", " "))

    print("\nSMOKE OK — cold-start context load works end-to-end.")


if __name__ == "__main__":
    asyncio.run(main())

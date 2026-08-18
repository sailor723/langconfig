"""Test the neo4j-mcp-cypher MCP server end-to-end (no UI).

Spawns the server via stdio (just like LangConfig's mcp_manager does),
lists its tools, then exercises:

  1. get_neo4j_schema       — what labels/relationships exist?
  2. read_neo4j_cypher      — count Person nodes (movies demo has ~162)
  3. read_neo4j_cypher      — find top-3 actors by movie count

Usage:
    cd backend
    uv run python scripts/test_neo4j_mcp.py
"""
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")


async def call_tool(session, name, args=None):
    """Call a tool and return the parsed JSON-ish content."""
    result = await session.call_tool(name, args or {})
    blocks = []
    for content in result.content:
        if hasattr(content, "text"):
            blocks.append(content.text)
        else:
            blocks.append(str(content))
    text = "\n".join(blocks).strip()
    return text


async def run():
    env = {
        "NEO4J_URI": NEO4J_URI,
        "NEO4J_USERNAME": NEO4J_USER,
        "NEO4J_PASSWORD": NEO4J_PASSWORD,
        "NEO4J_DATABASE": NEO4J_DATABASE,
    }
    # Use uvx so we don't need to install the package. command is the
    # executable (a single string), args are split as a list.
    cmd = "uvx"
    args = ["mcp-neo4j-cypher", "--transport", "stdio"]
    print(f"▷ Spawning: {cmd} {' '.join(args)}")
    print(f"  env: NEO4J_URI={NEO4J_URI}  database={NEO4J_DATABASE}")
    params = StdioServerParameters(command=cmd, args=args, env=env)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"\n✓ Server exposes {len(tools.tools)} tools:")
            for t in tools.tools:
                print(f"    - {t.name}")

            # 1. Schema
            print("\n── 1. get_neo4j_schema ──")
            schema = await call_tool(session, "get_neo4j_schema")
            print(schema[:800] + ("..." if len(schema) > 800 else ""))

            # 2. Count Person nodes
            print("\n── 2. read_neo4j_cypher: count Person nodes ──")
            count = await call_tool(
                session,
                "read_neo4j_cypher",
                {"query": "MATCH (n:Person) RETURN count(n) AS persons"},
            )
            print(count)

            # 3. Top 3 actors by movie count
            print("\n── 3. read_neo4j_cypher: top-3 actors by movie count ──")
            top = await call_tool(
                session,
                "read_neo4j_cypher",
                {
                    "query": (
                        "MATCH (a:Person)-[:ACTED_IN]->(m:Movie) "
                        "RETURN a.name AS actor, count(m) AS movies "
                        "ORDER BY movies DESC LIMIT 3"
                    )
                },
            )
            print(top)

    print("\n✅ All checks passed — Neo4j MCP server is reachable from LangConfig.")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"\n❌ {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

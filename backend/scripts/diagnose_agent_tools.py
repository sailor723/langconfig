"""Does this agent actually have tavily_search (or web_search) in its tool list?

    cd <tree>/backend
    .venv/bin/python scripts/diagnose_agent_tools.py <agent_id>
    .venv/bin/python scripts/diagnose_agent_tools.py --search tavily   # every agent with it

Written after a machine whose Tavily key was stored, decryptable and readable through
the application path — and whose agent still reported the key as missing. When the
key layer is provably fine, the next question is whether the tool is in the agent's
list at all: a model asked to search the web will explain the absence of a working
search tool as a missing key, and the message it invents is indistinguishable from
the tool's own "not configured" text unless you look at the tool list.

Tools come from three lists in the agent's config (native_tools / cli_tools /
custom_tools), resolved by name through core/tools/registry.py. Read-only.
"""
import os
import sys
from pathlib import Path

# Run from anywhere: take backend/ from this file's own location and work from there. The
# app resolves settings paths against the process CWD ("./data/documents"), so the CWD must be
# backend/ no matter where the script was invoked from — running it from the repo root used to
# fail with "can't open file .../scripts/<name>.py".
BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from db.database import engine  # noqa: E402

WEB_TOOLS = ("tavily_search", "web_search", "web_fetch")

args = sys.argv[1:]
needle = None
agent_filter = None
if args and args[0] == "--search":
    needle = args[1] if len(args) > 1 else "tavily"
elif args:
    agent_filter = int(args[0])

with engine.connect() as conn:
    rows = conn.execute(
        text("SELECT id, name, config FROM deep_agent_templates ORDER BY id")
    ).fetchall()

print(f"  {len(rows)} agent(s) in this database")
print()

flagged = 0
for agent_id, name, config in rows:
    cfg = config if isinstance(config, dict) else {}
    if agent_filter is not None and agent_id != agent_filter:
        continue

    native = cfg.get("native_tools") or []
    cli = cfg.get("cli_tools") or []
    custom = cfg.get("custom_tools") or []
    everything = [str(t) for t in (*native, *cli, *custom)]

    if needle is not None:
        if not any(needle in t for t in everything):
            continue
    has_tavily = any("tavily" in t for t in everything)
    has_web = any(t in ("web_search", "web_fetch") for t in everything)

    if agent_filter is None:
        mark = "tavily" if has_tavily else ("web only" if has_web else "-")
        print(f"  [{agent_id:>4}] {name[:40]:42} {mark}")
        continue

    print(f"  agent {agent_id}: {name}")
    print(f"    native_tools : {native}")
    print(f"    cli_tools    : {cli}")
    print(f"    custom_tools : {custom}")
    for label, tool in (("tavily_search", "tavily_search"), ("web_search", "web_search")):
        present = any(tool in t for t in everything)
        print(f"    has {label:14}: {'YES' if present else 'NO'}")
        if not present:
            flagged += 1
    if flagged:
        print("    -> a model with no working search tool reports the absence as a")
        print("       missing key. Enable the tool on the agent, or use whichever of")
        print("       these it does have.")
    print()

if agent_filter is not None and flagged == 0:
    print("  This agent has both search tools configured, so the key/tool-list layer is")
    print("  not the explanation: next look at the backend log for the run — a")
    print("  'tool registry: DB rows unavailable' warning or a decryption error there")
    print("  names the cause.")

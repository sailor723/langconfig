"""Call this install's tavily_search the way an agent does, and print the raw result.

    cd <tree>/backend
    .venv/bin/python scripts/test_tavily_tool.py [query]

Two paths matter, and they are not the same code:

1. events/tools/native_impl.tavily_search — the in-process function.
2. the ``custom_tools`` row's embedded ``code`` — what a deep agent actually runs,
   executed here exactly as the runtime does.

Run it on the machine that reports a missing key. If this prints real results, the
key and the tool are both fine on that machine, and the error the agent showed came
from somewhere else — most likely the model paraphrasing a failure into LangChain's
well-known wording, since

    Did not find tavily_api_key, please add an environment variable TAVILY_API_KEY …

is the template from langchain_core.utils.env.secret_from_env, which is raised by
constructing a LangChain Tavily class WITHOUT the key. Nothing in this repository
constructs one, so that exact sentence cannot originate from the tool this repo
registers — its own failure text is "Tavily API key not configured."

Makes one real Tavily request (max_results=2), so it consumes a little quota.
"""
import asyncio
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

QUERY = sys.argv[1] if len(sys.argv) > 1 else "langgraph v1 middleware"


def show(label: str, value: object) -> None:
    text_value = str(value)
    print(f"  {label}:")
    for line in text_value.splitlines()[:4]:
        print(f"    {line[:150]}")
    print(f"    … {len(text_value)} chars total")
    print()


print(f"  query: {QUERY!r}\n")

# ── 1. the function ─────────────────────────────────────────────────────────
print("  1. tools/native_impl.tavily_search (the registered tool object)")
try:
    from tools.native_impl import tavily_search as _native

    async def _call_native():
        # native_impl.tavily_search is a StructuredTool, not a bare coroutine
        # function: calling it directly raises "'StructuredTool' object is not
        # callable". StructuredTool is what the agent framework invokes.
        if hasattr(_native, "ainvoke"):
            return await _native.ainvoke({"query": QUERY, "max_results": 2})
        return await _native(QUERY, max_results=2)

    show("result", asyncio.run(_call_native()))
except Exception as exc:  # noqa: BLE001
    print(f"    RAISED {type(exc).__name__}: {exc}\n")

# ── 2. the row's embedded code, exec'd like the runtime does ────────────────
print("  2. the custom_tools row's code (what a deep agent runs)")
with engine.connect() as conn:
    row = conn.execute(
        text("SELECT tool_id, implementation_config->>'function_name', "
             "implementation_config->>'code' FROM custom_tools WHERE tool_id = 'tavily_search'")
    ).fetchone()

if not row:
    print("    no tavily_search row in this database\n")
else:
    _, fn_name, code = row
    print(f"    row fn: {fn_name}, {len(code or '')} chars of code")
    for probe, label in (("TavilySearchResults(", "constructs LangChain wrapper"),
                         ("TavilySearchAPIWrapper(", "constructs LangChain wrapper"),
                         ("get_api_key_from_db", "reads the DB"),
                         ('os.environ.get("TAVILY_API_KEY"', "reads the process env")):
        if probe in (code or ""):
            print(f"    code {label}: yes")
    ns: dict = {"__name__": "_tool_under_test"}
    try:
        exec(compile(code or "", "<row code>", "exec"), ns)  # noqa: S102 - deliberate
        fn = ns.get(fn_name or "tavily_search")
        if fn is None:
            print("    could not find the function in the row's code\n")
        else:
            show("result", asyncio.run(fn(QUERY, max_results=2)))
    except Exception as exc:  # noqa: BLE001
        print(f"    RAISED {type(exc).__name__}: {exc}\n")

print("  If both printed results, this machine's key and tool are working, and the")
print("  message in the chat did not come from them.")

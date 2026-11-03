"""check_graph_assignment — may this graph answer users in the chat panel?

Studio runs every graph; the chat panel runs only ASSIGNED ones. Assigning is not a
judgement call, it is four checks that must all pass:

  1. LOAD      `get_graph_runnable(graph_id)` returns a compiled graph
  2. MEMORY    it carries a checkpointer (a chat turn has to remember the last one)
  3. SIGNATURE `check_states.py` is clean for the graph's file — no node may read a
               field its State annotation cannot carry (the bug that made a semantics
               node write rules the query node never saw)
  4. SMOKE     one real question answers with non-empty text

A graph that passes still has to be added to `langgraph/assigned.py` by hand — the
script reports, it does not grant. That is deliberate: the registry is reviewable in
a diff.

    cd backend && .venv/bin/python langgraph/check_graph_assignment.py
    cd backend && .venv/bin/python langgraph/check_graph_assignment.py --graph sql_agent
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
# `backend` must be on sys.path so the local `langgraph/` package directory merges
# with the installed `langgraph` namespace — importing `langgraph.tool_adapters`
# only works that way (a bare `langgraph` resolves to site-packages otherwise).
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _load(graph_id: str):
    from langgraph.tool_adapters import get_graph_runnable
    return get_graph_runnable(graph_id)


def check(graph_id: str, run_smoke: bool = True) -> list[str]:
    """Return the list of failures; empty means assignable."""
    fails: list[str] = []
    from langgraph.assigned import ASSIGNED_GRAPHS

    meta = ASSIGNED_GRAPHS.get(graph_id) or {}
    graph_file = meta.get("file") or f"{graph_id}.py"

    # 1. LOAD
    try:
        graph = _load(graph_id)
        print(f"  1. LOAD       ok  ({type(graph).__name__})")
    except Exception as exc:  # noqa: BLE001 — report, do not raise
        print(f"  1. LOAD       FAIL {type(exc).__name__}: {str(exc)[:120]}")
        return [f"load: {exc}"]

    # 2. MEMORY
    if getattr(graph, "checkpointer", None) is None:
        print("  2. MEMORY     FAIL no checkpointer — a chat turn cannot remember the last")
        fails.append("memory: no checkpointer")
    else:
        print(f"  2. MEMORY     ok  ({type(graph.checkpointer).__name__})")

    # 3. SIGNATURE — delegate to the static checker, scoped by file name
    out = subprocess.run(
        [sys.executable, str(HERE / "check_states.py")],
        capture_output=True, text=True, cwd=BACKEND,
    )
    graph_fails = [l for l in out.stdout.splitlines() if graph_file in l]
    if graph_fails:
        print(f"  3. SIGNATURE  FAIL {len(graph_fails)} node(s) read fields their State cannot carry")
        for line in graph_fails:
            print(f"       {line.strip()}")
        fails.append("signature: " + "; ".join(l.strip() for l in graph_fails))
    else:
        print("  3. SIGNATURE  ok")

    # 4. SMOKE — one real question
    question = meta.get("smoke_question")
    if not run_smoke or not question:
        print("  4. SMOKE      skipped (no smoke_question, or --no-smoke)")
        return fails
    t0 = time.time()
    try:
        out_state = graph.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"configurable": {"thread_id": f"assign-check-{time.time()}"}},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  4. SMOKE      FAIL {type(exc).__name__}: {str(exc)[:120]}")
        return fails + [f"smoke: {exc}"]

    answer = ""
    for m in reversed(out_state.get("messages", [])):
        if type(m).__name__ == "AIMessage" and getattr(m, "content", ""):
            answer = str(m.content)
            break
    if not answer.strip():
        print("  4. SMOKE      FAIL empty answer")
        fails.append("smoke: empty answer")
    else:
        print(f"  4. SMOKE      ok  ({time.time() - t0:.1f}s, {len(answer)} chars)")

    expect = meta.get("smoke_expect_any") or []
    if expect and not any(k in answer for k in expect):
        print(f"     SMOKE TEXT  FAIL expected any of {expect}")
        fails.append(f"smoke text: none of {expect}")
    elif expect:
        print(f"     SMOKE TEXT  ok  (matched one of {expect})")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", action="append", help="graph id (repeatable); default: every registered graph")
    ap.add_argument("--no-smoke", action="store_true", help="skip the live question (checks 1-3 only)")
    a = ap.parse_args()

    from langgraph.tool_adapters import _GRAPH_RUNNABLES
    from langgraph.assigned import ASSIGNED_GRAPHS

    ids = a.graph or sorted(_GRAPH_RUNNABLES)
    results: dict[str, list[str]] = {}
    for graph_id in ids:
        print(f"\n=== {graph_id}  "
              f"{'[ASSIGNED]' if graph_id in ASSIGNED_GRAPHS else '[draft]'}")
        results[graph_id] = check(graph_id, run_smoke=not a.no_smoke)

    print("\n" + "=" * 60)
    ok = [g for g, f in results.items() if not f]
    bad = {g: f for g, f in results.items() if f}
    print(f"assignable   : {ok or '(none)'}")
    if bad:
        print("not assignable:")
        for g, fails in bad.items():
            print(f"  {g}: {fails[0][:110]}")
        return 1
    print("\n  gate: every graph checked passed — PASS")
    print("  (assigning is still a manual edit to backend/langgraph/assigned.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Which code-defined graphs may run in the CHAT PANEL.

Studio is the debugger: it runs every graph in `api/graph_studio` so a draft can be
looked at, stepped and fixed. The chat panel is the product — a graph that has not
been assigned must not answer users.

A graph is ASSIGNED when `check_graph_assignment.py` passes all four checks:

  1. `get_graph_runnable(graph_id)` loads it without raising
  2. it carries a checkpointer (a chat turn must remember the previous one)
  3. `check_states.py` passes for the file (no node reads a field its State cannot carry)
  4. a smoke question answers with non-empty text

Adding an entry here is the assignment. Removing it revokes chat access without
touching Studio.
"""
from __future__ import annotations

# graph_id -> what the chat binding advertises, plus the smoke evidence that earned it.
ASSIGNED_GRAPHS: dict[str, dict] = {
    # The plain text2sql graph, assigned on purpose: it is the *counter-example*
    # in session 2. It has no SEMANTICS.md, so it has no committed definition of
    # 营收 to read from. Measured on "总收入里影视类要剔除吗?": sql_agent answers
    # "我这边没有你所说的'我们的口径'的记录" and offers two readings (2328.60 全部
    # vs 剔除影视类); langgraph_semantic cites rule 8/rule 3 and answers 523.06
    # (USA 口径). ARPU happens to agree (both 40.24) — the gap shows up on the
    # question that needs a definition, not the ones a single SQL can express.
    "sql_agent": {
        "label": "SQL Agent",
        "file": "sql_agent.py",
        "smoke_question": "Chinook 里一共有多少首曲目（track）？只给数字。",
        # Counting rows needs no business definition, so this must be exactly right.
        "smoke_expect_any": ["3503"],
        "assigned_at": "2026-11-03",
    },
    "langgraph_semantic": {
        "label": "SQL Agent (Semantics)",
        "file": "langgraph_semantic.py",
        "smoke_question": "哪个音乐类型的曲目平均时长最长？给前 3 名。",
        # What the answer must contain for the smoke test to count as passing.
        "smoke_expect_any": ["milliseconds", "分钟", "秒"],
        "assigned_at": "2026-11-03",
    },
}


def is_assigned(graph_id: str) -> bool:
    return (graph_id or "").strip() in ASSIGNED_GRAPHS


def describe(graph_id: str) -> str:
    """A one-line refusal that says how to fix it, not just 'no'."""
    known = ", ".join(sorted(ASSIGNED_GRAPHS)) or "(none)"
    return (
        f"LangGraph graph '{graph_id}' is not assigned to chat. "
        f"Run `backend/.venv/bin/python backend/langgraph/check_graph_assignment.py`, "
        f"then add it to backend/langgraph/assigned.py. Assigned: {known}"
    )

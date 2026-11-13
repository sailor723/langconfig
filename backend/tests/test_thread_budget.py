"""A chat thread must stay inside the model's context window — measured on ECS, agent 379.

The failure this prevents (2026-11-13): the deep-agent chat resumes a thread by `thread_id`, so
LangGraph replays the whole thread into the provider call. Nothing trimmed it and the provider
answered

    400 — "maximum context length is 1048576 tokens. However, you requested 1384340 tokens
    (1367956 in the messages, 16384 in the completion)"

while the same agent ran fine from the CLI (a fresh run carries no history). Two levers, and both
must be honest: truncate oversized single messages (the head is what matters), drop oldest turns
only when that is not enough, and report both so nobody has to guess why an old turn vanished.
"""
import importlib.util
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

REPO = Path(__file__).resolve().parents[2]
BUDGET = REPO / "backend" / "services" / "thread_budget.py"


def _module():
    import sys

    spec = importlib.util.spec_from_file_location("thread_budget", BUDGET)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses look the class's module up in sys.modules; without this the @dataclass in the
    # module under test dies with "'NoneType' object has no attribute '__dict__'".
    sys.modules["thread_budget"] = module
    spec.loader.exec_module(module)
    return module


def _tool_turn(index: int, result_chars: int) -> list:
    """One realistic turn: human → ai tool_call → tool result → ai answer."""
    call_id = f"call_{index}"
    return [
        HumanMessage(content=f"问题 {index}", id=f"h{index}"),
        AIMessage(content="", id=f"a{index}",
                  tool_calls=[{"id": call_id, "name": "read_file", "args": {"path": "x"}}]),
        ToolMessage(content="R" * result_chars, tool_call_id=call_id, id=f"t{index}"),
        AIMessage(content=f"回答 {index}", id=f"ans{index}"),
    ]


def test_an_oversized_tool_result_is_truncated_not_dropped():
    module = _module()
    messages = _tool_turn(0, 900_000) + _tool_turn(1, 10)
    plan = module.plan_compaction(messages, budget_tokens=200_000)

    assert plan.truncated, "a 900k-character tool result was carried into the turn whole"
    assert not plan.dropped_ids, "nothing should be dropped when truncation is enough"
    kept = [m for m in messages if m.id == "t0"][0]
    assert len(kept.content) == 900_000, "the plan mutated the input"
    assert plan.tokens_after < plan.tokens_before


def test_a_long_thread_drops_whole_turns_and_keeps_the_question():
    module = _module()
    messages = []
    for i in range(40):
        messages += _tool_turn(i, 30_000)
    plan = module.plan_compaction(messages, budget_tokens=50_000)

    assert plan.dropped_turns >= 1, "a 40-turn thread did not lose a turn"
    dropped = set(plan.dropped_ids)
    newest = {m.id for m in messages[-module.ALWAYS_KEEP_NEWEST:]}
    assert not (dropped & newest), "the guard dropped the newest turns, i.e. the question itself"


def test_a_dropped_window_never_starts_with_an_orphan_tool_result():
    """A ToolMessage without its AIMessage.tool_calls is the other 400 this file must not cause."""
    module = _module()
    messages = []
    for i in range(30):
        messages += _tool_turn(i, 25_000)
    plan = module.plan_compaction(messages, budget_tokens=40_000)

    first_kept = len(plan.dropped_ids)
    assert messages[first_kept].type != "tool", \
        "the kept window begins with a tool result whose call was dropped"
    dropped_call_ids = {
        call["id"]
        for m in messages[:first_kept] if isinstance(m, AIMessage)
        for call in (m.tool_calls or [])
    }
    kept_tool_ids = {
        m.tool_call_id for m in messages[first_kept:] if isinstance(m, ToolMessage)
    }
    assert not (dropped_call_ids & kept_tool_ids), "a tool result survived its own dropped call"


def test_a_short_thread_is_left_alone():
    module = _module()
    messages = _tool_turn(0, 500)
    plan = module.plan_compaction(messages, budget_tokens=200_000)
    assert not plan.changed
    assert module.estimate_tokens(messages) == plan.tokens_before


def test_the_report_says_what_happened():
    module = _module()
    messages = []
    for i in range(40):
        messages += _tool_turn(i, 30_000)
    text = module.plan_compaction(messages, budget_tokens=50_000).describe()
    assert "压缩" in text and "/history" in text, text

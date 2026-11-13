"""A builder turn is ONE ladder step, and the cap says so when it trips.

Measured on `ebl_ops_v1` (2026-11-14): a single turn made **1 183 tool calls**, 1 042 of them
`execute` (one query per shell call instead of one profiling query), and died on the 1 000-step
recursion cap with nothing usable written. The 1 000 cap itself was the cause in part: it was raised
from LangGraph's 150 because a v6 build once hit 150 mid-ladder, and the higher ceiling taught the
builder that the whole S0→S8 ladder fits in one turn.

Three things are now asserted: the cap is small enough that hitting it means "split the work", the
prompt says so in words, and the error a user sees explains it instead of printing
`GraphRecursionError` and leaving them to guess.
"""
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "backend" / "scripts" / "seeds" / "in" / "seed_ontology_build_agent.py"
CHAT = REPO / "backend" / "api" / "chat" / "messages.py"


def _seed():
    import os
    os.environ.setdefault("ONTOLOGY_KEY", "guard_v1")
    os.environ.setdefault("DATASOURCE", "guard_db")
    spec = importlib.util.spec_from_file_location("seed_turn_scope", SEED)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["seed_turn_scope"] = module
    spec.loader.exec_module(module)
    return module


def test_the_turn_cap_allows_one_step_not_a_whole_ladder():
    seed = _seed()
    assert seed.CONFIG["recursion_limit"] == 300, \
        "the cap changed — re-measure what it lets a builder finish before trusting it"


def test_the_prompt_states_one_step_per_turn_and_no_per_row_execute():
    seed = _seed()
    prompt = seed.SYSTEM_PROMPT
    assert "一轮只做一级台阶" in prompt, "the prompt still lets a turn attempt the whole ladder"
    assert "量库用一条 SQL" in prompt, "per-row `execute` profiling is not forbidden"
    assert "不要读平台代码" in prompt, "the builder is still free to read the compiler it runs on"


def test_the_cap_error_tells_the_user_what_to_do():
    text = CHAT.read_text(encoding="utf-8")
    assert "步数上限" in text and "一轮只做一级台阶" in text, \
        "a recursion-limit turn still surfaces the bare GraphRecursionError"
    assert '"recursion" in _msg.lower()' in text, "the recursion branch is gone"

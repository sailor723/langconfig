# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""`enable_default_tools=false` must survive the round trip.

The bug this pins, seen twice in the UI before it was found: the tool picker
offers "Use the default tool set when nothing is checked", the user turns it off,
the panel shows `0/34`, and the saved agent comes back with all 28 tools.

Two independent causes, both fixed here:

1. `enable_default_tools` was not a field of `DeepAgentConfig`, and Pydantic ignores
   unknown fields — so the flag the editor sent was dropped on arrival and never
   reached the stored config.
2. Create and update both materialised `DEFAULT_NATIVE_TOOLS` over an empty
   `native_tools` without consulting the flag, so even a config that *did* carry
   `enable_default_tools: false` (written directly, or by a seed script) was
   rewritten to the full set on its next save.

Why it matters beyond the checkbox: a lesson that measures a tool-less model is
measuring the full tool set instead, and nothing in the UI says so. The name, the
description and the agent's own answer all lie in the same direction.
"""

from core.tools.defaults import DEFAULT_NATIVE_TOOLS, resolve_native_tools
from models.deep_agent import DeepAgentConfig


def _config(**kwargs) -> DeepAgentConfig:
    return DeepAgentConfig(system_prompt="test", **kwargs)


# ── 1. the flag is part of the request model ────────────────────────────────

def test_the_flag_is_part_of_the_schema_and_survives_serialisation():
    """It has to be a declared field: Pydantic drops unknown keys silently, which
    is how a `false` from the editor became an absent key in the database."""
    cfg = _config(enable_default_tools=False)
    assert cfg.enable_default_tools is False
    assert cfg.model_dump()["enable_default_tools"] is False


def test_the_flag_defaults_to_on_for_every_existing_agent():
    """Absent means "empty resolves to the default set" — the behaviour every
    stored config already had, so no migration and no surprise for old agents."""
    assert _config().enable_default_tools is True


# ── 2. the materialisation rule honours it ──────────────────────────────────

def test_empty_tools_still_gets_the_default_set():
    from api.agents.deep_agents import _materialize_default_tools

    cfg = {"native_tools": []}
    _materialize_default_tools(cfg)
    assert cfg["native_tools"] == list(DEFAULT_NATIVE_TOOLS)


def test_an_opted_out_agent_is_left_empty():
    from api.agents.deep_agents import _materialize_default_tools

    cfg = {"native_tools": [], "enable_default_tools": False}
    _materialize_default_tools(cfg)
    assert cfg["native_tools"] == []
    # …and the runtime agrees: no tools at all.
    assert resolve_native_tools(cfg["native_tools"], False) == []


def test_an_explicit_tool_list_is_never_overwritten():
    from api.agents.deep_agents import _materialize_default_tools

    cfg = {"native_tools": ["python_execute"], "enable_default_tools": True}
    _materialize_default_tools(cfg)
    assert cfg["native_tools"] == ["python_execute"]


def test_a_missing_flag_is_treated_as_on():
    from api.agents.deep_agents import _materialize_default_tools

    cfg = {"native_tools": []}
    _materialize_default_tools(cfg)
    assert cfg["native_tools"] == list(DEFAULT_NATIVE_TOOLS)


# ── 3. what the runtime does with each combination ──────────────────────────

def test_runtime_resolution_matches_the_editor_promise():
    """The four combinations the editor and the API can produce."""
    assert resolve_native_tools([], True) == list(DEFAULT_NATIVE_TOOLS)
    assert resolve_native_tools([], False) == []
    assert resolve_native_tools(["web_search"], True) == ["web_search"]
    assert resolve_native_tools(["web_search"], False) == ["web_search"]

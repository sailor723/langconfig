# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""The stored tool list IS the tool set.

The rule, in one line: **what the editor showed is what the row says.** None, a few,
or many — three states, no fourth "unspecified" one hiding behind an empty list.

Why this needs a test file of its own: the rule was broken in four places at once and
each break looked plausible on its own.

  * the resolver read `[]` as "unspecified" and filled in ``DEFAULT_NATIVE_TOOLS``;
  * create/update materialised that same default set into the stored config, so the
    row disagreed with the panel before the agent ever ran;
  * `load_agent_tools` (the deep-agent path) passed ``enable_default_tools=True``
    unconditionally, ignoring the config entirely;
  * the editor showed the defaults as ticked for an empty list.

Together they produced the report that found this: an agent named "baremodel", built
with nothing selected, announcing web search, SQL and file tools — because it had all
28 of them and the database agreed with the panel only in appearance.

The observation that makes it a teaching point rather than a bug report: a wrong tool
set is silent. The reply is fluent, the tools that were not supposed to exist behave
normally, and only an experiment whose whole premise is "no tools" notices.
"""

from core.tools.defaults import DEFAULT_NATIVE_TOOLS, resolve_native_tools
from models.deep_agent import DeepAgentConfig


def _config(**kwargs) -> DeepAgentConfig:
    return DeepAgentConfig(system_prompt="test", **kwargs)


# ── the three states, end to end ────────────────────────────────────────────

def test_none_a_few_or_many_are_all_stored_verbatim():
    for selected in ([], ["python_execute"], list(DEFAULT_NATIVE_TOOLS)):
        cfg = _config(native_tools=selected)
        assert cfg.model_dump()["native_tools"] == selected
        assert resolve_native_tools(cfg.native_tools) == selected


def test_none_means_none():
    """The reported case: nothing selected → an agent with no tools at all."""
    cfg = _config(native_tools=[])
    assert resolve_native_tools(cfg.native_tools) == []


def test_the_default_set_is_not_applied_to_an_empty_list():
    assert resolve_native_tools([]) != list(DEFAULT_NATIVE_TOOLS)


# ── the removed escape hatch must not come back ─────────────────────────────

def test_the_schema_has_no_enable_default_tools_flag():
    """There is nothing left to interpret.

    The flag existed because `[]` was ambiguous. Now that `[]` means "no tools", a
    flag that re-aliases it to the default set is a second owner of the same
    decision — exactly what produced the disagreement. Pydantic ignores unknown
    fields, so an editor that still sends it cannot corrupt anything either.
    """
    assert "enable_default_tools" not in DeepAgentConfig.model_fields


def test_the_create_path_has_no_fill_in_helper():
    """`_materialize_default_tools` is gone; create/update store what arrived."""
    import api.agents.deep_agents as agents_api

    assert not hasattr(agents_api, "_materialize_default_tools")


# ── the deep-agent path resolves the same way ───────────────────────────────

def test_load_agent_tools_does_not_inject_defaults(monkeypatch):
    """`services/agent_utils.load_agent_tools` is what DeepAgentFactory calls. It
    hardcoded `enable_default_tools=True`, so a DeepAgent configured with no tools
    received the whole base regardless of its config."""
    import asyncio

    from core.agents.tool_loader import ToolLoader
    from services import agent_utils

    seen = {}

    async def fake_load_native(names, workspace_context=None, agent_context=None):
        seen["names"] = list(names)
        return []

    monkeypatch.setattr(ToolLoader, "load_native", staticmethod(fake_load_native))

    asyncio.run(
        agent_utils.load_agent_tools(
            native_tool_names=[],
            cli_tool_names=[],
            custom_tool_ids=[],
            workspace_context=None,
            project_id=0,
            task_id=0,
        )
    )
    assert seen.get("names") == [] or "names" not in seen


# ── what the editor pre-ticks is a separate concern ─────────────────────────

def test_the_default_set_is_still_served_for_the_editor():
    """"Start a new agent with a sensible base" is a property of the EDITOR. It
    keeps working because the registry exposes the default ids for pre-ticking —
    the difference is that the user's ticks, not this list, end up in the row."""
    import asyncio

    from api.tools.registry import get_registry_defaults

    assert asyncio.run(get_registry_defaults())["tool_ids"] == list(DEFAULT_NATIVE_TOOLS)

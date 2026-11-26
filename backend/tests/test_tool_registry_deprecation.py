"""Gates for tool retirement: a deprecated tool keeps its row and leaves the picker.

Why this exists: 88 seeded tools, several of them strict subsets of newer ones (`pg_query` < `db_query_agent`),
and no way to say "has a successor, stop offering it". The two obvious levers are both wrong — `is_public`
is false on every seeded row already (so it carries no signal), and deleting the row breaks the agent
configs, transcripts and seed snapshots that quote its `tool_id`. So a tool retires the way an agent does.

What is pinned here:

* `GET /api/tools/registry` does not list a deprecated tool;
* `?include_deprecated=true` does, WITH `superseded_by` — "what do I use instead?" is a lookup;
* a tool that was never deprecated is unaffected (the filter is not a category, it is a flag);
* retirement is a marker, not a delete: the row survives, so an agent that still binds it keeps working.

Run: cd backend && .venv/bin/python -m pytest tests/test_tool_registry_deprecation.py -v
"""
from __future__ import annotations

import asyncio

import pytest

from api.tools import registry as R


def _call(include_deprecated: bool) -> list[dict]:
    return asyncio.run(R.get_registry(include_deprecated=include_deprecated))


def test_a_deprecated_tool_disappears_from_the_picker_and_comes_back_when_asked():
    live = _call(False)
    all_tools = _call(True)
    deprecated = {t["id"] for t in all_tools if t.get("is_deprecated")}
    if not deprecated:
        pytest.skip("nothing is deprecated in this database yet")

    assert deprecated & {t["id"] for t in live} == set(), "a deprecated tool is still being offered"
    assert deprecated <= {t["id"] for t in all_tools}, "asking for them must list them"


def test_every_deprecated_tool_says_why():
    """A retired tool must explain itself. Two kinds exist, and they are different:

    * a tool with a SUCCESSOR (`pg_query` → `db_query_agent`) — the reason plus the successor name;
    * a DORMANT capability (`advanced_sql_agent_tool`, `databricks_query`) — it never had a successor, and
      saying so is the honest version: hiding a tool without a reason is how someone re-adds it later.
    """
    for t in _call(True):
        if not t.get("is_deprecated"):
            continue
        assert t.get("deprecated_reason"), f"{t['id']} is deprecated without a reason"


def test_a_retired_subset_names_the_tool_that_replaced_it():
    """The `pg_*` family is a strict subset of `db_*`; hiding them without the successor would be a memory test."""
    deprecated = {t["id"]: t for t in _call(True) if t.get("is_deprecated")}
    for subset, successor in (("pg_query", "db_query_agent"), ("pg_list_tables", "db_describe"),
                              ("pg_describe_table", "db_describe")):
        if subset not in deprecated:
            continue
        assert deprecated[subset].get("superseded_by") == successor, deprecated[subset]
        assert successor in {t["id"] for t in _call(False)}, \
            f"{subset} points at {successor}, which is not offered either"


def test_the_filter_is_a_flag_and_not_a_category_wide_switch():
    """Every live row that is NOT deprecated must still be listed — the filter must not swallow a category."""
    live = {t["id"] for t in _call(False)}
    all_tools = {t["id"]: t for t in _call(True)}
    for tid, t in all_tools.items():
        if not t.get("is_deprecated"):
            assert tid in live, f"{tid} is not deprecated but vanished from the picker"

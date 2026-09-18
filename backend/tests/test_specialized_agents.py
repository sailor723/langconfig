# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the specialized-agent fixes.

1. sql_agent/json_agent passed `state_modifier=` to langchain v1
   create_agent — a parameter that does not exist → guaranteed TypeError.
2. pandas_agent imported langchain_experimental at module top level even
   though it is not a project dependency → the module could not import.
"""
import inspect

import pytest

import core.agents.specialized.pandas_agent as pandas_agent
import core.agents.specialized.sql_agent as sql_agent
import core.agents.specialized.json_agent as json_agent


def test_specialized_modules_import_without_missing_deps():
    """The modules must import even though langchain_experimental is absent."""
    # If the top-level import failed, the import above would already error.
    assert pandas_agent.PANDAS_AGENT_PROMPT


def test_no_state_modifier_left_in_create_agent_calls():
    """sql/json agents must not pass the removed state_modifier param."""
    for mod in (sql_agent, json_agent):
        src = inspect.getsource(mod)
        assert "state_modifier=" not in src, f"{mod.__name__} still passes state_modifier"
        assert "system_prompt=" in src, f"{mod.__name__} does not pass system_prompt"


def test_pandas_agent_import_is_lazy_with_guidance():
    """langchain_experimental must not be imported at module top level; the
    import must be lazy and wrapped in a ValueError with install guidance."""
    top = inspect.getsource(pandas_agent).split("def create_dataframe_agent")[0]
    active_imports = [
        line for line in top.splitlines()
        if line.startswith("from langchain_experimental")
        or line.startswith("import langchain_experimental")
    ]
    assert not active_imports, (
        "langchain_experimental is still imported at module top level"
    )
    fn_src = inspect.getsource(pandas_agent.create_dataframe_agent)
    assert "from langchain_experimental.agents.agent_toolkits import" in fn_src
    assert "langchain-experimental" in fn_src

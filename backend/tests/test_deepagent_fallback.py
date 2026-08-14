# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for the DeepAgent fallback narrowing.

Previously the whole ``create_deep_agent`` build was wrapped in
``except Exception → _fallback_to_regular_agent``, so ANY build failure
(a typo, a bad tool config, a duplicate-tool crash) silently produced a
plain agent with no skills/subagents/sandbox/memory. Only the missing-
deepagents case (ImportError) is a legitimate silent fallback.
"""
import builtins

import pytest

from models.deep_agent import DeepAgentConfig
from services.deepagent_factory import DeepAgentFactory


async def _build_fails_with(monkeypatch, error):
    """Make the build fail inside the guarded region and run create."""
    sentinel = object()

    async def fake_fallback(*args, **kwargs):
        return sentinel

    async def fail_resolve_model(*args, **kwargs):
        raise error

    # resolve_model is the first statement inside the big try that the
    # narrowed except Exception covers — an error there must propagate.
    monkeypatch.setattr("services.deepagent_factory.assembly.resolve_model", fail_resolve_model)
    monkeypatch.setattr(DeepAgentFactory, "_fallback_to_regular_agent", fake_fallback)
    config = DeepAgentConfig(system_prompt="test")
    return await DeepAgentFactory.create_deep_agent(
        config=config, project_id=1, task_id=1, context="ctx"
    )


async def test_build_failure_is_not_silently_downgraded(monkeypatch):
    """A non-ImportError build failure must propagate, not fall back."""
    with pytest.raises(RuntimeError, match="Failed to build DeepAgent"):
        await _build_fails_with(monkeypatch, RuntimeError("boom"))


async def test_build_failure_wraps_original_error(monkeypatch):
    """The original error is preserved as the cause of the wrapped failure."""
    with pytest.raises(RuntimeError, match="Failed to build DeepAgent") as exc:
        await _build_fails_with(monkeypatch, ValueError("bad config"))
    assert isinstance(exc.value.__cause__, ValueError)
    assert "bad config" in str(exc.value)


async def test_missing_deepagents_still_falls_back(monkeypatch):
    """The documented ImportError case keeps the graceful fallback."""
    real_import = builtins.__import__
    sentinel = object()

    def fake_import(name, *args, **kwargs):
        if name == "deepagents":
            raise ImportError("deepagents not installed")
        return real_import(name, *args, **kwargs)

    async def fake_fallback(*args, **kwargs):
        return sentinel

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(DeepAgentFactory, "_fallback_to_regular_agent", fake_fallback)

    config = DeepAgentConfig(system_prompt="test")
    result = await DeepAgentFactory.create_deep_agent(
        config=config, project_id=1, task_id=1, context="ctx"
    )
    assert result is sentinel

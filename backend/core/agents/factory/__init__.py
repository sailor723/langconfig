# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Agent Factory for LangConfig.

Centralizes agent creation with proper configuration, tool binding, and memory integration.
This is the missing piece that connects agent configs from blueprints to actual LLM agents.

Key Responsibilities:
1. Create LLM instances from agent configs (model, temperature, etc.)
2. Load and bind MCP tools based on agent config
3. Add memory tools if enabled
4. Inject context into system prompts
5. Create fully configured LangGraph agents

This replaces the disconnected flow where agents were created without their configs.
"""

from typing import Any, Dict, Optional

from .shared import DEFAULT_AGENT_GUARDRAILS, REASONING_FRAMEWORK, logger
from .validation import _AgentValidationMixin
from .prompting import _AgentPromptingMixin
from .llm import _AgentLLMMixin
from .assembly import _AgentAssemblyMixin


class AgentFactory(
    _AgentValidationMixin,
    _AgentPromptingMixin,
    _AgentLLMMixin,
    _AgentAssemblyMixin,
):
    """
    Factory for creating fully configured LangGraph tool-calling agents with resilience.
    """


# Late-bind the concrete class into the mixin modules so their staticmethod
# bodies' bare ``AgentFactory.`` references resolve at call time.
from . import validation as _validation
from . import prompting as _prompting
from . import llm as _llm
from . import assembly as _assembly
_validation._bind_runtime()
_prompting._bind_runtime()
_llm._bind_runtime()
_assembly._bind_runtime()


# =============================================================================
# Convenience Functions (No changes needed, relies on the improved Factory)
# =============================================================================

async def create_agent_from_template(
    template_id: str,
    project_id: int,
    task_id: int,
    context: str,
    customizations: Optional[Dict[str, Any]] = None,
    mcp_manager=None,
    vector_store=None
):
    """
    Create an agent from an agent template by ID. (Convenience function)
    """
    # Implementation remains the same as provided in the prompt, assuming AgentTemplateRegistry works.
    from core.agents.templates import AgentTemplateRegistry

    template = AgentTemplateRegistry.get(template_id)
    if not template:
        raise ValueError(f"Agent template not found: {template_id}")

    agent_config = template.to_agent_config()

    if customizations:
        agent_config.update(customizations)

    return await AgentFactory.create_agent(
        agent_config=agent_config,
        project_id=project_id,
        task_id=task_id,
        context=context,
        mcp_manager=mcp_manager,
        vector_store=vector_store
    )


# Re-exported from services.agent_utils for backward compatibility with
# existing importers (tests, scripts, chat endpoints).
from services.agent_utils import (
    validate_agent_config,
    resolve_model,
    create_llm_with_fallbacks,
    load_agent_tools,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    SUPPORTED_MODELS,
)

__all__ = [
    "AgentFactory",
    "create_agent_from_template",
    "DEFAULT_AGENT_GUARDRAILS",
    "REASONING_FRAMEWORK",
    "validate_agent_config",
    "resolve_model",
    "create_llm_with_fallbacks",
    "load_agent_tools",
    "DEFAULT_MODEL",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_MAX_TOKENS",
    "SUPPORTED_MODELS",
]

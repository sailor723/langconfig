# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Shared state for the core.agents.factory package.

Split out of core/agents/factory.py; moved verbatim.
"""
import logging

logger = logging.getLogger("core.agents.factory")

# =============================================================================
# AGENT GUARDRAILS FRAMEWORK
# =============================================================================
# This prompt is prepended to every agent's system prompt to enforce:
# 1. Stopping criteria - prevents infinite loops and over-exploration
# 2. Tool usage guidelines - ensures tools are called with correct parameters
#
# NOTE: The reasoning loop (Reason -> Act -> Observe) is handled internally by
# LangChain's create_agent(). These guardrails add production-safety rules.
#
# This can be customized per-agent via the "reasoning_framework" config field.
# =============================================================================

DEFAULT_AGENT_GUARDRAILS = """
# AGENT EXECUTION GUARDRAILS

## STOPPING CRITERIA
- **STOP AFTER 2-3 TOOL CALLS** if you have sufficient information
- **For searches**: One or two searches should provide enough context - do NOT search the same topic repeatedly
- **Quality over quantity**: Provide a good answer with 2-3 sources rather than searching indefinitely
- **When you have relevant information, STOP and provide your answer**
- **Do NOT repeat the same tool call** - if it succeeded, use the results and move on

## TOOL USAGE RULES
- **ALWAYS verify you have ALL required parameters** before calling a tool
- **For write_file**: You MUST provide both `file_path` AND `content` parameters
  - Do NOT call write_file with only file_path
  - Wait until you have complete content ready before writing
- **Do NOT call tools with partial or missing arguments** - this causes validation errors
- **Read tool descriptions carefully** - they specify which parameters are required
"""

# Legacy alias for backward compatibility
REASONING_FRAMEWORK = DEFAULT_AGENT_GUARDRAILS

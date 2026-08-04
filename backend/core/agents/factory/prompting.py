# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""System prompt construction, skill injection, and context augmentation.

Split out of core/agents/factory.py; moved verbatim. The concrete
``AgentFactory`` class (defined in the package ``__init__``) subclasses
this mixin. Bare ``AgentFactory.`` references in staticmethod bodies are
late-bound into this module's globals by ``_bind_runtime``.
"""

from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.tools import BaseTool

from .shared import DEFAULT_AGENT_GUARDRAILS, logger


class _AgentPromptingMixin:

    @staticmethod
    def _construct_system_prompt_string(
        base_prompt: str,
        context: str,
        enable_memory: bool,
        long_term_memory: bool = False,
        tools: List[BaseTool] = None,
        custom_guardrails: Optional[Union[str, Dict[str, Any]]] = None
    ) -> str:
        """
        Constructs the system prompt string using Context Engineering principles.
        Structure: Guardrails -> Role/Goal -> Context

        Args:
            base_prompt: The agent's role/goal (user-defined system prompt)
            context: Current task context
            enable_memory: Whether memory tools are enabled
            long_term_memory: Whether workflow-scoped Store memory is enabled
            tools: List of tools available to the agent
            custom_guardrails: Optional custom guardrails (per-agent override)
                              If None, uses DEFAULT_AGENT_GUARDRAILS

        Note: In LangChain v1.0, create_agent handles the reasoning loop internally.
        These guardrails add production-safety rules (stopping criteria, tool usage).
        """
        # Guardrails can be a plain string (legacy prompt rules) or a structured
        # dict (interrupts/token_limits runtime config). A dict is operational
        # config, not prompt text — fall back to the default string guardrails.
        if isinstance(custom_guardrails, dict):
            custom_guardrails = None
        # Use custom guardrails if provided, otherwise use default
        guardrails = custom_guardrails if custom_guardrails is not None else DEFAULT_AGENT_GUARDRAILS
        if enable_memory:
            guardrails += "\n# MEMORY USAGE\nYou have access to long-term memory tools (e.g., 'memory_recall', 'memory_store'). Use them to access and record knowledge relevant to this project."

        if long_term_memory:
            guardrails += "\n# WORKFLOW-SCOPED LONG-TERM MEMORY\nYou have access to workflow-scoped persistent memory via the LangGraph Store API (runtime.store). Use this to remember important information across workflow executions. Store data using workflow-specific namespaces."

        # CRITICAL: Add explicit tool enforcement if tools are available
        tool_enforcement = ""
        if tools and len(tools) > 0:
            tool_names = [t.name for t in tools]
            tool_enforcement = f"""
# CRITICAL TOOL USAGE REQUIREMENT
You have been equipped with the following tools: {', '.join(tool_names)}

**MANDATORY REQUIREMENT:**
- If your role involves using external services, APIs, or generating content (images, files, etc.), you MUST use the appropriate tool
- DO NOT just describe what you would do or provide meta-commentary
- DO NOT say things like "I understand" or "I need to work with what I have"
- ACTUALLY INVOKE THE TOOL to complete your task
- For example, if you are an "Image Generator" with an image generation tool, you MUST call that tool to generate images
- If you are a "File Writer" with a file writing tool, you MUST call that tool to write files
- Your output should be the RESULT of tool execution, not a description of what you plan to do

**If you fail to use your tools when required, your output will be considered incomplete.**
"""

        # DB mode (STORAGE_MODE=db): the final deliverable must be persisted
        # through save_document into the agent_documents document library
        # instead of being written to a loose file.
        doc_library_guidance = ""
        if tools and any(t.name == "save_document" for t in tools):
            doc_library_guidance = """
# DOCUMENT LIBRARY (DB MODE)
You have the 'save_document' tool for persisting the FINAL deliverable of this task.
- Call save_document(title=..., content=..., doc_type=...) with the COMPLETE final document once you have finished it
- Use a clear, descriptive title (e.g. 'Q3 Market Analysis Report') and the full final content
- Use write_file only for working files (scratch, todos, intermediate artifacts) — never for the final deliverable
"""

        system_message_content = f"""{guardrails}
{tool_enforcement}
{doc_library_guidance}
# YOUR SPECIFIC ROLE AND GOAL
{base_prompt}

# CURRENT CONTEXT AND TASK INFORMATION
<context>
{context}
</context>
---
"""
        return system_message_content

    @staticmethod
    async def _build_prompt_and_middleware(
        context: str,
        base_system_prompt: str,
        enable_memory: bool,
        long_term_memory: bool,
        tools: List[BaseTool],
        agent_config: Dict[str, Any],
        agent_context: Optional[Dict[str, Any]],
        middleware_list: List[Any],
        enable_default_middleware: bool,
        model_hooks: List[Any],
        enable_default_hooks: bool,
        project_id: int,
        task_id: int,
    ) -> Tuple[str, Optional[List], Optional[Any]]:
        """
        Compose the final system prompt and resolve middleware (or legacy hooks).

        Steps performed (matches the original inline order in ``create_agent``):
          1. Augment context with learned pattern recommendations.
          2. Build the system prompt string (guardrails + role + context).
          3. Optionally inject skills into the system prompt.
          4. Set up middleware (v1.0) or fall back to legacy hooks.

        Mutates ``agent_config`` to stash ``_middleware`` or ``_hook_manager``
        for downstream consumers.
        """
        # 1. Augment context with pattern recommendations.
        augmented_context = await AgentFactory._augment_context_with_patterns(
            context=context,
            agent_config=agent_config,
            project_id=project_id,
            task_id=task_id,
        )

        # 2. Build the base system prompt (guardrails + role + context).
        system_prompt_str = AgentFactory._construct_system_prompt_string(
            base_system_prompt,
            augmented_context,
            enable_memory,
            long_term_memory,
            tools,
            custom_guardrails=agent_config.get("guardrails"),
        )

        # 3. Optionally inject skills.
        if agent_config.get("enable_skills", False):
            explicit_skills = agent_config.get("skills", [])
            enable_skill_auto_detection = agent_config.get(
                "enable_skill_auto_detection", True
            )
            skill_context = {
                "query": context,
                "project_type": agent_config.get("project_type"),
                "tags": agent_config.get("skill_tags", []),
            }
            if agent_context:
                skill_context["file_path"] = agent_context.get("file_path")
                skill_context["file_content"] = agent_context.get("file_content")

            system_prompt_str = await AgentFactory._inject_skills(
                system_prompt=system_prompt_str,
                context=skill_context,
                explicit_skills=explicit_skills,
                enable_auto_detection=enable_skill_auto_detection,
                max_skills=agent_config.get("max_skills", 3),
            )

        # 4. Set up middleware (v1.0) or fall back to legacy hooks.
        middleware: Optional[List] = None
        hook_manager: Optional[Any] = None

        if middleware_list or enable_default_middleware:
            middleware = await AgentFactory._setup_middleware(
                middleware_list=middleware_list,
                enable_default_middleware=enable_default_middleware,
                project_id=project_id,
                task_id=task_id,
            )
            if middleware:
                agent_config["_middleware"] = middleware
        elif model_hooks or enable_default_hooks:
            logger.info("Using legacy hooks (consider migrating to middleware)")
            hook_manager = await AgentFactory._setup_model_hooks(
                model_hooks=model_hooks,
                enable_default_hooks=enable_default_hooks,
                project_id=project_id,
                task_id=task_id,
            )
            if hook_manager:
                agent_config["_hook_manager"] = hook_manager

        return system_prompt_str, middleware, hook_manager

    @staticmethod
    async def _inject_skills(
        system_prompt: str,
        context: Dict[str, Any],
        explicit_skills: Optional[List[str]] = None,
        enable_auto_detection: bool = True,
        max_skills: int = 3
    ) -> str:
        """
        Inject relevant skill instructions into the system prompt.

        Skills are modular, context-aware capabilities that enhance agent behavior.
        They can be explicitly requested or automatically detected based on context.

        Args:
            system_prompt: The base system prompt to enhance
            context: Execution context for matching (query, file_path, project_type, etc.)
            explicit_skills: Optional list of skill IDs to always include
            enable_auto_detection: Whether to auto-detect relevant skills
            max_skills: Maximum number of skills to inject

        Returns:
            Enhanced system prompt with skill instructions
        """
        try:
            from core.skills.registry import get_skill_registry
            from core.skills.matcher import get_skill_matcher

            registry = get_skill_registry()
            matcher = get_skill_matcher()

            # Ensure registry is initialized
            if not registry.is_initialized:
                await registry.initialize()

            skill_instructions = []
            skills_used = []

            # 1. Add explicitly requested skills
            if explicit_skills:
                for skill_id in explicit_skills[:max_skills]:
                    skill = registry.get_skill(skill_id)
                    if skill:
                        skill_instructions.append(AgentFactory._format_skill_for_prompt(skill))
                        skills_used.append(skill_id)

            # 2. Auto-detect relevant skills (if enabled and room for more)
            remaining_slots = max_skills - len(skills_used)
            if enable_auto_detection and remaining_slots > 0 and context:
                matches = await matcher.find_relevant_skills(
                    context=context,
                    max_results=remaining_slots,
                    min_score=0.6
                )
                for match in matches:
                    if match.skill.skill_id not in skills_used:
                        skill_instructions.append(AgentFactory._format_skill_for_prompt(match.skill))
                        skills_used.append(match.skill.skill_id)
                        logger.info(
                            f"Auto-injecting skill '{match.skill.skill_id}' "
                            f"(score={match.score:.2f}, reason={match.match_reason})"
                        )

            # 3. Inject skills into system prompt if any were found
            if skill_instructions:
                skills_section = "\n\n# AVAILABLE SKILLS\n" + \
                    "The following skills provide specialized guidance for your task:\n\n" + \
                    "\n\n---\n\n".join(skill_instructions)

                # Insert skills section before the context section
                if "# CURRENT CONTEXT" in system_prompt:
                    system_prompt = system_prompt.replace(
                        "# CURRENT CONTEXT",
                        f"{skills_section}\n\n# CURRENT CONTEXT"
                    )
                else:
                    system_prompt = system_prompt + skills_section

                logger.info(f"Injected {len(skill_instructions)} skill(s): {skills_used}")

            return system_prompt

        except Exception as e:
            logger.warning(f"Failed to inject skills: {e}")
            return system_prompt  # Return original prompt on error

    @staticmethod
    def _format_skill_for_prompt(skill) -> str:
        """Format a skill for injection into system prompt."""
        parts = [
            f"## Skill: {skill.name}",
            f"**Description:** {skill.description}",
            "",
            skill.instructions
        ]

        if skill.examples:
            parts.extend(["", "**Examples:**", "", skill.examples])

        if skill.allowed_tools:
            parts.extend(["", f"**Allowed Tools:** {', '.join(skill.allowed_tools)}"])

        return "\n".join(parts)

    @staticmethod
    async def _augment_context_with_patterns(
        context: str,
        agent_config: Dict[str, Any],
        project_id: int,
        task_id: int
    ) -> str:
        """
        Augment context with learned pattern recommendations.

        This integrates pattern learning into agent execution by providing agents with
        proven strategies from past successful workflows.

        Args:
            context: Original context string
            agent_config: Agent configuration (contains pattern hints)
            project_id: Project ID for pattern filtering
            task_id: Task ID for logging

        Returns:
            Augmented context string with pattern recommendations appended
        """
        try:
            # Check if pattern recommendations are enabled for this agent
            enable_patterns = agent_config.get("enable_pattern_recommendations", False)
            if not enable_patterns:
                logger.debug(f"Pattern recommendations disabled for task {task_id}")
                return context

            # Try to extract task description from context for better pattern matching
            # The context usually contains the task description in some form
            task_description = agent_config.get("task_description", "")
            if not task_description:
                # Try to extract from context (simple heuristic)
                lines = context.split('\n')
                # Look for lines that might contain task description
                for line in lines[:10]:  # Check first 10 lines
                    if len(line.strip()) > 20 and not line.strip().startswith('#'):
                        task_description = line.strip()
                        break

            if not task_description:
                logger.debug(f"No task description found for pattern recommendations (task {task_id})")
                return context

            # Get pattern type hints from agent config or default to common useful patterns
            pattern_types = agent_config.get("pattern_types", ["context_strategy", "agent_behavior"])

            # Fetch pattern recommendations
            from services.pattern_learning_service import PatternLearningService
            from models.agent_pattern import PatternType
            from backend.db.session import SessionLocal

            pattern_recommendations = []

            async with SessionLocal() as db:
                service = PatternLearningService(db)

                for pattern_type_str in pattern_types[:2]:  # Limit to 2 pattern types to avoid context bloat
                    try:
                        pattern_type = PatternType(pattern_type_str)
                        patterns = await service.get_pattern_recommendations(
                            task_description=task_description,
                            pattern_type=pattern_type,
                            project_id=project_id,
                            min_confidence=0.7,  # Only high-confidence recommendations
                            limit=2  # Max 2 recommendations per type
                        )

                        if patterns:
                            pattern_recommendations.extend(patterns)
                            logger.info(
                                f"Found {len(patterns)} {pattern_type_str} patterns for task {task_id}"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to get {pattern_type_str} patterns: {e}")
                        continue

            # If no patterns found, return original context
            if not pattern_recommendations:
                logger.debug(f"No pattern recommendations found for task {task_id}")
                return context

            # Format pattern recommendations for injection
            pattern_section = "\n\n# LEARNED PATTERNS FROM PAST SUCCESSES\n"
            pattern_section += "The following patterns have proven successful for similar tasks:\n\n"

            for i, pattern in enumerate(pattern_recommendations[:3], 1):  # Max 3 total patterns
                pattern_section += f"**Pattern {i}: {pattern.pattern_name}** (Type: {pattern.pattern_type})\n"
                pattern_section += f"- Success Rate: {pattern.success_rate:.1%} ({pattern.success_count}/{pattern.usage_count} uses)\n"
                pattern_section += f"- Confidence: {pattern.confidence:.2f}\n"

                if pattern.description:
                    pattern_section += f"- Description: {pattern.description}\n"

                if pattern.pattern_config:
                    # Format config as readable text (avoid dumping full JSON)
                    config_highlights = []
                    for key, value in list(pattern.pattern_config.items())[:3]:  # Top 3 config items
                        config_highlights.append(f"{key}: {value}")
                    if config_highlights:
                        pattern_section += f"- Key Settings: {', '.join(config_highlights)}\n"

                pattern_section += "\n"

            pattern_section += "**Recommendation:** Consider applying these proven patterns to improve success probability.\n"
            pattern_section += "---\n"

            # Append patterns to context
            augmented_context = context + pattern_section

            logger.info(
                f"Augmented context with {len(pattern_recommendations)} pattern recommendations "
                f"for task {task_id}"
            )

            return augmented_context

        except Exception as e:
            # Fail gracefully - if pattern retrieval fails, agent should still work with original context
            logger.warning(
                f"Failed to augment context with patterns for task {task_id}: {e}. "
                "Proceeding with original context."
            )
            return context


def _bind_runtime() -> None:
    """Bind the concrete AgentFactory class into this module's globals.

    Staticmethod bodies reference the concrete class by its bare name
    (e.g. ``AgentFactory._create_llm``), which must resolve in this
    module's globals at call time. The concrete class is defined in the
    package ``__init__``, which imports this module first — hence this
    late binding avoids a circular import.
    """
    from core.agents.factory import AgentFactory
    globals()["AgentFactory"] = AgentFactory

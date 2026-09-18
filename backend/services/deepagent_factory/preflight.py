# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DeepAgent factory preflight helpers.

Configuration validation and the skill-router LLM call, extracted from the
former monolithic deepagent_factory.py.
"""

from typing import List, Optional

from openai import OpenAI

from models.deep_agent import DeepAgentConfig
from .shared import logger


class _DeepAgentPreflightMixin:
    @staticmethod
    def _validate_deep_agent_config(config: DeepAgentConfig) -> List[str]:
        """
        Basic validation of DeepAgent configuration.

        Returns:
            List of error/warning messages (empty if valid)
        """
        errors = []

        # 1. Required: model must be set
        if not config.model:
            errors.append("model is required")

        # 2. Required: system_prompt must be set
        if not config.system_prompt:
            errors.append("system_prompt is required")

        # 3. Validate temperature bounds (0.0 to 2.0)
        if not (0.0 <= config.temperature <= 2.0):
            errors.append(f"temperature must be between 0.0 and 2.0, got {config.temperature}")

        # 4-6. Type and consistency validation now handled by Pydantic validators
        # Enum types ensure only valid values are accepted
        # @model_validator decorators check cross-field constraints
        # No runtime validation needed here

        return errors

    @staticmethod
    async def _run_skill_router(
        router_model: str,
        skill_records: list,
        user_message: str
    ) -> Optional[str]:
        """
        Call the router LLM to classify which skill matches the user's request.

        Args:
            router_model: Model name (e.g. "deepseek:deepseek-chat")
            skill_records: List of Skill DB records with skill_id and description
            user_message: The user's first message

        Returns:
            Matched skill_id string, or None if no skill matches
        """
        try:
            # Build skill descriptions list
            skill_lines = []
            for s in skill_records:
                desc = s.description or ""
                skill_lines.append(f"- {s.skill_id}: {desc}")

            skills_text = "\n".join(skill_lines)

            routing_prompt = (
                f"You are a skill router. Classify the user's request to the most relevant skill.\n\n"
                f"Available skills:\n{skills_text}\n\n"
                f"Return ONLY the skill_id (one word) that best matches, or 'none' if no skill matches. "
                f"Do NOT include any other text, explanation, or formatting.\n\n"
                f"User: {user_message}"
            )

            # Normalize model name — strip provider prefix
            model_name = router_model.replace("deepseek:", "").replace("agnes:", "")

            # Get API key from DB settings (not from env)
            from config import get_api_key_from_db
            if router_model.startswith("deepseek"):
                api_key = get_api_key_from_db("deepseek_api_key")
                base_url = "https://api.deepseek.com/v1"
            elif router_model.startswith("agnes"):
                api_key = get_api_key_from_db("agnes_api_key")
                base_url = None  # uses default
            else:
                api_key = get_api_key_from_db("openai_api_key")
                base_url = None

            if not api_key:
                logger.warning(f"Skill Router: no API key found for {router_model}. Falling back to all skills.")
                return None

            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": routing_prompt}],
                temperature=0.1,
                max_tokens=20,
            )

            result = response.choices[0].message.content.strip().lower()

            # Validate result is a known skill_id
            valid_ids = {s.skill_id.lower() for s in skill_records}
            if result in valid_ids:
                logger.info(f"Skill Router selected: {result}")
                return result
            else:
                logger.info(f"Skill Router returned '{result}' — no matching skill, using all skills")
                return None

        except Exception as e:
            logger.warning(f"Skill Router failed: {e}. Falling back to all skills.")
            return None


def _bind_runtime() -> None:
    """Bind the concrete DeepAgentFactory class into this module's globals.

    The staticmethod bodies reference the concrete class by its bare name
    (e.g. ``DeepAgentFactory._validate_deep_agent_config``), which must
    resolve in this module's globals at call time. The concrete class is
    defined in the package ``__init__``, which imports this module first —
    hence this late binding avoids a circular import.
    """
    from services.deepagent_factory import DeepAgentFactory
    globals()["DeepAgentFactory"] = DeepAgentFactory

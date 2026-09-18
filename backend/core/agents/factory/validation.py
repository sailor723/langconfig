# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Config validation for AgentFactory (delegates to services.agent_utils).

Split out of core/agents/factory.py; moved verbatim. The concrete
``AgentFactory`` class (defined in the package ``__init__``) subclasses
this mixin. Bare ``AgentFactory.`` references in staticmethod bodies are
late-bound into this module's globals by ``_bind_runtime``.
"""

from typing import Any, Dict, List

from services.agent_utils import validate_agent_config


class _AgentValidationMixin:

    @staticmethod
    def _validate_agent_config(agent_config: Dict[str, Any]) -> List[str]:
        """Delegate to shared validate_agent_config from services.agent_utils."""
        return validate_agent_config(agent_config)


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

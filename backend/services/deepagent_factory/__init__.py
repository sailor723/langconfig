# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DeepAgent Factory Service.

Creates DeepAgents using the deepagents library while integrating
with LangConfig's existing agent factory infrastructure.
"""

from .shared import logger
from .preflight import _DeepAgentPreflightMixin
from .assembly import _DeepAgentAssemblyMixin
from .support import _DeepAgentSupportMixin


class DeepAgentFactory(_DeepAgentPreflightMixin, _DeepAgentAssemblyMixin, _DeepAgentSupportMixin):
    """
    Factory for creating DeepAgents with full middleware and backend support.
    Wraps the deepagents library while integrating with LangConfig infrastructure.
    """
    # Note: Type validation now handled by Pydantic enums in models.enums
    # No need for VALID_* constants anymore


# Late-bind the concrete class into the mixin modules so their staticmethod
# bodies' bare ``DeepAgentFactory.`` references resolve at call time.
from . import preflight as _preflight
from . import assembly as _assembly
from . import support as _support
_preflight._bind_runtime()
_assembly._bind_runtime()
_support._bind_runtime()

# DeepAgent library v0.6.8 already provides:
#   - StateBackend, StoreBackend, CompositeBackend (deepagents.backends)
#   - FilesystemBackend, LocalShellBackend, LangSmithSandbox
# Use those directly. See https://docs.langchain.com/oss/python/deepagents/backends

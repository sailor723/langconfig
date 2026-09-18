# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tool Factory - Dynamic Custom Tool Creation
============================================

Creates LangChain tools dynamically from user configurations.
Supports multiple tool types: API, Notification, Image/Video, Database, Data Transform.

Pattern: Mirrors AgentFactory architecture for consistency.
"""

from typing import Dict

from .shared import logger, get_pending_artifacts, store_artifact
from .models import ToolTypes, ValidationResult, LangChainRequirements
from .base import _ToolFactoryBaseMixin
from .builders import _ToolBuildersMixin


# =============================================================================
# Tool Factory Core
# =============================================================================

class ToolFactory(_ToolFactoryBaseMixin, _ToolBuildersMixin):
    """
    Factory for creating custom LangChain tools dynamically.

    Follows AgentFactory pattern for consistency.
    """

    # Class-level cache for Pydantic schemas
    # Key: hash of (tool_id + input_schema), Value: Pydantic model class
    _schema_cache: Dict[str, type] = {}


# Late-bind the concrete class into the mixin modules so their staticmethod
# bodies' bare ``ToolFactory.`` references resolve at call time.
from . import base as _base
from . import builders as _builders
_base._bind_runtime()
_builders._bind_runtime()

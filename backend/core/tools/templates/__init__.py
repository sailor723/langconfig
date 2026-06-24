# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tool Templates - package of pre-configured tool templates.

Created 2026-06-24 by splitting the old 1385-line templates.py into per-template
files. Each template lives in its own file under a category subdirectory.

Re-exports ToolTemplate and ToolTemplateRegistry for backward compatibility
with the old `from core.tools.templates import X` imports.

Usage (same as before):
    from core.tools.templates import ToolTemplateRegistry
    templates = ToolTemplateRegistry.list_templates()

Or import a specific template directly:
    from core.tools.templates.notification.slack import NOTIFICATION_SLACK_TEMPLATE
"""

# Original imports (kept for backward compat with the old file)
from typing import Dict, List, Any, Optional
from enum import Enum
from pydantic import BaseModel, Field

from models.custom_tool import ToolType, ToolTemplateType


# Base classes (extracted from old templates.py)
class ToolTemplate(BaseModel):
    """
    Template for creating custom tools.

    Provides pre-configured defaults and required fields.
    """
    template_id: str = Field(..., description="Unique template identifier")
    name: str = Field(..., description="Display name")
    description: str = Field(..., description="What this tool does")
    category: str = Field(..., description="Tool category")
    tool_type: ToolType = Field(..., description="Type of tool")

    # Icon/visual for UI
    icon: str = Field(default="🔧", description="Emoji or icon identifier")
    priority: int = Field(default=0, description="Display priority (higher = featured)")

    # Template configuration structure
    config_template: Dict[str, Any] = Field(
        ...,
        description="Template configuration with placeholders"
    )
    input_schema_template: Dict[str, Any] = Field(
        ...,
        description="JSON Schema template for tool inputs"
    )

    # Required fields that users must fill
    required_user_fields: List[str] = Field(
        default_factory=list,
        description="Fields that users must customize"
    )

    # Helper information for users
    setup_instructions: str = Field(
        default="",
        description="Instructions for setting up this tool"
    )
    example_use_cases: List[str] = Field(
        default_factory=list,
        description="Example scenarios for using this tool"
    )

    # Metadata
    tags: List[str] = Field(default_factory=list)
    is_featured: bool = Field(default=False)

    def to_tool_config(self, user_values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert template to tool configuration with user values.

        Args:
            user_values: User-provided values for customization

        Returns:
            Complete tool configuration
        """
        # Deep copy config template
        import copy
        config = copy.deepcopy(self.config_template)

        # Apply user values
        for key, value in user_values.items():
            if key in config.get("implementation_config", {}):
                config["implementation_config"][key] = value
            else:
                config[key] = value

        return config


# =============================================================================
# Tool Template Registry
# =============================================================================

class ToolTemplateRegistry:
    """
    Registry of available tool templates.

    Mirrors AgentTemplateRegistry pattern.
    """
    _templates: Dict[str, ToolTemplate] = {}

    @classmethod
    def register(cls, template: ToolTemplate):
        """Register a tool template"""
        cls._templates[template.template_id] = template

    @classmethod
    def get(cls, template_id: str) -> Optional[ToolTemplate]:
        """Get a template by ID"""
        return cls._templates.get(template_id)

    @classmethod
    def list_all(cls) -> List[ToolTemplate]:
        """List all available templates"""
        return list(cls._templates.values())

    @classmethod
    def list_by_type(cls, tool_type: ToolType) -> List[ToolTemplate]:
        """List templates filtered by tool type"""
        return [t for t in cls._templates.values() if t.tool_type == tool_type]

    @classmethod
    def list_featured(cls) -> List[ToolTemplate]:
        """List featured templates"""
        return [t for t in cls._templates.values() if t.is_featured]


# =============================================================================
# TEMPLATE DEFINITIONS
# =============================================================================

# -----------------------------------------------------------------------------
# 1. NOTIFICATION TOOLS (PRIORITY)
# -----------------------------------------------------------------------------

# All template definitions (re-exported for convenience)
from core.tools.templates.notification.slack import NOTIFICATION_SLACK_TEMPLATE
from core.tools.templates.notification.discord import NOTIFICATION_DISCORD_TEMPLATE
from core.tools.templates.cms.wordpress import CMS_WORDPRESS_TEMPLATE
from core.tools.templates.social.twitter import SOCIAL_TWITTER_TEMPLATE
from core.tools.templates.api.webhook import API_WEBHOOK_TEMPLATE
from core.tools.templates.image.openai_dalle3 import IMAGE_OPENAI_DALLE3_TEMPLATE
from core.tools.templates.image.gpt_image_1_5 import IMAGE_OPENAI_GPT_IMAGE_1_5_TEMPLATE
from core.tools.templates.image.gemini_imagen3 import IMAGE_GEMINI_IMAGEN3_TEMPLATE
from core.tools.templates.image.gemini_nano_banana import IMAGE_GEMINI_NANO_BANANA_TEMPLATE
from core.tools.templates.video.openai_sora import VIDEO_OPENAI_SORA_TEMPLATE
from core.tools.templates.video.gemini_veo3 import VIDEO_GEMINI_VEO3_TEMPLATE
from core.tools.templates.video.gemini_veo31 import VIDEO_GEMINI_VEO31_TEMPLATE
from core.tools.templates.database.postgres import DATABASE_POSTGRES_TEMPLATE
from core.tools.templates.data.json_transform import DATA_TRANSFORM_JSON_TEMPLATE
from core.tools.templates.python.python_function import PYTHON_FUNCTION_TEMPLATE

# Templates auto-register on import (see each file's ToolTemplateRegistry.register() call)

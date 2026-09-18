# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Shared models for the tool factory: tool type constants, the validation
result model, and the LangChain compatibility requirements.

Extracted from the former monolithic factory.py.
"""

import re
from typing import Dict, Any, List

from pydantic import BaseModel, Field


# =============================================================================
# Tool Type Constants
# =============================================================================

class ToolTypes:
    """Constants for tool types - replaces magic strings"""
    API = "api"
    NOTIFICATION = "notification"
    IMAGE_VIDEO = "image_video"
    DATABASE = "database"
    DATA_TRANSFORM = "data_transform"
    PYTHON_FUNCTION = "python_function"


# =============================================================================
# Validation Result Model
# =============================================================================

class ValidationResult(BaseModel):
    """Result of tool configuration validation"""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    langchain_compatible: bool = True


# =============================================================================
# LangChain Requirements
# =============================================================================

class LangChainRequirements:
    """Required fields for LangChain tool compatibility"""

    REQUIRED_FIELDS = {
        "tool_id": str,
        "name": str,
        "description": str,
        "input_schema": dict
    }

    RECOMMENDED_FIELDS = {
        "output_format": str,
        "error_handling": dict
    }

    @staticmethod
    def validate(tool_config: Dict[str, Any]) -> ValidationResult:
        """
        Validate tool configuration against LangChain requirements.

        Returns:
            ValidationResult with validation details
        """
        result = ValidationResult(is_valid=True, langchain_compatible=True)

        # Check required fields
        for field_name, field_type in LangChainRequirements.REQUIRED_FIELDS.items():
            if field_name not in tool_config:
                result.errors.append(f"Missing required field: {field_name}")
                result.is_valid = False
                result.langchain_compatible = False
            elif not isinstance(tool_config[field_name], field_type):
                result.errors.append(f"Field '{field_name}' must be of type {field_type.__name__}")
                result.is_valid = False

        # Check recommended fields
        for field_name, field_type in LangChainRequirements.RECOMMENDED_FIELDS.items():
            if field_name not in tool_config:
                result.warnings.append(f"Recommended field missing: {field_name}")

        # Validate tool_id format (alphanumeric + underscores + hyphens)
        if "tool_id" in tool_config:
            if not re.match(r'^[a-zA-Z0-9_-]+$', tool_config["tool_id"]):
                result.errors.append("tool_id must contain only letters, numbers, underscores, and hyphens")
                result.is_valid = False

        # Validate description is not empty
        if "description" in tool_config:
            if not tool_config["description"].strip():
                result.errors.append("description cannot be empty (required for LLM understanding)")
                result.is_valid = False
                result.langchain_compatible = False

        # Validate input_schema structure
        if "input_schema" in tool_config:
            schema = tool_config["input_schema"]
            if not isinstance(schema, dict):
                result.errors.append("input_schema must be a dictionary (JSON Schema format)")
                result.is_valid = False
            elif "properties" not in schema:
                result.warnings.append("input_schema should have 'properties' field")

        return result

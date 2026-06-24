# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
DATA_TRANSFORM_JSON_TEMPLATE - Data category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


DATA_TRANSFORM_JSON_TEMPLATE = ToolTemplate(
    template_id="data_transform_json",
    name="Data Format Converter",
    description="Convert between JSON, CSV, XML, and YAML formats",
    category="data_transform",
    tool_type=ToolType.DATA_TRANSFORM,
    icon="🔄",
    priority=60,
    is_featured=False,
    config_template={
        "tool_type": "data_transform",
        "template_type": "data_transform_json",
        "implementation_config": {
            "input_format": "json",
            "output_format": "csv",
            "transformation_rules": [],
            "validate_output": True
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "data": {
                "type": "string",
                "description": "Data to transform"
            },
            "output_format": {
                "type": "string",
                "description": "Desired output format: json, csv, xml, yaml",
                "default": "json"
            }
        },
        "required": ["data"]
    },
    required_user_fields=[],
    setup_instructions="""
1. Select the input data format
2. Choose the desired output format
3. Optionally define transformation rules (JSONPath, mappings, etc.)
4. Enable output validation to ensure format correctness

Supports: JSON ↔ CSV ↔ XML ↔ YAML conversions
""",
    example_use_cases=[
        "Convert API responses from JSON to CSV for reporting",
        "Transform XML data to JSON for processing",
        "Generate YAML configs from JSON",
        "Extract specific fields using JSONPath",
        "Reshape data structures"
    ],
    tags=["data", "transform", "convert", "json", "csv", "xml", "yaml"]
)


# Register on import
ToolTemplateRegistry.register(DATA_TRANSFORM_JSON_TEMPLATE)

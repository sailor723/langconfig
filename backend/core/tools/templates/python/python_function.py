# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
PYTHON_FUNCTION_TEMPLATE - Python category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


PYTHON_FUNCTION_TEMPLATE = ToolTemplate(
    template_id="python_function",
    name="Python Function",
    description="Write custom Python code (add, subtract, data transform, etc.)",
    category="python",
    tool_type=ToolType.PYTHON_FUNCTION,
    icon="🐍",
    priority=90,
    is_featured=True,
    config_template={
        "tool_type": "python_function",
        "implementation_config": {
            "function_name": "my_function",
            "code": "def my_function(a: float, b: float) -> float:\n    \"\"\"My custom function.\"\"\"\n    return a + b",
            "args_schema": {
                "a": {"type": "float", "description": "First parameter"},
                "b": {"type": "float", "description": "Second parameter"}
            }
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "a": {
                "type": "number",
                "description": "First parameter"
            },
            "b": {
                "type": "number",
                "description": "Second parameter"
            }
        },
        "required": ["a", "b"]
    },
    required_user_fields=["code", "function_name"],
    setup_instructions="""
1. Write a Python function with clear parameter names and type hints
2. The function will be executed dynamically when the agent calls it
3. Arguments are passed based on the args_schema you define
4. math and json modules are available by default
5. Test your function with simple values before using it in complex tasks
    """,
    example_use_cases=[
        "Add/subtract/multiply/divide numbers (arithmetic)",
        "Calculate square root or other math operations",
        "Transform data structures or validate input",
        "Format strings or parse text patterns",
        "Any simple Python computation"
    ],
    tags=["python", "code", "function", "math", "custom"]
)


# Register on import
ToolTemplateRegistry.register(PYTHON_FUNCTION_TEMPLATE)

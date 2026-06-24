# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
API_WEBHOOK_TEMPLATE - Api category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


API_WEBHOOK_TEMPLATE = ToolTemplate(
    template_id="api_webhook",
    name="API / Webhook Call",
    description="Make HTTP requests to any REST API or webhook",
    category="api",
    tool_type=ToolType.API,
    icon="🌐",
    priority=90,
    is_featured=True,
    config_template={
        "tool_type": "api",
        "template_type": "api_webhook",
        "implementation_config": {
            "method": "GET",
            "url": "",  # USER MUST PROVIDE
            "headers": {},
            "auth": {
                "type": "none"
            },
            "body_template": None,
            "response_parser": {
                "type": "full_response"
            },
            "timeout": 30
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "endpoint": {
                "type": "string",
                "description": "API endpoint path or full URL"
            }
        },
        "required": ["endpoint"]
    },
    required_user_fields=["url", "method"],
    setup_instructions="""
1. Enter the API base URL or full endpoint URL
2. Select HTTP method (GET, POST, PUT, DELETE, PATCH)
3. Add any required headers (e.g., Content-Type, API keys)
4. Configure authentication if needed
5. For POST/PUT/PATCH, define the request body template
6. Configure how to parse the response

Variables in URL/body are substituted from agent inputs using {variable_name} syntax.
""",
    example_use_cases=[
        "Trigger deployments via CI/CD webhooks",
        "Create tickets in project management systems",
        "Query external data APIs",
        "Send data to analytics platforms",
        "Integrate with third-party services"
    ],
    tags=["api", "webhook", "http", "rest", "integration"]
)


# Register on import
ToolTemplateRegistry.register(API_WEBHOOK_TEMPLATE)

# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
NOTIFICATION_SLACK_TEMPLATE - Notification category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


NOTIFICATION_SLACK_TEMPLATE = ToolTemplate(
    template_id="notification_slack",
    name="Slack Notification",
    description="Send messages to Slack channels via webhook or bot",
    category="notification",
    tool_type=ToolType.NOTIFICATION,
    icon="💬",
    priority=100,  # Highest priority
    is_featured=True,
    config_template={
        "tool_type": "notification",
        "template_type": "notification_slack",
        "implementation_config": {
            "provider": "slack",
            "webhook_url": "",  # USER MUST PROVIDE
            "channel": "#general",
            "message_template": "{message}",
            "username": "LangConfig Bot",
            "icon_emoji": ":robot_face:",
            "timeout": 10
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message to send to Slack"
            },
            "channel": {
                "type": "string",
                "description": "Channel to send to (optional, uses default if not specified)",
                "default": "#general"
            },
            "priority": {
                "type": "string",
                "description": "Message priority: normal, high, urgent",
                "default": "normal"
            }
        },
        "required": ["message"]
    },
    required_user_fields=["webhook_url"],
    setup_instructions="""
1. Go to https://api.slack.com/messaging/webhooks
2. Create a new Incoming Webhook for your workspace
3. Select the default channel
4. Copy the webhook URL
5. Paste it into the 'Webhook URL' field below

The webhook URL looks like: https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXX
""",
    example_use_cases=[
        "Send task completion notifications to team channel",
        "Alert when workflow encounters errors",
        "Notify stakeholders of important agent decisions",
        "Daily summary reports to project channel"
    ],
    tags=["notification", "slack", "messaging", "communication"]
)


# Register on import
ToolTemplateRegistry.register(NOTIFICATION_SLACK_TEMPLATE)

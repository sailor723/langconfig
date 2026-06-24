# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
NOTIFICATION_DISCORD_TEMPLATE - Notification category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


NOTIFICATION_DISCORD_TEMPLATE = ToolTemplate(
    template_id="notification_discord",
    name="Discord Notification",
    description="Send messages to Discord channels via webhook (supports multiple channels)",
    category="notification",
    tool_type=ToolType.NOTIFICATION,
    icon="🎮",
    priority=95,
    is_featured=True,
    config_template={
        "tool_type": "notification",
        "template_type": "notification_discord",
        "implementation_config": {
            "provider": "discord",
            # Support both single webhook or multiple channels
            "webhook_url": "",  # Default/fallback webhook (USER MUST PROVIDE)
            "webhooks": {
                # Example multi-channel setup (optional):
                # "announcements": "https://discord.com/api/webhooks/111111/aaaaa",
                # "updates": "https://discord.com/api/webhooks/222222/bbbbb",
                # "errors": "https://discord.com/api/webhooks/333333/ccccc"
            },
            "default_channel": "default",  # Which webhook to use if channel not specified
            "username": "LangConfig Bot",
            "avatar_url": "",
            "message_template": "{message}",
            "use_embeds": True,
            "embed_color": "#5865F2",  # Discord blurple
            "timeout": 10
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Message to send to Discord"
            },
            "channel": {
                "type": "string",
                "description": "Channel name to send to (uses default if not specified or webhook_url if only one configured)",
                "default": "default"
            },
            "title": {
                "type": "string",
                "description": "Embed title (if using embeds)",
                "default": ""
            },
            "color": {
                "type": "string",
                "description": "Embed color in hex (e.g., #FF0000)",
                "default": "#5865F2"
            },
            "username": {
                "type": "string",
                "description": "Override bot username for this message (optional)",
                "default": ""
            }
        },
        "required": ["message"]
    },
    required_user_fields=["webhook_url"],
    setup_instructions="""
SINGLE CHANNEL SETUP:
1. Open your Discord server
2. Go to Server Settings → Integrations → Webhooks
3. Click 'New Webhook'
4. Choose the channel and copy the webhook URL
5. Paste it into the 'Webhook URL' field below

MULTIPLE CHANNELS SETUP:
Each Discord webhook is permanently bound to ONE channel. To send to different channels:

1. Create separate webhooks for each channel:
   - Channel A: Server Settings → Integrations → Webhooks → New Webhook → Copy URL
   - Channel B: Server Settings → Integrations → Webhooks → New Webhook → Copy URL
   - Channel C: Server Settings → Integrations → Webhooks → New Webhook → Copy URL

2. In the 'Webhooks' configuration field (JSON), add your webhooks like this:
   {
     "announcements": "https://discord.com/api/webhooks/111111/aaaaa",
     "updates": "https://discord.com/api/webhooks/222222/bbbbb",
     "errors": "https://discord.com/api/webhooks/333333/ccccc"
   }

3. When calling the tool, specify which channel: {"message": "Hello!", "channel": "announcements"}

IMPORTANT: Each webhook URL is bound to the channel where you created it. You cannot change
which channel a webhook posts to - you must create a new webhook in the target channel.

Webhook URLs look like: https://discord.com/api/webhooks/[ID]/[TOKEN]
""",
    example_use_cases=[
        "Send workflow status to #updates, errors to #alerts",
        "Route different message types to different channels",
        "Alert moderators in #moderation, announce in #general",
        "Log to #logs, notify stakeholders in #notifications"
    ],
    tags=["notification", "discord", "messaging", "communication", "multi-channel"]
)


# Register on import
ToolTemplateRegistry.register(NOTIFICATION_DISCORD_TEMPLATE)

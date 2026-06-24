# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
VIDEO_OPENAI_SORA_TEMPLATE - Video category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


VIDEO_OPENAI_SORA_TEMPLATE = ToolTemplate(
    template_id="video_openai_sora",
    name="Sora Video Generator",
    description="Generate videos using OpenAI's Sora model",
    category="image_video",
    tool_type=ToolType.IMAGE_VIDEO,
    icon="🎬",
    priority=80,
    is_featured=False,
    config_template={
        "tool_type": "image_video",
        "template_type": "image_openai_sora",
        "implementation_config": {
            "provider": "openai",
            "model": "sora",
            "api_key": "",  # USER MUST PROVIDE
            "duration": 5,
            "resolution": "1080p",
            "timeout": 120
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Video generation prompt"
            },
            "duration": {
                "type": "integer",
                "description": "Video duration in seconds (3-60)",
                "default": 5
            }
        },
        "required": ["prompt"]
    },
    required_user_fields=["api_key"],
    setup_instructions="""
1. Get your OpenAI API key from https://platform.openai.com/api-keys
2. Ensure you have Sora access (may require waitlist approval)
3. Paste your API key below

Note: Sora is OpenAI's video generation model. Check availability and pricing.
""",
    example_use_cases=[
        "Generate video content from text descriptions",
        "Create animated product demonstrations",
        "Produce short video clips for social media",
        "Visualize concepts in motion"
    ],
    tags=["video", "generation", "openai", "sora", "animation"]
)


# Register on import
ToolTemplateRegistry.register(VIDEO_OPENAI_SORA_TEMPLATE)

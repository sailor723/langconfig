# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
VIDEO_GEMINI_VEO3_TEMPLATE - Video category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


VIDEO_GEMINI_VEO3_TEMPLATE = ToolTemplate(
    template_id="video_gemini_veo3",
    name="Veo 3 Video Generator",
    description="Generate videos using Google's Veo 3 model",
    category="image_video",
    tool_type=ToolType.IMAGE_VIDEO,
    icon="📹",
    priority=70,
    is_featured=False,
    config_template={
        "tool_type": "image_video",
        "template_type": "video_gemini_veo3",
        "implementation_config": {
            "provider": "google",
            "model": "veo-3",
            "api_key": "",  # USER MUST PROVIDE
            "duration": 5,
            "resolution": "1080p",
            "fps": 24,
            "aspect_ratio": "16:9",
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
                "description": "Video duration in seconds",
                "default": 5
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Video aspect ratio: 16:9, 9:16, 1:1, 4:3",
                "default": "16:9"
            }
        },
        "required": ["prompt"]
    },
    required_user_fields=["api_key"],
    setup_instructions="""
1. Get your Google Cloud API key with Vertex AI access
2. Enable the Veo API in your Google Cloud Console
3. Paste your API key below

Note: Veo 3 is Google's advanced video generation model.
""",
    example_use_cases=[
        "Generate video content from descriptions",
        "Create animated explainer videos",
        "Produce marketing video clips",
        "Generate motion graphics"
    ],
    tags=["video", "generation", "google", "gemini", "veo"]
)


# Register on import
ToolTemplateRegistry.register(VIDEO_GEMINI_VEO3_TEMPLATE)

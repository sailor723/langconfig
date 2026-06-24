# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
IMAGE_OPENAI_DALLE3_TEMPLATE - Image category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


IMAGE_OPENAI_DALLE3_TEMPLATE = ToolTemplate(
    template_id="image_openai_dalle3",
    name="DALL-E 3 Image Generator",
    description="Generate images using OpenAI's DALL-E 3 model",
    category="image_video",
    tool_type=ToolType.IMAGE_VIDEO,
    icon="🎨",
    priority=85,
    is_featured=True,
    config_template={
        "tool_type": "image_video",
        "template_type": "image_openai_dalle3",
        "implementation_config": {
            "provider": "openai",
            "model": "dall-e-3",
            "api_key": "",  # USER MUST PROVIDE
            "size": "1024x1024",
            "quality": "standard",
            "style": "vivid",
            "timeout": 60
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Image generation prompt"
            },
            "size": {
                "type": "string",
                "description": "Image size: 1024x1024, 1792x1024, or 1024x1792",
                "default": "1024x1024"
            },
            "quality": {
                "type": "string",
                "description": "Image quality: standard or hd",
                "default": "standard"
            }
        },
        "required": ["prompt"]
    },
    required_user_fields=["api_key"],
    setup_instructions="""
1. Get your OpenAI API key from https://platform.openai.com/api-keys
2. Ensure you have DALL-E 3 access enabled
3. Paste your API key below (it will be encrypted)

Note: DALL-E 3 generates one image per request. Costs vary by size and quality.
""",
    example_use_cases=[
        "Generate marketing visuals from product descriptions",
        "Create illustrations for blog posts",
        "Visualize concepts and ideas",
        "Generate placeholder images",
        "Create custom artwork based on text"
    ],
    tags=["image", "generation", "openai", "dalle", "art"]
)


# Register on import
ToolTemplateRegistry.register(IMAGE_OPENAI_DALLE3_TEMPLATE)

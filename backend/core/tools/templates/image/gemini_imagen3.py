# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
IMAGE_GEMINI_IMAGEN3_TEMPLATE - Image category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


IMAGE_GEMINI_IMAGEN3_TEMPLATE = ToolTemplate(
    template_id="image_gemini_imagen3",
    name="Imagen 3 Image Generator",
    description="Generate images using Google's Imagen 3 model",
    category="image_video",
    tool_type=ToolType.IMAGE_VIDEO,
    icon="🖼️",
    priority=75,
    is_featured=False,
    config_template={
        "tool_type": "image_video",
        "template_type": "image_gemini_imagen3",
        "implementation_config": {
            "provider": "google",
            "model": "imagen-3",
            "aspect_ratio": "1:1",
            "num_images": 1,
            "safety_filter_level": "block_most",
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
            "aspect_ratio": {
                "type": "string",
                "description": "Aspect ratio: 1:1, 16:9, 9:16, 4:3, 3:4",
                "default": "1:1"
            }
        },
        "required": ["prompt"]
    },
    required_user_fields=[],
    setup_instructions="""
🖼️ **Imagen 3**

API Key: Configured in Settings page

Note: Imagen 3 offers high-quality photorealistic and artistic image generation.
""",
    example_use_cases=[
        "Generate photorealistic product images",
        "Create artistic interpretations",
        "Produce marketing visuals",
        "Generate concept art"
    ],
    tags=["image", "generation", "google", "gemini", "imagen"]
)


# Register on import
ToolTemplateRegistry.register(IMAGE_GEMINI_IMAGEN3_TEMPLATE)

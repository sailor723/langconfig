# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
IMAGE_GEMINI_NANO_BANANA_TEMPLATE - Image category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


IMAGE_GEMINI_NANO_BANANA_TEMPLATE = ToolTemplate(
    template_id="image_gemini_nano_banana",
    name="Nano Banana Pro (Gemini 3 Pro Image)",
    description="High-quality AI image generation using Gemini 3 Pro Image - Google's best model with 2K/4K output, text rendering, and character consistency",
    category="image_video",
    tool_type=ToolType.IMAGE_VIDEO,
    icon="🍌",
    priority=90,
    is_featured=True,
    config_template={
        "tool_type": "image_video",
        "template_type": "image_gemini_nano_banana",
        "implementation_config": {
            "provider": "google",
            "model": "gemini-3-pro-image-preview",
            "aspect_ratio": "1:1",
            "number_of_images": 1,
            "safety_filter_level": "block_some",
            "timeout": 45
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed image generation prompt"
            },
            "negative_prompt": {
                "type": "string",
                "description": "Elements to avoid in the image (optional)",
                "default": ""
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Image aspect ratio: 1:1, 16:9, 9:16, 4:3, or 3:4",
                "default": "1:1"
            },
            "style": {
                "type": "string",
                "description": "Image style: photorealistic, artistic, anime, illustration, or default",
                "default": "default"
            }
        },
        "required": ["prompt"]
    },
    required_user_fields=[],
    setup_instructions="""
🍌 **Nano Banana (Gemini 2.5 Flash Image)**

API Key: Configured in Settings page

**Features:**
- Ultra-fast image generation (2-5 seconds)
- Multimodal inputs (text + reference images)
- Character consistency across generations
- Image editing (inpainting, outpainting, blending)
- High-resolution output with upscaling
- Natural scene reconstruction

💰 **Pricing:**
~$0.01-0.03 per image (significantly cheaper than DALL-E 3)

✨ **Best For:**
- Rapid prototyping and iteration
- Batch image generation
- Character-consistent artwork
- Marketing visuals & social media graphics
- Illustrated blog posts and articles
- Image blending and composition
""",
    example_use_cases=[
        "Generate marketing visuals from research reports",
        "Create consistent character artwork for stories",
        "Produce illustrations for blog posts and articles",
        "Generate social media graphics in bulk",
        "Create mockups and prototypes with visual elements",
        "Blend multiple images into cohesive compositions",
        "Add visual elements to automated content"
    ],
    tags=["image", "generation", "google", "gemini", "nano-banana", "fast", "featured", "workflow"]
)


# Register on import
ToolTemplateRegistry.register(IMAGE_GEMINI_NANO_BANANA_TEMPLATE)

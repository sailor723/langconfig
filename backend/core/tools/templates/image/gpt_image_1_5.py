# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
IMAGE_OPENAI_GPT_IMAGE_1_5_TEMPLATE - Image category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


IMAGE_OPENAI_GPT_IMAGE_1_5_TEMPLATE = ToolTemplate(
    template_id="image_openai_gpt_image_1_5",
    name="GPT-Image-1.5 Generator",
    description="Generate and edit images using OpenAI's latest GPT-Image-1.5 model (December 2025) - 4x faster, enhanced instruction following, precise editing, and legible text rendering",
    category="image_video",
    tool_type=ToolType.IMAGE_VIDEO,
    icon="🖼️",
    priority=88,
    is_featured=True,
    config_template={
        "tool_type": "image_video",
        "template_type": "image_openai_gpt_image_1_5",
        "implementation_config": {
            "provider": "openai",
            "model": "gpt-image-1.5",
            "api_key": "",  # USER MUST PROVIDE
            "size": "1024x1024",
            "quality": "high",
            "background": "auto",
            "moderation": "auto",
            "output_format": "png",
            "timeout": 90
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed image generation prompt. GPT-Image-1.5 excels at instruction following, precise editing, and rendering legible text in images."
            },
            "size": {
                "type": "string",
                "description": "Image size: 1024x1024 (square), 1536x1024 (landscape), 1024x1536 (portrait), or auto",
                "default": "1024x1024"
            },
            "quality": {
                "type": "string",
                "description": "Image quality: low (faster, less detail), medium (balanced), high (maximum detail)",
                "enum": ["low", "medium", "high"],
                "default": "high"
            },
            "background": {
                "type": "string",
                "description": "Background type: transparent, opaque, or auto (model decides)",
                "enum": ["transparent", "opaque", "auto"],
                "default": "auto"
            },
            "n": {
                "type": "integer",
                "description": "Number of images to generate (1-4)",
                "default": 1,
                "minimum": 1,
                "maximum": 4
            }
        },
        "required": ["prompt"]
    },
    required_user_fields=["api_key"],
    setup_instructions="""
🖼️ **GPT-Image-1.5**

OpenAI's latest image generation model, released December 16, 2025. 4x faster than previous versions.

**Setup:**
1. Get your OpenAI API key from https://platform.openai.com/api-keys
2. Ensure your account has access to gpt-image-1.5
3. Paste your API key below

**Key Features:**
- ⚡ **4x Faster**: Significantly faster generation than previous models
- 🎯 **Enhanced Instruction Following**: Better understanding of prompts
- ✏️ **Precise Editing**: Add, change, or remove objects, styles, and clothing
- 🔤 **Legible Text**: Improved text rendering in generated images
- 🎨 **Style Control**: More accurate style and clothing modification

**Quality Levels:**
- `low`: Faster generation, lower detail
- `medium`: Balanced speed and quality
- `high`: Maximum detail, best for final outputs

**Pricing:**
~$0.04 per image (1024x1024, high quality)

**Best For:**
- Marketing materials with accurate text/logos
- Product mockups and designs
- Illustrations requiring precise details
- Social media graphics with embedded text
""",
    example_use_cases=[
        "Generate marketing materials with accurate text and logos",
        "Create product mockups with realistic branding",
        "Design social media graphics with embedded text",
        "Illustrate concepts with precise contextual accuracy",
        "Generate images with transparent backgrounds for compositing",
        "Create detailed illustrations for documentation"
    ],
    tags=["image", "generation", "openai", "gpt-image-1.5", "fast", "text-rendering", "editing", "featured"]
)


# Register on import
ToolTemplateRegistry.register(IMAGE_OPENAI_GPT_IMAGE_1_5_TEMPLATE)

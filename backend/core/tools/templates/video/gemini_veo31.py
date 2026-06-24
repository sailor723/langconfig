# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
VIDEO_GEMINI_VEO31_TEMPLATE - Video category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


VIDEO_GEMINI_VEO31_TEMPLATE = ToolTemplate(
    template_id="video_gemini_veo31",
    name="Veo 3.1 Fast Video Generator",
    description="Generate videos using Google's Veo 3.1 Fast model. Supports text-to-video, image-to-video animation, and video continuation/extension.",
    category="image_video",
    tool_type=ToolType.IMAGE_VIDEO,
    icon="🎬",
    priority=85,
    is_featured=True,
    config_template={
        "tool_type": "image_video",
        "template_type": "video_gemini_veo31",
        "implementation_config": {
            "provider": "google",
            "model": "veo-3.1-fast-generate-preview",
            "duration": 8,
            "resolution": "720p",
            "fps": 24,
            "aspect_ratio": "16:9",
            "generate_audio": True,
            "timeout": 180
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text description of the video to generate, including desired actions, scenes, and style"
            },
            "image_url": {
                "type": "string",
                "description": "Optional: URL or base64 data URI of an image to animate (image-to-video mode)",
                "default": ""
            },
            "video_url": {
                "type": "string",
                "description": "Optional: URL of a previously generated Veo video to extend/continue",
                "default": ""
            },
            "duration": {
                "type": "integer",
                "description": "Video duration in seconds: 4, 6, or 8",
                "default": 8
            },
            "aspect_ratio": {
                "type": "string",
                "description": "Video aspect ratio: 16:9 (landscape) or 9:16 (portrait)",
                "default": "16:9"
            },
            "negative_prompt": {
                "type": "string",
                "description": "Optional: Elements or styles to avoid in the video",
                "default": ""
            }
        },
        "required": ["prompt"]
    },
    required_user_fields=[],
    setup_instructions="""
🎬 **Veo 3.1 Fast Video Generator**

API Key: Configured in Settings page (uses GOOGLE_API_KEY)

**Three Generation Modes:**

1. **Text-to-Video**: Just provide a prompt
   ```json
   {"prompt": "A cat playing with yarn in a sunlit room"}
   ```

2. **Image-to-Video**: Animate an existing image
   ```json
   {
     "prompt": "The cat starts walking towards the camera",
     "image_url": "https://example.com/cat.jpg"
   }
   ```

3. **Video Extension**: Continue an existing Veo video
   ```json
   {
     "prompt": "The cat jumps onto the couch",
     "video_url": "https://storage.googleapis.com/your-bucket/previous-video.mp4"
   }
   ```

**Features:**
- Fast generation (Veo 3.1 Fast variant)
- Audio generation included
- Up to 8 seconds per clip
- Chain videos for up to 141 seconds total
- 720p resolution, 16:9 or 9:16 aspect ratio

**Best For:**
- Marketing videos and social media content
- Product animations
- Animated storytelling
- Extending video narratives
""",
    example_use_cases=[
        "Generate marketing video clips from product descriptions",
        "Animate product photos into dynamic video content",
        "Create video continuations for storytelling",
        "Produce social media video content",
        "Generate explainer video segments",
        "Chain multiple clips into longer narratives"
    ],
    tags=["video", "generation", "google", "veo", "fast", "image-to-video", "video-extension", "featured", "workflow"]
)


# Register on import
ToolTemplateRegistry.register(VIDEO_GEMINI_VEO31_TEMPLATE)

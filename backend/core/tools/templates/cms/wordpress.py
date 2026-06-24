# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
CMS_WORDPRESS_TEMPLATE - Cms category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


CMS_WORDPRESS_TEMPLATE = ToolTemplate(
    template_id="cms_wordpress",
    name="WordPress Publisher",
    description="Create, update, and manage WordPress posts, pages, and media",
    category="cms",
    tool_type=ToolType.API,
    icon="📝",
    priority=92,
    is_featured=True,
    config_template={
        "tool_type": "api",
        "template_type": "cms_wordpress",
        "implementation_config": {
            "provider": "wordpress",
            "site_url": "",  # USER MUST PROVIDE: https://yoursite.com
            "username": "",  # USER MUST PROVIDE: WordPress username
            "app_password": "",  # USER MUST PROVIDE: Application password (NOT regular password)
            "default_author_id": 1,
            "default_status": "draft",  # draft, publish, pending, private
            "default_category": "Uncategorized",
            "timeout": 30
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action to perform: create_post, update_post, publish_post, delete_post, upload_media",
                "enum": ["create_post", "update_post", "publish_post", "delete_post", "upload_media", "get_post"],
                "default": "create_post"
            },
            "title": {
                "type": "string",
                "description": "Post/page title"
            },
            "content": {
                "type": "string",
                "description": "Post/page content (HTML or plain text)"
            },
            "excerpt": {
                "type": "string",
                "description": "Post excerpt/summary (optional)",
                "default": ""
            },
            "status": {
                "type": "string",
                "description": "Post status: draft, publish, pending, private",
                "enum": ["draft", "publish", "pending", "private"],
                "default": "draft"
            },
            "post_id": {
                "type": "integer",
                "description": "Post ID (required for update/publish/delete actions)"
            },
            "categories": {
                "type": "array",
                "description": "Category names or IDs",
                "items": {"type": "string"},
                "default": []
            },
            "tags": {
                "type": "array",
                "description": "Tag names",
                "items": {"type": "string"},
                "default": []
            },
            "featured_image_url": {
                "type": "string",
                "description": "URL of image to set as featured image",
                "default": ""
            },
            "author_id": {
                "type": "integer",
                "description": "Author ID (optional, uses default if not specified)"
            }
        },
        "required": ["action"]
    },
    required_user_fields=["site_url", "username", "app_password"],
    setup_instructions="""
WORDPRESS REST API AUTHENTICATION:

1. **Create an Application Password** (WordPress 5.6+):
   - Log in to your WordPress admin dashboard
   - Go to Users → Profile
   - Scroll down to "Application Passwords"
   - Enter a name (e.g., "LangConfig Bot")
   - Click "Add New Application Password"
   - COPY THE PASSWORD IMMEDIATELY (shown only once!)
   - Paste it into the 'App Password' field below

2. **Site URL**:
   - Enter your WordPress site URL (e.g., https://yoursite.com)
   - Do NOT include /wp-admin or /wp-json

3. **Username**:
   - Your WordPress username (the one you log in with)

IMPORTANT NOTES:
- Application Passwords are MORE SECURE than your regular password
- They can be revoked anytime from your WordPress profile
- Requires WordPress 5.6+ with REST API enabled
- HTTPS is recommended for security

TESTING YOUR SETUP:
After configuration, test with:
{
  "action": "create_post",
  "title": "Test Post",
  "content": "This is a test post from LangConfig",
  "status": "draft"
}

COMMON ACTIONS:

Create Draft:
{
  "action": "create_post",
  "title": "My Article",
  "content": "<p>Article content here</p>",
  "status": "draft",
  "categories": ["News"],
  "tags": ["AI", "Automation"]
}

Publish Draft:
{
  "action": "publish_post",
  "post_id": 123
}

Update Post:
{
  "action": "update_post",
  "post_id": 123,
  "title": "Updated Title",
  "content": "<p>Updated content</p>"
}

Delete Post:
{
  "action": "delete_post",
  "post_id": 123
}
""",
    example_use_cases=[
        "Generate blog posts with AI and save as WordPress drafts",
        "Auto-publish scheduled content from workflows",
        "Update existing posts with new information",
        "Create documentation pages automatically",
        "Bulk import content from external sources",
        "Generate and publish social media round-ups"
    ],
    tags=["wordpress", "cms", "publishing", "blog", "content-management"]
)


# Register on import
ToolTemplateRegistry.register(CMS_WORDPRESS_TEMPLATE)

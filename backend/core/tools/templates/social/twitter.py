# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
SOCIAL_TWITTER_TEMPLATE - Social category tool template.

Extracted from templates.py on 2026-06-24.
"""
from typing import Any
from models.custom_tool import ToolType
from core.tools.templates import ToolTemplate, ToolTemplateRegistry


SOCIAL_TWITTER_TEMPLATE = ToolTemplate(
    template_id="social_twitter",
    name="Twitter/X Integration",
    description="Read and post tweets using Twitter API v2 (supports free tier)",
    category="cms",
    tool_type=ToolType.API,
    icon="social_twitter",
    priority=91,
    is_featured=True,
    config_template={
        "tool_type": "api",
        "template_type": "social_twitter",
        "implementation_config": {
            "provider": "twitter",
            "api_key": "",  # USER MUST PROVIDE: Twitter API Key
            "api_secret": "",  # USER MUST PROVIDE: Twitter API Secret
            "access_token": "",  # USER MUST PROVIDE: Access Token
            "access_token_secret": "",  # USER MUST PROVIDE: Access Token Secret
            "bearer_token": "",  # USER MUST PROVIDE (Alternative): Bearer Token (for read-only)
            "api_version": "v2",
            "timeout": 30
        }
    },
    input_schema_template={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action to perform: post_tweet, read_timeline, search_tweets, get_user, delete_tweet",
                "enum": ["post_tweet", "read_timeline", "search_tweets", "get_user", "delete_tweet"],
                "default": "post_tweet"
            },
            "text": {
                "type": "string",
                "description": "Tweet text content (max 280 characters for post_tweet)"
            },
            "tweet_id": {
                "type": "string",
                "description": "Tweet ID (required for delete_tweet)"
            },
            "username": {
                "type": "string",
                "description": "Twitter username (for get_user, read_timeline actions)"
            },
            "query": {
                "type": "string",
                "description": "Search query (for search_tweets action)"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 10, max: 100 for free tier)",
                "default": 10
            },
            "reply_to_tweet_id": {
                "type": "string",
                "description": "Tweet ID to reply to (optional, for post_tweet)"
            },
            "media_url": {
                "type": "string",
                "description": "URL of media to attach (optional, for post_tweet)"
            }
        },
        "required": ["action"]
    },
    required_user_fields=["api_key", "api_secret", "access_token", "access_token_secret"],
    setup_instructions="""
TWITTER API V2 SETUP (FREE TIER):

1. **Create a Twitter Developer Account**:
   - Go to https://developer.twitter.com/
   - Click "Sign up" and complete the application
   - Select "Free" tier (includes 1,500 tweets/month post limit)

2. **Create a New App**:
   - Go to the Developer Portal
   - Navigate to "Projects & Apps"
   - Click "Create App"
   - Give your app a name

3. **Get API Credentials**:
   - In your app settings, go to "Keys and tokens"
   - Generate/copy the following:
     * API Key (Consumer Key)
     * API Secret (Consumer Secret)
     * Access Token
     * Access Token Secret
   - Alternatively, for read-only: Use Bearer Token

4. **Set App Permissions**:
   - In app settings → "User authentication settings"
   - Set permissions: "Read and Write" (for posting)
   - Save changes

5. **Rate Limits (Free Tier)**:
   - Post tweets: 1,500 tweets/month
   - Read tweets: 500,000 tweets/month
   - User lookups: 500,000 requests/month

IMPORTANT NOTES:
- Free tier has monthly limits, not per-minute
- Tweets must be ≤280 characters
- Media uploads require additional setup
- For read-only operations, Bearer Token alone is sufficient
""",
    example_use_cases=[
        "Post automated updates and announcements to Twitter",
        "Monitor mentions and replies from your timeline",
        "Search for tweets about specific topics or hashtags",
        "Get user profile information and follower counts",
        "Reply to tweets programmatically",
        "Schedule and post content to Twitter automatically"
    ],
    tags=["social", "twitter", "x", "posting", "social-media", "publishing"]
)


# Register on import
ToolTemplateRegistry.register(SOCIAL_TWITTER_TEMPLATE)

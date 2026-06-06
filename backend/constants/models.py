# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Model constants for LangConfig
Updated December 16, 2025
"""
from enum import Enum


class ModelChoice(str, Enum):
    """Available AI models - Updated Dec 2025"""

    # OpenAI - GPT-5 Series (commented out, no API key configured)
    # GPT_5_2 = "gpt-5.2"
    # GPT_5_1 = "gpt-5.1"
    # GPT_4O = "gpt-4o"
    # GPT_4O_MINI = "gpt-4o-mini"

    # Google - Gemini 3 (Current)
    GEMINI_3_PRO = "gemini-3-pro-preview"

    # Google - Gemini 2.5
    GEMINI_2_FLASH = "gemini-2.0-flash"
    GEMINI_25_FLASH = "gemini-2.5-flash"
    GEMINI_25_FLASH_LITE = "gemini-2.5-flash-lite"

    # DeepSeek
    DEEPSEEK_CHAT = "deepseek-chat"
    DEEPSEEK_REASONER = "deepseek-reasoner"

    # GLM (Zhipu AI)
    GLM_4 = "glm-4"
    GLM_4V = "glm-4v"
    GLM_4_FLASH = "glm-4-flash"

    # MiniMax
    MINIMAX_T1 = "minimax-t1"
    MINIMAX_M3 = "minimax-m3"


# Default model
DEFAULT_MODEL = ModelChoice.DEEPSEEK_CHAT
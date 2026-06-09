"""
Lightweight LLM-based metadata extraction from chat messages.

Uses LangChain's init_chat_model with structured output (Pydantic)
to extract user metadata. Works with DeepSeek (via langchain-deepseek).
"""
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExtractedMetadata(BaseModel):
    """Structured metadata extracted from a user message."""
    name: Optional[str] = Field(None, description="The user's name if they introduced themselves")
    preferences: List[str] = Field(default_factory=list, description="Things the user likes")
    topics_mentioned: List[str] = Field(default_factory=list, description="Topics mentioned")
    has_new_info: bool = Field(default=False, description="Whether this message contained new personal info")


EXTRACTION_PROMPT = """Extract personal information from this user message.

- name: The user's name if introduced (e.g. "hi am X", "I'm X", "my name is X")
- preferences: Things the user likes, enjoys, or their favorites
- has_new_info: true if ANY personal information was found in this message

Message: {message}"""


async def extract_metadata_from_message(
    message: str,
    llm=None,
    model_name: str = "deepseek-chat",
) -> ExtractedMetadata:
    """Extract user metadata from a single message using LLM structured output."""
    if not message or not message.strip():
        return ExtractedMetadata()

    try:
        if llm is None:
            from langchain.chat_models import init_chat_model

            llm = init_chat_model(
                model=model_name,
                model_provider="deepseek",
                temperature=0,
            )

        structured_llm = llm.with_structured_output(ExtractedMetadata)
        return await structured_llm.ainvoke(
            EXTRACTION_PROMPT.format(message=message.strip())
        )

    except Exception as e:
        logger.warning(f"LLM metadata extraction failed: {e}")
        return ExtractedMetadata()

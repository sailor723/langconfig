"""Test DeepSeek with_structured_output using init_chat_model."""
import asyncio
from pydantic import BaseModel, Field


class ExtractedMetadata(BaseModel):
    name: str | None = Field(None, description="User's name")
    preferences: list[str] = Field(default_factory=list)
    topics_mentioned: list[str] = Field(default_factory=list)
    has_new_info: bool = Field(default=False)


async def test():
    from langchain.chat_models import init_chat_model

    llm = init_chat_model(
        model="deepseek-chat",
        model_provider="deepseek",
        temperature=0,
    )

    # Test 1: with_structured_output
    structured = llm.with_structured_output(ExtractedMetadata)
    result = await structured.ainvoke("hi am weiping")
    print(f"Test 1 - Name introduction:")
    print(f"  Result: {result}")
    print(f"  Name: {result.name}, has_new_info: {result.has_new_info}")

    # Test 2: Preference
    result2 = await structured.ainvoke("I like blue color")
    print(f"\nTest 2 - Preference:")
    print(f"  Result: {result2}")
    print(f"  Preferences: {result2.preferences}, has_new_info: {result2.has_new_info}")

    # Test 3: No info
    result3 = await structured.ainvoke("how are you")
    print(f"\nTest 3 - No info:")
    print(f"  Result: {result3}")
    print(f"  has_new_info: {result3.has_new_info}")


asyncio.run(test())

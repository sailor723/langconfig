"""
Test: init_chat_model works for all model providers used in the app.

This test verifies that LangChain's init_chat_model can replace ChatOpenAI
for DeepSeek, OpenAI, and other providers. Tests configuration only (no API calls).
"""
import pytest


class TestInitChatModel:
    """Test that init_chat_model can instantiate LLMs for all providers."""

    def test_init_chat_model_importable(self):
        """Verify init_chat_model is available."""
        from langchain.chat_models import init_chat_model
        assert init_chat_model is not None

    def test_init_chat_model_deepseek(self):
        """Test init_chat_model with deepseek provider (langchain-deepseek)."""
        from langchain.chat_models import init_chat_model

        llm = init_chat_model(
            model="deepseek-chat",
            model_provider="deepseek",
            temperature=0,
        )
        assert llm is not None
        assert llm.model == "deepseek-chat"

    def test_init_chat_model_openai(self):
        """Test init_chat_model with OpenAI provider (config only, mock api_key)."""
        from langchain.chat_models import init_chat_model

        llm = init_chat_model(
            model="gpt-4o-mini",
            model_provider="openai",
            temperature=0,
            api_key="sk-test",
        )
        assert llm is not None
        assert llm.model == "gpt-4o-mini"

    def test_init_chat_model_with_api_key(self):
        """Test passing api_key as init_kwargs works."""
        from langchain.chat_models import init_chat_model

        # Should accept api_key as direct kwarg
        llm = init_chat_model(
            model="deepseek-chat",
            model_provider="deepseek",
            temperature=0,
            api_key="test-key",
        )
        assert llm is not None

    def test_init_chat_model_deepseek_structured_output(self):
        """Test deepseek + structured output (used by metadata_extractor)."""
        from langchain.chat_models import init_chat_model
        from pydantic import BaseModel, Field

        class TestSchema(BaseModel):
            name: str | None = Field(None)

        llm = init_chat_model(
            model="deepseek-chat",
            model_provider="deepseek",
            temperature=0,
        )
        structured = llm.with_structured_output(TestSchema)
        assert structured is not None

    def test_init_chat_model_with_max_tokens(self):
        """Test passing max_tokens and streaming kwargs."""
        from langchain.chat_models import init_chat_model

        llm = init_chat_model(
            model="deepseek-chat",
            model_provider="deepseek",
            temperature=0.7,
            max_tokens=4096,
            streaming=True,
        )
        assert llm is not None
        # These params might be set on the underlying model
        assert llm.temperature == 0.7

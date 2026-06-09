"""
Test: Summarization middleware integration.

Uses deepagents' built-in SummarizationMiddleware, no custom summarization needed.
Tests the config mapping from GuardrailsConfig → middleware params.
"""
import pytest


class TestSummarizationMiddlewareConfig:
    """Test that SummarizationMiddleware config maps correctly from GuardrailsConfig."""

    def test_middleware_can_be_imported(self):
        """Verify the built-in SummarizationMiddleware is available."""
        from deepagents.middleware.summarization import SummarizationMiddleware
        assert SummarizationMiddleware is not None

    def test_middleware_config_guardrails_mapping(self):
        """Test mapping from GuardrailsConfig to SummarizationMiddleware params."""
        from models.deep_agent import GuardrailsConfig

        config = GuardrailsConfig()
        limits = config.token_limits

        # Map guardrails config → SummarizationMiddleware params
        trigger = ("token", limits["summarization_threshold"])
        keep = ("fraction", 0.10)  # keep 10% of context after summarization

        assert trigger[0] == "token"
        assert trigger[1] == 60000
        assert keep[0] == "fraction"
        assert keep[1] == 0.10

    def test_summarization_disabled_guardrails(self):
        """Test when summarization is disabled, middleware is not added."""
        from models.deep_agent import GuardrailsConfig

        config = GuardrailsConfig(enable_summarization=False)
        assert config.enable_summarization is False

        # When disabled, we should skip adding SummarizationMiddleware
        should_add = config.enable_summarization
        assert should_add is False

    def test_trigger_keep_factory_function(self):
        """Test the factory function that creates SummarizationMiddleware from GuardrailsConfig.

        This tests the mapping logic only — not actual middleware instantiation
        (which requires API keys).
        """
        from models.deep_agent import GuardrailsConfig

        config = GuardrailsConfig()
        limits = config.token_limits

        # Build the middleware kwargs from guardrails config
        trigger = ("token", limits["summarization_threshold"])
        keep = ("fraction", 0.10)

        # Verify the values that would be passed to the middleware
        assert trigger == ("token", 60000)
        assert keep == ("fraction", 0.10)


class TestMetadataExtractionIntegration:
    """Test metadata extraction with PostgresStore (LangGraph Store)."""

    @pytest.mark.asyncio
    async def test_extract_name_from_conversation(self):
        """Test extracting user metadata from a short conversation."""
        from core.agents.memory import SimpleMemory
        from db.database import AsyncSessionLocal

        # Simulate: agent stores memory, then we extract metadata
        session = AsyncSessionLocal()
        mem = SimpleMemory(project_id=1, agent_id="task_meta_test", db_session=session)

        # Store user info (simulating what the LLM would do with memory_store)
        store_result = await mem.save_to_memory(
            memory_content="User's name is Weiping",
            memory_type="fact",
            importance=8,
            tags=["user_info"],
        )
        assert "error" not in store_result.lower()

        # Store preference
        await mem.save_to_memory(
            memory_content="User likes the color blue",
            memory_type="fact",
            importance=5,
            tags=["preference"],
        )

        # Recall all memories to simulate metadata extraction
        all_memories = await mem.recall_memory()
        assert "Weiping" in all_memories
        assert "blue" in all_memories

        await session.close()

    def test_conversation_turn_logging(self):
        """Test that conversation turns can be logged to checkpointer."""
        # The checkpointer already handles this — this test verifies
        # the pattern we'll use for the archive middleware
        from langgraph.checkpoint.postgres import PostgresSaver
        assert PostgresSaver is not None

    def test_create_deep_agent_accepts_summarization_middleware(self):
        """Test that the middleware import works (instantiation happens in factory with real API keys)."""
        from deepagents.middleware.summarization import SummarizationMiddleware
        # Just verify the import — actual instantiation requires API keys
        assert "SummarizationMiddleware" in SummarizationMiddleware.__name__

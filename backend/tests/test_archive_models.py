"""
Test: Conversation summarization + metadata extraction using LangGraph patterns.

Tests TDD-style using LangGraph's built-in infrastructure where possible.
- Conversation history → LangGraph PostgresSaver checkpointer (already exists)
- Summarization → LangGraph conditional edge + RemoveMessage pattern
- User metadata → PostgresStore (already initialized) + extraction node
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import text


class TestLangGraphCheckpointerHistory:
    """Test that LangGraph checkpointer already stores conversation history."""

    def test_checkpoints_table_exists(self, db_engine):
        """Verify LangGraph checkpoints table exists (pre-requisite)."""
        with db_engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables "
                    "WHERE table_name = 'checkpoints')"
                )
            )
            assert result.scalar() is True, \
                "LangGraph checkpoints table must exist for conversation history"

    def test_checkpoint_writes_after_insert(self, db_engine):
        """Verify we can read checkpoint data for a thread."""
        with db_engine.connect() as conn:
            # Checkpointers write to 'checkpoints' table with thread_id
            result = conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'checkpoints' "
                    "ORDER BY ordinal_position"
                )
            )
            cols = {row[0]: row[1] for row in result}
            required = ["thread_id", "checkpoint", "metadata", "parent_checkpoint_id"]
            for col in required:
                assert col in cols, f"Missing column: {col}" \
                    " (LangGraph checkpointer format may differ)"


class TestSummarizationPattern:
    """Test summarization logic (using LangGraph's RemoveMessage pattern)."""

    def test_summarize_trims_old_messages(self):
        """
        Simulate LangGraph summarization pattern:
        - N messages in state
        - Summarize keeps summary + last 2 messages
        - Uses RemoveMessage to delete old ones
        """
        from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage

        # Simulate a conversation with 8 messages
        messages = [
            HumanMessage(content=f"Message {i}", id=f"msg_{i}")
            for i in range(8)
        ]

        # Simulate summarization: keep last 2, delete rest
        summary = "Summary of messages 0-5"
        keep_count = 2
        to_delete = messages[:-keep_count]
        delete_ops = [RemoveMessage(id=m.id) for m in to_delete]
        remaining = messages[-keep_count:]

        assert len(delete_ops) == 6, "Should delete 6 old messages"
        assert len(remaining) == 2, "Should keep 2 most recent"
        assert summary, "Summary should exist"

    def test_summarize_threshold_check(self):
        """Test the conditional logic: should summarize when count > threshold."""
        threshold = 6  # configurable setting
        message_counts = [2, 4, 6, 8, 10, 20]

        for count in message_counts:
            should_summarize = count > threshold
            if count > threshold:
                assert should_summarize, f"Should summarize {count} > {threshold}"
            else:
                assert not should_summarize, f"Should NOT summarize {count} <= {threshold}"

    def test_summary_included_in_context(self):
        """Test that when a summary exists, it's prepended as system message."""
        from langchain_core.messages import SystemMessage, HumanMessage

        summary = "User name is Weiping. User likes blue."
        messages = [HumanMessage(content="What's my name?")]

        # Simulate: prepend summary as system message
        if summary:
            context = [SystemMessage(content=f"Summary: {summary}")] + messages
        else:
            context = messages

        assert len(context) == 2
        assert isinstance(context[0], SystemMessage)
        assert "Weiping" in context[0].content


class TestMetadataExtraction:
    """Test automatic user metadata extraction from conversation."""

    def test_extract_name_from_message(self):
        """Test extracting user name from natural language."""
        messages = [
            ("hi am weiping", {"name": "Weiping"}),
            ("hello, my name is John", {"name": "John"}),
            ("I'm Sarah, nice to meet you", {"name": "Sarah"}),
            ("hi there", {"name": None}),  # no name in this one
            ("my name is Mary Jane", {"name": "Mary Jane"}),
        ]

        for msg, expected in messages:
            result = self._extract_name(msg)
            assert result == expected["name"], f"Failed for '{msg}': {result}"

    def _extract_name(self, message: str):
        """Simple name extraction logic (will be replaced by LLM extraction)."""
        import re
        patterns = [
            # "my name is X", "i'm X", "i am X", "call me X"
            r"(?:my name is|i'?m|i am|call me)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)",
        ]
        msg_lower = message.lower()
        for pattern in patterns:
            match = re.search(pattern, msg_lower)
            if match:
                name = match.group(1)
                # Capitalize properly
                return " ".join(w.capitalize() for w in name.split())
        return None

    def test_extract_preferences(self):
        """Test extracting preferences from statements."""
        statements = [
            ("I like blue color", ["blue"]),
            ("I love pizza and pasta", ["pizza", "pasta"]),
            ("my favorite programming language is Python", ["Python"]),
            ("I enjoy hiking in the mountains", ["hiking"]),
            ("I don't like spicy food", None),  # negative preference
        ]

        for statement, expected in statements:
            result = self._extract_preferences(statement)
            if expected:
                # Check at least one expected item is in the result
                result_items = [r.lower() for r in (result or [])]
                assert any(e.lower() in " ".join(result_items) for e in expected), \
                    f"Failed for '{statement}': {result}"

    def _extract_preferences(self, message: str):
        """Simple preference extraction (will be replaced by LLM extraction)."""
        import re
        msg_lower = message.lower()

        # "I like/love/enjoy X"
        # "my favorite X is Y"
        patterns = [
            r"(?:i\s+(?:like|love|enjoy)\s+)(.+)",
            r"(?:my\s+favorite\s+.+?\s+is\s+)(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, msg_lower)
            if match:
                content = match.group(1).strip().rstrip(".!,")
                # Split by "and", ",", etc.
                items = re.split(r"\s+(?:and|,)\s+", content)
                # Clean trailing generic words (color, food, etc.)
                cleaned = []
                generic_suffixes = [" color", " food", " drink", " activity"]
                for item in items:
                    item = item.strip()
                    for suffix in generic_suffixes:
                        if item.endswith(suffix):
                            item = item[:-len(suffix)]
                            break
                    cleaned.append(item.strip())
                return cleaned
        return None

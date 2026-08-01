import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from core.workflows.executor import SimpleWorkflowExecutor


def test_llm_node_uses_shared_model_resolver():
    """LLM_NODE must resolve models through agent_utils, not ChatOpenAI directly."""
    executor = SimpleWorkflowExecutor()
    node_executor = executor._create_llm_node_executor("llm-1", {
        "config": {
            "model": "deepseek-chat",
            "temperature": 0.4,
            "system_prompt": "Be concise.",
            "max_tokens": 128,
        }
    })

    fake_llm = AsyncMock()
    fake_llm.ainvoke.return_value = AIMessage(content="ok")

    async def run():
        with patch(
            "services.agent_utils.resolve_model",
            new=AsyncMock(return_value=fake_llm),
        ) as resolve_mock:
            result = await node_executor({"query": "hello", "messages": []}, None)
            resolve_mock.assert_awaited_once()
            assert resolve_mock.await_args.args == (
                "deepseek-chat",
                0.4,
                128,
                {
                    "model": "deepseek-chat",
                    "temperature": 0.4,
                    "system_prompt": "Be concise.",
                    "max_tokens": 128,
                },
            )
            return result

    result = asyncio.run(run())
    assert result["agent_type"] == "LLM_NODE"
    assert result["messages"][0].content == "ok"

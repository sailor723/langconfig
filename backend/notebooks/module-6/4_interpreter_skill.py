import os
from pathlib import Path
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langchain_quickjs import CodeInterpreterMiddleware
from langgraph.checkpoint.memory import MemorySaver

root_dir = Path(__file__).parent.resolve()
skills_dir = root_dir / "skills"

model = init_chat_model(
    "deepseek-chat",
    temperature=0.5,
    timeout=600,
    max_tokens=25000,
    streaming=True,
)

checkpointer = MemorySaver()
backend = FilesystemBackend(root_dir=str(root_dir))

agent = create_deep_agent(
    model=model,
    backend=backend,
    skills=[str(skills_dir)],
    checkpointer=checkpointer,
    middleware=[CodeInterpreterMiddleware(skills_backend=backend)],
)

print("=" * 60)
print("  Question: what is 15 + 27?")
print("=" * 60)

for token, metadata in agent.stream(
    {"messages": [HumanMessage(content="what is 15 + 27?")]},
    config={"configurable": {"thread_id": "calc-test-1"}},
    stream_mode="messages",
):
    print(token.content, end="", flush=True)
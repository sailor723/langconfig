import os
from pathlib import Path
from typing import Literal
from tavily import TavilyClient
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
model = init_chat_model(
    "deepseek-chat",
    temperature=0.5,
    timeout=600,
    max_tokens=25000,
    streaming=True,
)


def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Run a web search"""
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )


root_dir = Path(__file__).parent.resolve()
skills_dir = root_dir / "skills"
checkpointer = MemorySaver()
backend = FilesystemBackend(root_dir=str(root_dir))

agent = create_deep_agent(
    model=model,
    tools=[internet_search],
    backend=backend,
    skills=[str(skills_dir)],
    checkpointer=checkpointer,
)

print("=" * 60)
print("  Question: what is langgraph")
print("=" * 60)

for token, metadata in agent.stream(
    {"messages": [HumanMessage(content="what is langgraph")]},
    config={"configurable": {"thread_id": "web-search-skill-1"}},
    stream_mode="messages",
):
    print(token.content, end="", flush=True)
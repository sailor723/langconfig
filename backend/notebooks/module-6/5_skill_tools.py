import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "skills" / "web-search"))
sys.path.insert(0, str(Path(__file__).parent / "skills" / "calculator"))

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from web_search import internet_search
from calculator import run_python

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
    tools=[internet_search, run_python],
    backend=backend,
    skills=[str(skills_dir)],
    checkpointer=checkpointer,
)


def ask(question: str, thread_id: str):
    print("=" * 60)
    print(f"  Question: {question}")
    print("=" * 60)
    for token, metadata in agent.stream(
        {"messages": [HumanMessage(content=question)]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="messages",
    ):
        print(token.content, end="", flush=True)
    print("\n")


ask("what is 15 + 27?", "test-calc-1")
ask("what is sqrt(144)?", "test-calc-2")
ask("search latest AI news", "test-web-1")
import asyncio
import os
from dotenv import load_dotenv
load_dotenv("../.env")

import dspy
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend

dspy.configure(lm=dspy.LM(
    model=f"openai/{os.getenv('MINIMAX_MODEL', 'minimax-M3')}",
    api_base=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
    api_key=os.getenv("MINIMAX_API_KEY"),
))


class Sentiment(dspy.Signature):
    """Classify a product review as positive, negative, or neutral."""
    review: str = dspy.InputField()
    sentiment: str = dspy.OutputField()


class SentimentAnalyzer(dspy.Module):
    def __init__(self):
        super().__init__()
        self.analyze = dspy.Predict(Sentiment)

    def forward(self, review):
        return self.analyze(review=review).sentiment


analyzer = SentimentAnalyzer()


@tool
def analyze_review(review: str) -> str:
    """Classify a product review's sentiment: positive, negative, or neutral."""
    return analyzer(review=review)


async def main():
    llm = ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "minimax-M3"),
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        api_key=os.getenv("MINIMAX_API_KEY"),
        streaming=True,
    )
    agent = create_deep_agent(
        model=llm,
        tools=[analyze_review],
        backend=FilesystemBackend(root_dir="/tmp/dspy-deepagent-demo"),
        checkpointer=MemorySaver(),
    )
    result = await agent.ainvoke(
        {"messages": [("human", "Analyze the sentiment of this review: 'The camera is great but the battery drains fast.'")]},
        config={"configurable": {"thread_id": "dspy-demo-1"}, "recursion_limit": 30},
    )
    print(result["messages"][-1].content)


asyncio.run(main())

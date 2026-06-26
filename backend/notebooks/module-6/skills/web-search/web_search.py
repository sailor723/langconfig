import os
from typing import Literal
from tavily import TavilyClient


def internet_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
) -> dict:
    """Run a web search using Tavily.

    Args:
        query: The search query
        max_results: Maximum number of results (default 5)
        topic: Search topic - general, news, or finance
        include_raw_content: Whether to include raw content

    Returns:
        Tavily search results dict
    """
    tavily_client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    return tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        topic=topic,
    )
---
name: web-search
description: Use this skill when user asks to research, search the web, find information online, or look up facts.
module: web_search.py
---

# Web Search Skill

## Tool

```python
from web_search import internet_search

result = internet_search("your query", max_results=5)
```

## Instructions

### 1. Identify the Search Query
- Break down the user's question into clear, searchable terms
- Consider synonyms and related concepts

### 2. Use Tavily Search
- Use the `internet_search` tool with appropriate `max_results` (5-10 for general research)
- Set `include_raw_content=True` for detailed information

### 3. Synthesize Results
- Combine information from multiple sources
- Provide a clear, structured answer with key findings
- Include source URLs in a **References** section

### 4. Quality Check
- Verify information consistency across sources
- Note any conflicting information
- Clearly distinguish facts from opinions

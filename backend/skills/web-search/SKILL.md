---
name: web-search
description: >-
  Search the web for the latest news, current events, and recent information. Use when the user asks about today's news, current events, breaking news, recent updates, latest developments, or any extern
tags: [web-search, news, current-events, research, search]
triggers:
  - "when user asks about the latest news"
  - "when user asks about current events or breaking news"
  - "when user asks what's new or what's happening today"
  - "when user needs the most recent information on a topic"
  - "when user asks about recent events or current news"
  - "when user needs external facts not in their training data"
  - "when user asks to search the web for information"
  - "when user wants to find URLs related to a specific topic"
  - "when user asks to look up something online"
  - "when user asks to verify a fact or claim"
allowed-tools: [web_search, fetch_url, write_file, read_file]
author: User
---

---
name: web-research
description: Searches multiple web sources, synthesizes findings, and produces cited research reports using delegated subagents. Use when the user asks to research a topic online, search the web, look something up, find current information, compare options, or produce a research report.
---

# Web Research Skill
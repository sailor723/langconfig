---
name: Web Search（网络搜索）
description: >-
  在网络上检索最新新闻、时事与近期信息。当用户询问今日新闻、时事、突发新闻、最新更新、最新进展，或询问任何不在其训练数据中的外部事实时使用。
version: 1.0.0
author: User
tags:
- web-search
- news
- current-events
- research
- search
triggers:
- 当用户询问最新新闻时
- 当用户询问时事或突发新闻时
- 当用户问有什么新鲜事、今天发生了什么时
- 当用户需要某个主题的最新信息时
- 当用户询问近期事件或当前新闻时
- 当用户需要其训练数据之外的外部事实时
- 当用户要求在网上搜索信息时
- 当用户想找与某个主题相关的 URL 时
- 当用户要求上网查点东西时
- 当用户要求核实某个事实或说法时
allowed_tools:
- web_search
- fetch_url
- write_file
- read_file
lang: zh
translated: machine
source: backend/skills/en-originals/web-search/SKILL.md

---

## Instructions（指令）

# 网络调研技能

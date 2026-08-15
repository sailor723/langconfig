# Agents Audit — prompt + tools per agent (34 templates)

Status: **audit (2026-08-15)** — every `deep_agent_template` cross-checked against
the live tool registry, the `models` table, and the `skills` table.

## Summary

- 34 agents (25 deep · 9 normal). Every agent now carries the **35-tool default
  set** (merged into Postgres), so tool *coverage* is good everywhere.
- **23 agents healthy** — valid prompt, tools, skills, model.
- **11 agents flagged** below; fixes are small DB edits (models/skills/tool ids).

## ✅ Healthy (23)

| id | Agent | Notes |
|---|---|---|
| 35 | ETMF Research Agent | clean |
| 38 | research agent | 39 native + 4 skills, all valid |
| 45 | pdf_chat | clean |
| 69 | skill_gen_agent | clean |
| 73 | smart-agent | generic prompt but skills-driven — OK |
| 76 | doc-chat | generic prompt, 1 skill — OK |
| 108 | graphindex_chat | clean |
| 115 | 全球股市研究分析师 | clean |
| 119 | Market Research Agent | clean |
| 120 | Tech News Monitor | 41 native + 3 skills — clean |
| 125 | SQL Data Analyst | clean |
| 129 | 2.1 TODO Demo | clean (notebook parity) |
| 137 | 2.3 sub agent | clean |
| 138 | 2.4 full agent | clean |
| 159 | hello | **prompt stale — see F6** |
| 161 | Research Planner | clean |
| 162 | Presentation Generator | clean |
| 163 | Report Critic | clean |
| 165 | Deep Presentation Generator | clean |
| 172 | Documentation Writer | clean |
| 173 | executive researcher | clean |

## ⚠️ Flagged (11)

| # | id | Agent | Issue | Fix |
|---|---|---|---|---|
| F1 | 1,2,3,4,164 | Deep Code Researcher · Deep Architect · Deep Debugger · Deep Document Writer · Deep Test Engineer | **Model `claude-sonnet-4-5-20250929` not in the models table** (table has `claude-sonnet-4-5`) — the UI model picker can't show it and validation warns | change to `claude-sonnet-4-5` |
| F2 | 37 | analysis agent | **dead skill `internet-research`** (not in skills table) — silently skipped | remove from `skills` |
| F3 | 47 | ticker_classifer | **dead skill `pdf-chat-assistant`** (not in skills table); generic prompt | remove skill; keep prompt (skills-driven) |
| F4 | 124 | Orchestrator | **dead skill `sql-data-analyst`** (not in skills table) | remove from `skills` |
| F5 | 82 | data analysis | **dead native tool `execute`** (no such tool — meant `python_execute`?) + **38-char prompt** | fix tool id; expand prompt |
| F6 | 103 | graphindex_builder | **4 dead native tools**: `graphindex_ingest`, `graphindex_rebuild_one`, `graphindex_rebuild_project`, `graphindex_show` — functions exist in `native_impl.py` but are **not seeded** into `custom_tools` (only search/load/list_docs/multi_doc_load are) | either **seed the 4** (they're real functions — makes the builder work) or remove from config |
| F7 | 111 | Research Agent | **dead custom tool `Current Time`** — case mismatch (actual id is `current_time`) | fix to `current_time` |
| F8 | 136 | 2.3 VFS Demo | kept per request, but **VFS tools were removed** and the prompt still says "virtual file system" — now a generic filesystem demo under a stale name | optionally rename/reprompt |
| F9 | 159 | hello | **prompt asks for arithmetic/search tools** ("精通算术…请用算术和搜索工具") but the `math_*` tools were **deleted** — now relies on `python_execute`/`bash` instead | update prompt |

## Fix status (2026-08-15)

- ✅ **F1** — 5 Deep-series agents → `claude-sonnet-4-5` (+ **smart-agent**'s
  `deepseek:`-prefixed model/router ids → `deepseek-chat`).
- ✅ **F2–F4** — removed the dead skills (`internet-research`,
  `pdf-chat-assistant`, `sql-data-analyst`).
- ✅ **F5** — dropped the dead `execute` tool; expanded the `data analysis` prompt.
- ✅ **F7** — `Current Time` → `current_time`.
- ✅ **F9** — hello's prompt rewritten (no more arithmetic-tool references).
- ⏸️ **F6** — **deferred**: graphindex_builder still references the 4 unseeded
  graphindex tools (`graphindex_ingest/rebuild_one/rebuild_project/show`);
  seed them later so the builder works.
- ◻️ **F8** — optional: rename `2.3 VFS Demo` / refresh its prompt (kept per request).

## Tool coverage per agent

- Native: 35–41 tools each (the 35 defaults + per-agent extras like `tavily_search`,
  `browser`, graphindex family).
- Custom: only hello (1: `current_time`) and Research Agent (1: `current_time`).
- Skills: deep agents carry 1–7 skills; the 3 dead ids are the only gaps.

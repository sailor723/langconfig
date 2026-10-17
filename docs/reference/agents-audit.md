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
- ✅ **F6** — **fixed**: seeded the 4 graphindex build tools
  (`graphindex_ingest`, `graphindex_rebuild_one`, `graphindex_rebuild_project`,
  `graphindex_show`) into `custom_tools` (added to `SEEDABLE_TOOL_META`,
  `seed_builtin_tools.py` — now 55 seedable). All 4 materialize via
  ToolFactory with correct args; `graphindex_builder` (103) tool wiring is
  complete. Agent still needs a `minimax_api_key` in Settings to run
  (only `deepseek_api_key` is configured).
- ◻️ **F8** — optional: rename `2.3 VFS Demo` / refresh its prompt (kept per request).

## Tool coverage per agent

- Native: 35–41 tools each (the 35 defaults + per-agent extras like `tavily_search`,
  `browser`, graphindex family).
- Custom: only hello (1: `current_time`) and Research Agent (1: `current_time`).
- Skills: deep agents carry 1–7 skills; the 3 dead ids are the only gaps.

## Live curl test (2026-08-15) — all 34 agents, one by one

Method: `POST /api/chat/start` → `POST /api/chat/message/stream` (message
"Reply with exactly: OK") → `POST /api/chat/{session_id}/end`.

| Result | Count | Agents |
|---|---|---|
| ✅ **OK** (replies "OK") | 27 | deepseek agents (35, 37, 38, 47, 69, 73, 112, 125, 159, 161, 162, 163, 165, 172, 173) + minimax-m3 agents (45, 76, 82, 103, 108, 111, 115, 124, 129, 136, 137, 138) |
| 🔑 **KEY-MISSING** (clean error, key not configured) | 7 | claude-sonnet-4-5 (1, 2, 3, 4, 164), gemini-2.5-pro (120), gpt-4o (119) |

Findings from the run:

- **Bug found & fixed**: `services/agent_utils.py` referenced `settings.*`
  (`MINIMAX_API_BASE`, `AGNES_BASE_URL`, `KIMI_API_BASE`, `QWEN_API_BASE`,
  `GLM_API_BASE`, `OPENAI_API_BASE`) without importing `settings` → every
  non-deepseek/non-claude/gemini model raised
  `NameError: name 'settings' is not defined` at agent build time
  (13 agents: 12× minimax-m3 + gpt-4o). Fixed by importing `settings` from
  `config`. After the fix all 13 reach the API-key check and fail cleanly.
- After the user added `minimax_api_key` in Settings > Models, all 12
  minimax-m3 agents passed (incl. graphindex_builder 103, which also
  successfully called `doc_index_list` and had its 4 graphindex build tools
  attached — F6).
- Remaining 7 KEY-MISSING: claude (1, 2, 3, 4, 164), gemini (120), gpt-4o
  (119) — those keys are still not configured in Settings > Models.


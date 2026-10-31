---
name: research-pipeline-builder
description: >-
  Builds research-report agents powered by the research-skills pipeline: generates the thin
  orchestrator system prompt, the 3 role subagents (researcher, technical writer, critic)
  with their tool sets and role-file pointers, pins research-skills, and can create
  domain-specialized pipeline variants. Use when creating a new research/report agent.
version: 1.0.0
author: LangConfig (derived from agent 175)
tags: [meta, agent-creation, research, pipeline, builder, skill-generation]
triggers:
  - "when the user asks to create a research agent"
  - "when building an agent that produces research reports"
  - "when the user wants a report-writing agent"
  - "when asked to generate a research skill or pipeline"
  - "when the user wants a domain-specialized research agent (e.g. market, tech, medical)"
allowed_tools: [create_deepagent, create_agent, create_skill, read_file, web_search]
---

# Research Pipeline Builder

You build research-report agents on the **research-skills** pipeline. The pipeline is one
deployable unit — `research-skills` (a SKILL.md orchestration playbook + three role files
under `roles/`) — and every research agent is exactly **three pieces** plus the skill pin:

1. a **thin orchestrator system prompt** (identity + non-negotiable contract + hard limits
   + pointer to `research-skills`);
2. **3 role subagents**, each = name + description + thin prompt (pointing at its role
   file) + tools;
3. **`config.skills: ["research-skills"]`** (pins the pipeline).

## The reference implementation (agent 175, proven live)

The working agent that this builder reproduces (Research Report Writer, id 175):

- **Model**: `deepseek-v4-flash`, temperature 0.3, max_tokens 393216, reasoning_effort low
- **Middleware**: `todo_list` + `filesystem` (both enabled)
- **Guardrails**: max_total_tokens 1_000_000 / summarization 800_000 / eviction 900_000,
  auto-eviction + summarization + long-term memory on
- **Main tools** (35): `think_tool`, `reasoning_chain`, `write_todos`, `read_todos`,
  `memory_store`, `memory_recall`, `web_search`, `web_fetch`, filesystem
  (`ls read_file read_image write_file edit_file glob grep delete_file rename_file
  move_file mkdir`), `bash`, `skill`, `save_document`, Postgres
  (`pg_list_tables pg_describe_table pg_query pg_list_agents pg_get_agent
  pg_list_projects`), `sqlite_execute`, `sqlite_load_csv`, `python_execute`,
  `save_analysis_result`, `graphindex_search`, `graphindex_load`, `doc_index_list`
  (`native_tools` additionally: `tavily_search`, `serpapi_search`)
- **Subagents**: `web_researcher` [web_search, web_fetch, tavily_search, serpapi_search, think_tool, reasoning_chain],
  `technical_writer` [write_todos, read_todos, think_tool, reasoning_chain],
  `critic` [think_tool, reasoning_chain, read_todos]

## Workflow

### Step 1 — Clarify the scope
Ask or infer: research domain/topic focus, audience, output formats (default `.md` + `.docx`),
language, and whether the standard 3 roles suffice. If the domain needs a 4th specialized
role (e.g. `data_analyst`, `legal_reviewer`, `domain_expert`), note it for Step 4.

### Step 2 — Generate the thin orchestrator system prompt
Use this template (fill the placeholders; keep the contract and hard limits verbatim):

```
You are the <ROLE_NAME>. You coordinate three specialized subagents — web_researcher,
technical_writer, critic — to produce a research report on <DOMAIN>. You never do the
research or the writing yourself: you delegate, then review.

Follow the research-skills skill: read its SKILL.md via read_file and apply it. The three
role files live in the same skill folder: skills/research-skills/roles/researcher.md,
roles/writer.md, roles/critic.md.

## Non-negotiable contract
- NEVER write the document yourself. Never call write_file to produce the report.
- NEVER do web research yourself. Never call web_search / web_fetch.
- ALWAYS delegate via the task tool to the matching subagent, and relay context via FILE
  PATHS, not pasted content (subagents are context-isolated).
- NEVER use python_execute or bash to create documents or to research.
- The critic only audits and comments — it must never update the report.
- Cite sources inline in the final report (the researcher provides URLs).
- Match the language of the user's query (English or Chinese).

## Hard limits
- OVERALL ITERATION CAP: your whole run (including all subagent delegations) is capped at
  200 model/tool steps. Budget your steps; do not re-delegate the same stage repeatedly,
  and do not loop on critique→rewrite more than once unless the critique flags a blocking error.
- WEB SEARCH RETRY CAP: web_search refuses the SAME query after 3 failed attempts. If a
  search fails, rephrase the query or move on — never retry the identical query a 4th time.
```

### Step 3 — Generate the 3 subagents
For each role, emit exactly (tools verbatim):

| name | description | system_prompt (thin) | tools |
|---|---|---|---|
| `web_researcher` | "Searches the web, gathers facts, and returns sourced findings with URLs for a given research topic." | "You are a web research specialist in an ISOLATED context window: your searches, fetched pages, and reasoning stay here; the orchestrator only sees your final report. Read skills/research-skills/roles/researcher.md (via read_file) and follow it exactly. Write your verified findings to findings.md, then RETURN ONLY the file path + a 3-line summary." | `["web_search", "web_fetch", "tavily_search", "serpapi_search", "think_tool", "reasoning_chain"]` |
| `technical_writer` | "Turns research findings into a clear, well-structured technical report or document." | "You are a technical writer in an ISOLATED context window: you receive the research as a FILE, and you produce the report as FILES. Read skills/research-skills/roles/writer.md (via read_file) and follow it exactly. Produce <title>.docx AND <title>.md, then RETURN ONLY the paths + a 2-line summary." | `["write_todos", "read_todos", "think_tool", "reasoning_chain"]` |
| `critic` | "Reviews a draft report for factual accuracy, structure, clarity, and completeness; returns actionable feedback." | "You are a rigorous report critic in an ISOLATED context window: you review the report as a FILE and return your critique as text. Read skills/research-skills/roles/critic.md (via read_file) and follow it exactly. Audit the report and RETURN ONLY your structured critique. Never modify the report." | `["think_tool", "reasoning_chain", "read_todos"]` |

### Step 4 — Optional: domain-specialized variant
If the user needs a distinct pipeline (different role set or domain rules), create a NEW
skill rather than mutating `research-skills`:
1. Copy `backend/skills/personal/research-skills/` to
   `backend/skills/personal/<domain>-research-pipeline/` (e.g. `market-research-pipeline`).
2. Edit the copy's `SKILL.md`: pipeline map + delegation contract for the new roles;
   keep the context-isolation principle and iteration discipline.
3. Add `roles/<new-role>.md` for any 4th role (self-contained, like the existing ones).
4. Sync the new skill to the DB (FS→DB sync, `source_type=personal`) and pin it in the
   agent's `config.skills` instead of `research-skills`.
5. Update the orchestrator prompt's role-file pointers to the new skill path.

### Step 5 — Save the agent (self-persist)
Call the **`create_deepagent`** tool with the FULL configuration so the agent is persisted
to the database and appears in the DeepAgent Studio. Pass every field:

- `name`, `description`, `category`, `model` (use `deepseek-v4-flash`), `temperature` (0.3)
- `system_prompt` — the Step 2 output, verbatim
- `tools` — the full 35-tool list from the reference implementation
- `native_tools` — the native subset (incl. `tavily_search`, `serpapi_search`)
- `skills` — `["research-skills"]` (or the domain-variant skill id from Step 4)
- `subagents` — the Step 3 table as a JSON array: each `{name, description, type: "dictionary", system_prompt, tools}`
- `middleware` — `[{"type": "todo_list", "enabled": true, "config": {}}, {"type": "filesystem", "enabled": true, "config": {}}]`
- `guardrails` — `{"token_limits": {"max_total_tokens": 1000000, "summarization_threshold": 800000, "eviction_threshold": 900000}, "enable_auto_eviction": true, "enable_summarization": true, "long_term_memory": true}`
- `max_tokens` — 393216, `reasoning_effort` — `"low"`

List/dict arguments may be passed as JSON strings (e.g. `'["web_search", "web_fetch"]'`).
Confirm the tool returns `✅ Agent '<name>' (id=<n>) created successfully` — that id is
the persisted agent. Reference template (argument map, not a separate API call):

```json
{
  "name": "<kebab-or-title>",
  "description": "Researches <DOMAIN> using web search + project documents, then writes a structured report saved to the workspace.",
  "category": "research",
  "model": "deepseek-v4-flash",
  "temperature": 0.3,
  "max_tokens": 393216,
  "reasoning_effort": "low",
  "system_prompt": "<Step 2 output>",
  "tools": ["think_tool","reasoning_chain","write_todos","read_todos","memory_store","memory_recall","web_search","web_fetch","ls","read_file","read_image","write_file","edit_file","glob","grep","delete_file","rename_file","move_file","mkdir","bash","skill","save_document","pg_list_tables","pg_describe_table","pg_query","pg_list_agents","pg_get_agent","pg_list_projects","sqlite_execute","sqlite_load_csv","python_execute","save_analysis_result","graphindex_search","graphindex_load","doc_index_list"],
  "native_tools": ["think_tool","reasoning_chain","write_todos","read_todos","web_search","web_fetch","skill","graphindex_search","graphindex_load","doc_index_list","memory_store","memory_recall","rename_file","move_file","mkdir","bash","save_document","pg_list_tables","pg_describe_table","pg_query","pg_list_agents","pg_get_agent","pg_list_projects","sqlite_execute","sqlite_load_csv","python_execute","save_analysis_result","tavily_search","serpapi_search"],
  "skills": ["research-skills"],
  "middleware": [
    { "type": "todo_list", "enabled": true, "config": {} },
    { "type": "filesystem", "enabled": true, "config": {} }
  ],
  "subagents": [ "<Step 3: the 3 subagent objects>" ],
  "guardrails": {
    "interrupts": {},
    "token_limits": { "max_total_tokens": 1000000, "summarization_threshold": 800000, "eviction_threshold": 900000 },
    "enable_auto_eviction": true, "enable_summarization": true, "long_term_memory": true
  }
}
```

If the `create_deepagent` tool is NOT available to you, fall back to emitting the same
JSON for the operator to create via `POST /api/deepagents/` (CreateDeepAgentRequest).

### Step 6 — Verify
The agent is persisted the moment `create_deepagent` returns its id. Confirm it via
`pg_get_agent` / the DeepAgent Studio, then run one short test chat ("write a SHORT
2-section report on <topic>, follow your full workflow") and confirm in the stream: the
orchestrator reads `skills/research-skills/SKILL.md`, each subagent reads its
`roles/<role>.md`, a `task` delegation fires for each stage, and the final files land in
the agent workspace.

## Quality checklist
- [ ] System prompt has the full non-negotiable contract + hard limits (never shortened)
- [ ] All 3 subagents have their role-file pointer + exact tool lists
- [ ] `skills` pins the right pipeline skill (`research-skills` or the domain variant)
- [ ] Domain variant (if any) is a separate skill dir, synced, with its own SKILL.md map
- [ ] `create_deepagent` returned a success message with an agent id (persisted!)
- [ ] A test chat completes with files produced

---
name: presentation-pipeline-builder
description: >-
  Builds presentation agents powered by the presentation-skills pipeline: generates the thin
  orchestrator system prompt, 3 role subagents (outline_designer, deck_writer, qa_reviewer)
  with their tool sets and role-file pointers, pins presentation-skills, and saves via
  create_deepagent. Use when creating a new presentation/deck agent.
version: 1.0.0
author: LangConfig (derived from agent 165 + research-pipeline-builder)
tags: [meta, agent-creation, presentation, pptx, pipeline, builder]
triggers:
  - "when the user asks to create a presentation agent"
  - "when building an agent that produces PowerPoint decks"
  - "when the user wants a 演示文稿 / PPT agent"
allowed_tools: [create_deepagent, create_agent, create_skill, read_file, web_search]
---

# Presentation Pipeline Builder

You build presentation agents on the **presentation-skills** pipeline. A presentation
agent is exactly **three pieces** plus the skill pin:

1. a **thin orchestrator system prompt** (identity + non-negotiable contract + hard limits
   + pointer to `presentation-skills`);
2. **3 role subagents** (outline_designer, deck_writer, qa_reviewer), each = name +
   description + thin prompt (pointing at its role file) + tools — the deck_writer MUST
   have the deck tools `gen_pptx`, `gen_html_deck`, `gen_pdf_deck` (tool-first, NOT
   hand-written python-pptx/HTML scripts);
3. **`config.skills: ["presentation-skills"]`**.

## Reference (proven): the tool-first design

The platform's older Deep Presentation Generator (agent 165) is the same architecture but
script-based (subagents wrote `generate_pptx.py` and ran `python_execute` ~30× per deck).
New agents MUST be **tool-first**: the deck_writer calls the theme-aware deck tools
(`gen_pptx`, `gen_html_deck`, `gen_pdf_deck`; 6 themes: business/fashion/tech/health/
education/minimal) — deterministic, one call per format.

## Workflow

### Step 1 — Clarify the scope
Ask or infer: presentation domain/topic, preferred theme (business / fashion / tech /
health / education / minimal), source-doc input style. If a 4th specialized role is needed
(e.g. `data_analyst` for chart-heavy decks), note it for Step 4.

### Step 2 — Generate the thin orchestrator system prompt
Template (keep the contract and hard limits verbatim):

```
You are the <ROLE_NAME>. You coordinate three specialized subagents — outline_designer,
deck_writer, qa_reviewer — to turn documents into a themed deck (PPTX/HTML/PDF) on <DOMAIN>.
You never design slides or generate the deck yourself: you delegate, then review.

Follow the presentation-skills skill: read its SKILL.md via read_file and apply it. The
three role files live in the same skill folder:
skills/presentation-skills/roles/outline-designer.md, roles/deck-writer.md,
roles/qa-reviewer.md.

## Non-negotiable contract
- NEVER design the outline or write the deck yourself. Never call gen_pptx directly.
- ALWAYS delegate via the task tool to the matching subagent, and relay context via FILE
  PATHS (outline JSON, source doc), not pasted content (subagents are context-isolated).
- deck_writer MUST use the deck tools (gen_pptx / gen_html_deck / gen_pdf_deck); it must
  NOT hand-write python-pptx/HTML scripts.
- NEVER use python_execute or bash to generate the deck.
- qa_reviewer only audits and comments — it must never modify the deck or outline.
- Match the language of the user's query (English or Chinese).

## Hard limits
- OVERALL ITERATION CAP: your whole run is capped at 200 model/tool steps. Budget your
  steps; outline review ≤2 rounds, deck revision ≤1 round after QA feedback.
- Do not re-delegate the same stage repeatedly.
```

### Step 3 — Generate the 3 subagents
Emit exactly (tools verbatim):

| name | description | system_prompt (thin) | tools |
|---|---|---|---|
| `outline_designer` | "Turns a source document into a 12–15-page slide outline JSON (cover → agenda → content → data → conclusion → closing) for a themed deck." | "You are an outline designer in an ISOLATED context window. Read skills/presentation-skills/roles/outline-designer.md (via read_file) and follow it exactly. Write the outline JSON to the path in the brief, then RETURN ONLY the outline path + a 2-line summary." | `["read_file", "ls", "glob", "write_file", "think_tool", "reasoning_chain"]` |
| `deck_writer` | "Generates the deck (pptx/html/pdf) from the outline JSON using the theme-aware gen_pptx / gen_html_deck / gen_pdf_deck tools." | "You are a deck writer in an ISOLATED context window. Read skills/presentation-skills/roles/deck-writer.md (via read_file) and follow it exactly. Call the deck tools (gen_pptx / gen_html_deck / gen_pdf_deck) with the outline JSON (as a string) + the theme for each requested format, then RETURN ONLY the output path(s) + a 1-line summary." | `["read_file", "ls", "glob", "gen_pptx", "gen_html_deck", "gen_pdf_deck", "think_tool", "reasoning_chain"]` |
| `qa_reviewer` | "Audits the generated .pptx against the outline (slide count, titles, bullets, theme, notes) and returns PASS/CHANGES." | "You are a QA reviewer in an ISOLATED context window. Read skills/presentation-skills/roles/qa-reviewer.md (via read_file) and follow it exactly. Audit the deck against the outline and RETURN ONLY your structured verdict. Never modify the deck." | `["read_file", "ls", "glob", "think_tool", "reasoning_chain"]` |

### Step 4 — Optional: domain-specialized variant
If a distinct pipeline is needed (extra role, different deck rules), copy
`backend/skills/personal/presentation-skills/` to
`backend/skills/personal/<domain>-presentation-pipeline/`, adapt the SKILL.md + add
`roles/<new-role>.md`, sync, and pin that skill id instead.

### Step 5 — Save the agent (self-persist)
Call the **`create_deepagent`** tool with the FULL configuration:

- `name`, `description`, `category: "presentation"`, `model: "deepseek-v4-flash"`,
  `temperature: 0.3`, `max_tokens: 393216`, `reasoning_effort: "low"`
- `system_prompt` — the Step 2 output, verbatim
- `tools` — `["think_tool","reasoning_chain","write_todos","read_todos","memory_store","memory_recall","web_search","web_fetch","ls","read_file","read_image","write_file","edit_file","glob","grep","delete_file","rename_file","move_file","mkdir","skill","gen_pptx","gen_html_deck","gen_pdf_deck","save_document","python_execute"]`
- `native_tools` — `["think_tool","reasoning_chain","write_todos","read_todos","web_search","web_fetch","skill","gen_pptx","gen_html_deck","gen_pdf_deck","memory_store","memory_recall","save_document","bash"]`
- `skills` — `["presentation-skills"]`
- `middleware` — `[{"type":"todo_list","enabled":true,"config":{}},{"type":"filesystem","enabled":true,"config":{}}]`
- `subagents` — the Step 3 table as a JSON array
- `guardrails` — `{"token_limits":{"max_total_tokens":1000000,"summarization_threshold":800000,"eviction_threshold":900000},"enable_auto_eviction":true,"enable_summarization":true,"long_term_memory":true}`

List/dict arguments may be passed as JSON strings. Confirm the tool returns
`✅ Agent '<name>' (id=<n>) created successfully`.

If the `create_deepagent` tool is NOT available, emit the same JSON for the operator to
create via `POST /api/deepagents/` (CreateDeepAgentRequest).

### Step 6 — Verify
Confirm the agent id via `pg_get_agent`, then run one short test chat ("make a SHORT
5-slide deck on <topic> from <doc>, follow your full workflow") and confirm in the stream:
orchestrator reads `skills/presentation-skills/SKILL.md`, each subagent reads its role
file, deck_writer calls the deck tools, and `.pptx`/`.html`/`.pdf` land in the workspace.

## Quality checklist
- [ ] System prompt has the full non-negotiable contract + hard limits (never shortened)
- [ ] All 3 subagents have their role-file pointer + exact tool lists
- [ ] `deck_writer` has `gen_pptx` + `gen_html_deck` + `gen_pdf_deck` (tool-first, not script-first)
- [ ] `skills` pins `presentation-skills` (or the domain variant)
- [ ] `create_deepagent` returned a success message with an agent id (persisted!)
- [ ] A test chat completes with deck file(s) produced (pptx / html / pdf)

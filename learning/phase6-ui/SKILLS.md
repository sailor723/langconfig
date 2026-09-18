# Skills — Extending Agents with Modular Capabilities

> A "skill" is a reusable bundle of instructions + (optional) helper files that an agent reads on demand to handle specific kinds of tasks. Skills let you teach an agent specialized behavior without bloating its system prompt.

This README documents the **skill system** that complements the agent + workflow concepts in [`README.md`](./README.md).

---

## 1. Mental Model: What Is a Skill?

A **skill** is a folder containing:

```
my-skill/
├── SKILL.md          # REQUIRED — instructions + metadata
└── helper.py         # OPTIONAL — executable helper script
```

**SKILL.md** has two parts:

1. **YAML frontmatter** (required) — name, description, tags, triggers
2. **Markdown body** — step-by-step workflow, business rules, examples, edge cases

```markdown
---
name: finance-pro
description: Tax-aware revenue analysis with regional rules (US 8%, EMEA 15%, APAC 12%).
tags: [finance, analytics]
triggers:
  - "revenue by region"
  - "tax calculation"
---

## Instructions

### Tax Rates
| Region | Tax |
|---|---|
| US | 8% |
| EMEA | 15% |
| APAC | 12% |

### Formula
`net_after_tax = (qty * price - discount) * (1 - tax_rate)`
```

When an agent is given access to a skill, the skill's `name` and `description` are injected into the system prompt as a catalog. The agent then reads `SKILL.md` on demand via `read_file` when it decides the skill applies.

This pattern is called **progressive disclosure** — the agent sees *what skills exist* (small catalog), but only loads *how to use them* (full body) when needed.

---

## 2. Skill vs Agent vs Tool

These three concepts overlap but serve different purposes:

| Concept | What it is | Lives in | Created by |
|---|---|---|---|
| **Tool** | A function the agent can call (e.g., `python_repl`, `web_search`) | Code (Python `@tool` decorated function) | Developer |
| **Agent** | A self-contained AI unit (model + tools + prompt) | DB (`deep_agent_templates`) | UI form |
| **Skill** | Reusable instructions + helpers, read on demand | FS (`backend/skills/<name>/SKILL.md`) | Anyone (file edit) |

### When to use which

- **Tool** — single-purpose atomic action (run Python, search web, query DB)
- **Agent** — combine model + tools + persona to handle a class of conversations
- **Skill** — add domain knowledge / workflow to an agent without changing code or DB

A skill is essentially a **"playbook"** an agent can consult. It doesn't add capabilities (tools do that) — it teaches the agent *how* and *when* to use them.

---

## 3. Where Skills Live

### Filesystem layout

```
backend/skills/                              ← ALL skills
├── builtin/                                  ← git-tracked, system skills
│   ├── code-review/SKILL.md
│   ├── data-analysis/SKILL.md
│   └── ... (15 skills)
│
├── personal/                                 ← git-tracked, user-created
│   ├── bug-report-analyzer/SKILL.md
│   ├── unit-test-writer/SKILL.md
│   └── ... (12 skills)
│
└── market_wizard/                            ← git-tracked, our refactor
    ├── SKILL.md
    └── rules.yaml                            ← YAML rules for content-free wizard
```

> Skills are **filesystem-first**, not DB-driven. Adding a skill = create a folder. No DB schema, no migration, no API call.

### Where they're discovered

When the backend starts (or a session begins), the library scans the skills directories and builds a catalog of `name + description` for each SKILL.md. This catalog is injected into agent prompts that have skills enabled.

---

## 4. SKILL.md Frontmatter Specification

```yaml
---
name: kebab-case-id              # REQUIRED
  # Lowercase alphanumeric with single hyphens
  # Must match the directory name
  # Example: "code-review", "unit-test-writer"

description: <one-liner>         # REQUIRED
  # ≤200 chars, mentions WHAT and WHEN
  # Example: "Tax-aware revenue analysis with regional rules"

version: 1.0.0                  # OPTIONAL
author: <name>                  # OPTIONAL
tags: [analytics, finance]      # OPTIONAL
triggers:                       # OPTIONAL
  - "when user asks for X"
allowed_tools:                  # OPTIONAL
  - execute
  - filesystem
---
```

### Naming rules (strict)

- Lowercase letters, digits, and **single hyphens only**
- No spaces, no underscores, no double hyphens
- Must match the directory name
- Must be unique within a skills root

```
✓ code-review, unit-test-writer, finance-pro
✗ Code Review, code_review, code--review, -code
```

> Common pitfall: SKILL.md files copied from other systems often use Title Case in `name:` — the library warns but still loads them. Fix by lowercasing.

---

## 5. Authoring a Skill (5-Section Template)

The recommended structure (see [`skill_md_best_practices.md`](../skill_md_best_practices.md) for the full reference):

```markdown
---
name: my-skill
description: What it does and when to use it.
---

## Data Source            ← Where data lives, sample rows
## Column Metadata        ← Each column: name + type + semantic + usage
## Business Logic         ← Formulas, thresholds, exceptions
## Few-shot Examples      ← 3-5 copy-paste-runnable examples
## Edge Cases & Pitfalls  ← 4-10 ❌/✅ pitfalls
```

### Special case: data-preparation skills

If a skill **cleans data** rather than **answers business questions**, replace Section 3 with:

```markdown
## Business Context
- What business questions this cleaned data enables (delegated to analysis skill)

## Data Cleaning Rules
- The actual transformation steps
```

### Length guideline

- 50-200 lines is ideal
- < 50 lines: too sparse, missing context
- > 300 lines: too verbose, the LLM won't read carefully

---

## 6. Associating Skills with Agents

In the **Agents** tab, the agent config has a `skills` field:

```python
class DeepAgentConfig:
    name: str
    model: str
    skills: list[str]   # ← list of skill IDs
    ...
```

When a chat session starts:
1. Library looks up each skill ID in the FS
2. Builds catalog (name + description for each)
3. Injects catalog into system prompt
4. Agent decides whether to read each SKILL.md

### Three patterns (in order of complexity)

| Pattern | `skills` value | When |
|---|---|---|
| **Single skill** | `["finance-pro"]` | Agent does one specialized task |
| **Multiple skills** | `["finance-pro", "market-wizard"]` | Agent handles related workflows |
| **All skills** | `[]` or `["*"]` | Agent has general-purpose role |

---

## 7. Progressive Disclosure — How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Library injects SKILLS_SYSTEM_PROMPT into agent         │
│  ────────────────────────────────────────────────────────────── │
│  "You have access to:                                            │
│   - finance-pro: Tax-aware revenue analysis...                  │
│   - bug-report-analyzer: Severity classification..."            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: User sends query                                        │
│  ────────────────────────────────────────────────────────────── │
│  "Analyze Q4 revenue by region"                                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: Agent decides which skill matches                      │
│  ────────────────────────────────────────────────────────────── │
│  Matches "revenue by region" → finance-pro                     │
│  Calls read_file("skills/finance-pro/SKILL.md", limit=1000)   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: Agent applies skill's rules                            │
│  ────────────────────────────────────────────────────────────── │
│  Loads US 8% / EMEA 15% / APAC 12% tax rates                    │
│  Computes net_after_tax using formula                          │
│  Generates chart with generate_report tool                     │
└─────────────────────────────────────────────────────────────────┘
```

### Why progressive disclosure?

- **Token efficiency**: SKILL.md bodies are 100-200 lines each. Loading all of them would bloat the system prompt by 5-10K tokens per session.
- **On-demand accuracy**: Agent reads exactly the skill it needs, not stale info from others.
- **Easy to extend**: Add a new skill = drop a folder. No code change to the agent.

### Catalog visibility

Agents see `name` and `description` only. They do NOT see:
- The body of SKILL.md (must call `read_file`)
- Other skills' bodies
- Helper scripts

This is intentional — keeps catalog cheap to inject.

---

## 8. Skill Catalog (Current)

### Built-in (15 skills in `backend/skills/builtin/`)

| Skill | Purpose |
|---|---|
| `code-review` | Reviews code for style, bugs, and best practices |
| `data-analysis` | Deterministic data profiling + aggregation |
| `data-analysis-llm` | Flexible LLM-driven data analysis |
| `debugging` | Systematic debugging workflow |
| `documentation` | API/function documentation generation |
| `frontend-design` | UI/UX review and suggestions |
| `git-workflow` | Git commands and PR creation |
| `langchain-agents` | LangChain patterns |
| `langconfig-builder` | Build LangConfig components |
| `langgraph-workflows` | LangGraph patterns |
| `mcp-builder` | MCP tool creation |
| `python-testing` | pytest patterns |
| `security-review` | Security audit checklist |
| `skill-generator` | Generate new skills |
| `webapp-testing` | E2E testing |

### Personal (12 skills in `backend/skills/personal/`)

| Skill | Purpose |
|---|---|
| `ai-agent-trends-research` | Research AI agent trends |
| `ai-agent-trends-researcher` | Trend reporting |
| `api-rate-limiter` | API rate limit handling |
| `bug-report-analyzer` | Bug severity classification |
| `changelog-generator` | Format changelogs |
| `pdf-chat` | PDF interaction |
| `pdf-chat-assistant` | PDF assistant |
| `text-summarizer` | Text summarization |
| `ticket-classifier` | Support ticket triage |
| `tool-analyzer` | Tool code analysis |
| `unit-test-writer` | Generate pytest tests |
| `web-search` | Web search workflow |

### Notebook demo (5 skills in `backend/notebooks/module-5/skills/`)

Used by the progressive-disclosure demo:
- `finance_pro` — financial analysis
- `inventory_management` — inventory queries
- `market_wizard` — CSV cleaning (with `rules.yaml`)
- `sales_analytics` — sales queries
- `personal_skills/` — 12 personal skills (mirror of `backend/skills/personal/`)

---

## 9. Adding a New Skill

### Step-by-step

1. **Create the folder**
   ```bash
   mkdir -p backend/skills/personal/my-new-skill
   ```

2. **Create SKILL.md** (use the 5-section template)
   ```bash
   $EDITOR backend/skills/personal/my-new-skill/SKILL.md
   ```

3. **Validate frontmatter** (no Title Case, kebab-case name)
   ```yaml
   ---
   name: my-new-skill         # ✓ kebab-case
   description: What it does. # ✓ ≤200 chars
   ---
   ```

4. **Restart the backend** (skills are loaded at startup)
   ```bash
   cd backend && .venv/bin/python main.py
   ```

5. **Verify discovery** (catalog should now include the new skill)
   - Run `skill_agent_demo.py`
   - Look for "Available Skills" in output

6. **Associate with an agent**
   - In **Agents** tab, edit agent config
   - Add `"my-new-skill"` to the `skills` list
   - Save

7. **Test the agent**
   - Use **Test Agent** modal
   - Send a query that should trigger the skill
   - Verify agent reads SKILL.md and applies rules

---

## 10. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Skill not in catalog | Wrong directory structure | Folder must be `skills/<name>/SKILL.md` (not flat) |
| Skill loaded but agent ignores it | Description too vague | Make `description:` specific about WHEN to use |
| Agent uses wrong info | SKILL.md not read | Add "ALWAYS read SKILL.md first" to agent's system prompt |
| Name validation warnings | Title Case in `name:` field | Lowercase the `name:` in frontmatter |
| Helper script not found | Path not absolute in SKILL.md | Use absolute paths in instructions |
| Skill conflict (2 with same name) | Duplicates | Last one wins; check all skills roots |
| SKILL.md too long | >300 lines | Split into multiple skills or use `helper.py` |

---

## 11. Future Direction

### Short term (now)
- ✅ FS-first skills (no DB sync)
- ✅ Content-light SKILL.md (5-section template)
- ✅ Generic wizard for data-prep skills (YAML rules + Pydantic schema)
- ⏳ Skill catalog UI (browse, search, create)

### Medium term
- 🔲 Semantic search over skill descriptions (find right skill by intent)
- 🔲 Skill versioning (`skill-name@v1`, `@v2`)
- 🔲 Skill marketplace (share across projects)

### Long term
- 🔲 Auto-generate skills from successful agent runs
- 🔲 Skill composition (skill that calls other skills)
- 🔲 Per-agent skill permissions (some agents only see some skills)

---

## 12. Related Files

| File | Purpose |
|---|---|
| [`backend/notebooks/module-5/agent_skills.py`](../../backend/notebooks/module-5/agent_skills.py) | Reference notebook implementation |
| [`backend/services/skill_agent_demo.py`](../../backend/services/skill_agent_demo.py) | Standalone demo (notebook pattern, all skills) |
| [`backend/services/skill_agent_subagents_demo.py`](../../backend/services/skill_agent_subagents_demo.py) | Subagent-per-skill demo |
| [`backend/core/data_prep/wizard.py`](../../backend/core/data_prep/wizard.py) | Generic CSV wizard for data-prep skills |
| [`backend/schemas/sales.py`](../../backend/schemas/sales.py) | Canonical schema (single source of truth) |
| [`learning/skill_md_best_practices.md`](../skill_md_best_practices.md) | Detailed SKILL.md authoring guide |
| [`learning/phase6/README.md`](../phase6/README.md) | Phase 6 architecture overview |

---

## TL;DR

- **Skill** = folder with `SKILL.md` (+ optional helpers)
- **Progressive disclosure** = catalog in prompt, body on demand
- **Where** = `backend/skills/{builtin,personal}/<name>/SKILL.md`
- **Add one** = create folder + SKILL.md + restart + edit agent's `skills` list
- **Why** = modular knowledge without bloating system prompt
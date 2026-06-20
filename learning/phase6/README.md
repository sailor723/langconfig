# Phase 6: Normalization — Skill as the Hub

> How to normalize the LangConfig codebase around LangChain/LangGraph/DeepAgent concepts, making the **Skill** the central hub that connects prompts, tools, and agents through the UI rather than through IDE-generated glue code.

---

## Motivation

LangConfig was built iteratively with heavy IDE assistance. The result works, but the **abstraction boundaries between LangChain, LangGraph, and DeepAgent concepts are blurred**. The platform has all the features — Prompt editor, Skill builder, Agent studio, Tool library — but they operate as **separate islands** rather than a connected system.

The core insight: **Skill should be the hub** that ties everything together in a LangChain-native way:

```
          ┌──────────┐
          │  Prompt  │◄──── instructions (template with {{variables}})
          └────┬─────┘
               │
          ┌────▼─────┐
          │   Skill   │──── allowed_tools ────► ┌──────────┐
          │  (hub)   │                          │   Tool   │
          └────┬─────┘                          └──────────┘
               │
          ┌────▼─────┐
          │  Agent   │──── explicit_skills ────► runtime injection
          └──────────┘
```

This phase documents the **gap analysis**, the **target architecture**, and the **3-phase implementation plan** to normalize the codebase.

---

## Current State: Gap Analysis

### Trace: The Full Skill Data Flow

```
SkillBuilderModal.tsx                    SkillLibrary.tsx                    DeepAgentBuilder.tsx
  ┌─────────────────┐                   ┌─────────────────┐                 ┌─────────────────────┐
  │ name, desc      │                   │ browse skills   │                 │ model, tools,       │
  │ tags, triggers  │  POST /api/skills │ view details    │                 │ middleware,          │
  │ instructions    │ ───────────────►  │                 │                 │ subagents           │
  └─────────────────┘                   └─────────────────┘                 │ skills: [] (hidden) │
         │                                   │                              │ enable_skills: false│
         │                                   │ (no agent binding)           └─────────────────────┘
         │                                   │                                      │
         ▼                                   ▼                                      ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────┐
  │                                        Backend                                        │
  │                                                                                       │
  │  models/skill.py          core/skills/registry.py          core/agents/factory.py     │
  │  ┌──────────────┐        ┌─────────────────────┐         ┌──────────────────────┐    │
  │  │ Skill table  │◄──────►│ in-memory cache + DB │◄──────►│ _inject_skills()     │    │
  │  │ - skill_id  │        │ CRUD, tags, search   │         │ BUT disabled by      │    │
  │  │ - name      │        └─────────────────────┘         │ default              │    │
  │  │ - tags      │                                         │ (enable_skills=False)│    │
  │  │ - triggers  │                                         └──────────────────────┘    │
  │  │ - allowed   │                                                  │                  │
  │  │   _tools    │                                                  ▼                  │
  │  │ - instruc-  │                                         System prompt string        │
  │  │   tions     │                                         "injection" is invisible    │
  │  └──────────────┘                                         to the user                │
  └──────────────────────────────────────────────────────────────────────────────────────┘
```

### Problem 1: Agent ↔ Skill Connection Missing in UI

| Backend supports | UI exposes |
|---|---|
| `enable_skills: bool` | ❌ No toggle in DeepAgentBuilder |
| `explicit_skills: List[str]` | ❌ No skill picker — only raw text paths for subagents |
| `enable_skill_auto_detection: bool` | ❌ No toggle |

The `AgentFactory._inject_skills()` at [`backend/core/agents/factory.py#L848`](../../backend/core/agents/factory.py#L848) is a complete, working system. It:
1. Loads explicitly requested skills by ID
2. Auto-detects relevant skills via semantic/trigger/tag matching
3. Injects formatted skill instructions into the system prompt
4. Composes multiple skills with proper section markers

But the UI never activates it. `enable_skills` defaults to `False` and no UI control sets it to `True`.

### Problem 2: Skill Builder is Missing Key Fields

| DB model field | API supports | UI exposes |
|---|---|---|
| `allowed_tools: List[str]` | ✅ CRUD | ❌ Not editable in SkillBuilderModal |
| `instructions` (as prompt template) | ✅ Text | ⚠️ Plain textarea — no variable support |

### Problem 3: Skill ↔ Agent Binding is Invisible

- Skill Library shows skills but cannot show which agents use them
- Agent Builder has no "Manage Skills" section
- When skills are injected at runtime, the `PromptCanvas` doesn't show them as segments
- User has no visibility into "this agent will use skills X, Y, Z"

### Problem 4: Prompt is Not a First-Class Entity

- Agent `system_prompt`, `custom_prompt`, `custom_suffix` are strings embedded in JSON
- Skill `instructions` is a raw text column
- No `Prompt` table, no prompt versioning, no prompt reuse across agents/skills
- `PromptAssemblyPage` requires an agent context — cannot create/edit prompts standalone

---

## Target Architecture: Skill as the Hub

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          LangConfig IDE                                 │
│                                                                         │
│   ┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌────────────┐  │
│   │ Prompt   │◄──►│    Skill     │◄──►│   Tool   │    │   Agent    │  │
│   │ Library  │    │   Catalog    │    │ Library  │    │   Studio   │  │
│   │ (DB)     │    │ (DB + file)  │    │ (DB)     │    │   (DB)     │  │
│   └────┬─────┘    └──────┬───────┘    └──────────┘    └─────┬──────┘  │
│        │                 │                                   │        │
│        │   instructions  │  allowed_tools                    │        │
│        │◄────────────────┼───────────────────────────────────┤        │
│        │                 │                                   │        │
│        └─────────────────┼───────────────────────────────────┘        │
│                          │ explicit_skills                            │
│                          │ enable_skills                              │
│                          ▼                                             │
│                   ┌──────────────────────┐                           │
│                   │    Runtime Engine     │                           │
│                   │                       │                           │
│                   │ 1. Load agent config  │                           │
│                   │ 2. Resolve prompts    │                           │
│                   │ 3. Match & inject     │                           │
│                   │    skills             │                           │
│                   │ 4. Bind tools         │                           │
│                   │ 5. Create LangGraph   │                           │
│                   │    agent              │                           │
│                   └──────────────────────┘                           │
└─────────────────────────────────────────────────────────────────────────┘

Conceptual mapping to LangChain ecosystem:

  Prompt        ──►  LangChain PromptTemplate ({{variables}}, composition)
  Skill         ──►  LangChain RunnableBranch / Agent's "expertise module"
  Tool          ──►  LangChain BaseTool / StructuredTool
  Agent         ──►  LangGraph CompiledStateGraph (with or without DeepAgent middleware)
  Agent+Skills  ──►  LangGraph agent with augmented system prompt + tool constraints
```

---

## Implementation Plan: 3 Phases

### Phase 1: Connect Agent ↔ Skill in UI (High Impact, Low Effort)

**Goal**: Activate the existing backend skill injection by building the missing UI controls.

#### 1.1 Add "Enable Skills" toggle + skill picker to DeepAgentBuilder

**Files**: [`src/features/agents/ui/DeepAgentBuilder.tsx`](../../src/features/agents/ui/DeepAgentBuilder.tsx)

Changes:
- Add an "Enable Skills" toggle switch (→ `enable_skills: true`)
- Add "Enable Auto-Detection" toggle (→ `enable_skill_auto_detection: true/false`)
- Add a "Max Skills" number input (→ `max_skills: number`)
- Add a **Skill Picker** button that opens `SkillLibrary` in multi-select mode
- Selected skills populate `skills: ["skill-id-1", "skill-id-2"]` in agent config
- Show selected skills as chips/badges with remove button

**Backend**: Already works — `factory.py` lines 607-629 will pick up these config fields.

#### 1.2 Add `allowed_tools` editor to Skill Builder

**File**: [`src/features/agents/ui/SkillBuilderModal.tsx`](../../src/features/agents/ui/SkillBuilderModal.tsx)

Changes:
- Add a "Allowed Tools" multi-select section
- Load available tools from `GET /api/tools`
- User selects which tools this skill can use
- Save `allowed_tools` array via existing API

**Backend**: DB model already has `allowed_tools` JSON column — no changes needed.

#### 1.3 Show skill-to-agent bindings in Skill Library

**File**: [`src/features/skills/ui/SkillLibrary.tsx`](../../src/features/skills/ui/SkillLibrary.tsx)

Changes:
- Add a "Used by N agents" metric to skill cards
- Click to see which agents use this skill

**Backend**: Add `GET /api/skills/{id}/agents` endpoint (queries `deep_agent_templates` for configs containing the skill ID).

#### 1.4 Add skills section to AgentLoadouts detail panel

**File**: [`src/features/agents/ui/AgentLoadouts.tsx`](../../src/features/agents/ui/AgentLoadouts.tsx)

Changes:
- When viewing agent details, show "Equipped Skills" section
- Show skill name, description, tags
- Link to open skill detail
- Button to "Manage Skills" → opens skill picker

---

## ✅ Completed (Phase 1.1 + 1.4 + 2.3)

### What Was Built

| Component | Files Changed | Status |
|---|---|---|
| Skills section in DeepAgentBuilder (creation) | `DeepAgentBuilder.tsx` | ✅ Done |
| Skills section in AgentConfigView (edit panel) | `AgentLoadouts.tsx` | ✅ Done |
| Skill picker modal with all available skills | `DeepAgentBuilder.tsx`, `AgentLoadouts.tsx` | ✅ Done |
| Selected skills shown as chips with remove | `DeepAgentBuilder.tsx`, `AgentLoadouts.tsx` | ✅ Done |
| Auto-enable `use_local_sandbox` when skills selected | `DeepAgentBuilder.tsx`, `AgentLoadouts.tsx` | ✅ Done |
| Auto-inject skill instruction into system prompt at runtime | `deepagent_factory.py` | ✅ Done |
| **Skill Router LLM** — deepseek routes, only matched skill loaded | `deepagent_factory.py` | ✅ Done |
| **Skill Router UI** — model picker in edit panel | `AgentLoadouts.tsx` | ✅ Done |
| End-to-end test script (filesystem + DB flow) | `scripts/test_ticket_classifier.py` | ✅ Done |
| Test script for persistent skill creation | `scripts/create_ticket_skill.py` | ✅ Done |
| Multi-skill auto-selection test (3 skills, generic prompt) | `scripts/test_multi_skill_auto_select.py` | ✅ Done |
| Skill Router LLM test (5 scenarios, 100% accuracy) | `scripts/test_skill_router.py` | ✅ Done |

### Verified End-to-End Flow

```
UI Skills Panel → POST /api/skills → PostgreSQL
     ↓
Agent Builder → select skills → save → DB (skills: ["ticket-classifier"], use_local_sandbox: true)
     ↓
deepagent_factory.py at runtime:
  1. Read agent config from DB ──── skills: ["ticket-classifier"]
  2. Read skill from DB ─────────── instructions, tags, triggers
  3. Write SKILL.md to sandbox ──── outputs/default/skills/ticket-classifier/SKILL.md
  4. Inject prompt hint ─────────── "You have skills: ticket-classifier"
  5. create_deep_agent(skills=[path]) ── SkillsMiddleware loads SKILL.md
     ↓
Agent classifies ticket: Category=Shipping, Priority=High, Sentiment=Frustrated ✅
```

### Key Findings

1. **`use_local_sandbox: true` is required** for skills to reach `create_deep_agent()`. The `deepagent_factory.py` only syncs DB→filesystem when sandbox is enabled. Fixed by auto-enabling sandbox when skills are selected.

2. **Skill auto-selection works with generic system prompts** — the deepagents `SkillsMiddleware` handles progressive disclosure: it lists all available skills (name + description) in the `## Skills System` section, and the LLM automatically selects the correct one based on user intent. NO hardcoded skill names needed in the system prompt. The only requirement is a concise hint: *"You have access to equipped skills."*

3. **No PostgreSQL needed for core testing** — skills can be tested via filesystem-only: create SKILL.md on disk → `create_deep_agent(skills=[path])`. This pattern is documented in `rules.md`.

### Test Script

```bash
cd backend && uv run python scripts/test_ticket_classifier.py
```

Three tests:
- **Test 1**: DeepAgentConfig model validation
- **Test 2**: Filesystem skill → `create_deep_agent()` → invoke
- **Test 3**: Full DB → filesystem → `create_deep_agent()` → invoke

### Multi-Skill Auto-Selection Test

```bash
cd backend && uv run python scripts/test_multi_skill_auto_select.py
```

Three tests proving the agent auto-selects the correct skill from multiple equipped options using a **generic system prompt** (no hardcoded skill names):

| Test | Query | Skill Expected | Result |
|------|-------|---------------|--------|
| 1 | "Order #12345 is 3 weeks late!" | **ticket-classifier** | ✅ Shipping keywords |
| 2 | "Analyze CSV and chart sales by month" | **data-analysis** | ✅ Data keywords |
| 3 | "Review this Python SQL injection code" | **code-review** | ✅ Security keywords |

Key: `create_deep_agent(skills=[path])` → SkillsMiddleware injects `## Skills System` listing all skill names+descriptions → LLM reads descriptions → selects matching skill → loads full SKILL.md instructions.

---

### Full Process Diagram: Ticket-Classifier Example

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    TICKET CLASSIFIER — COMPLETE FLOW                        │
└─────────────────────────────────────────────────────────────────────────────┘

═══ STEP 1: Create Skill ══════════════════════════════════════════════════════

  ┌─ User Action ───────────────────────────────────────────────────────┐
  │  Skills Panel → "New Skill" → fill:                                 │
  │    skill_id:  "ticket-classifier"                                    │
  │    name:      "ticket-classifier"                                    │
  │    tags:      ["support", "classification", "ticket"]               │
  │    instructions: "# Ticket Classifier\n## Rules\n..."               │
  └──────────────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌─ API ───────────────────────────────────────────────────────────────┐
  │  POST /api/skills → PostgreSQL (skills table)                       │
  └──────────────────────────────────────────────────────────────────────┘


═══ STEP 2: Create Agent + Bind Skill ═════════════════════════════════════════

  ┌─ User Action ───────────────────────────────────────────────────────┐
  │  Agent Builder → "New Deep Agent"                                   │
  │    1. System Prompt: "Classify tickets according to equipped skills"│
  │    2. Skills section → "Add Skills" → check "ticket-classifier"    │
  │    3. use_local_sandbox: true (auto-enabled)                       │
  │    4. Save                                                          │
  └──────────────────────────────────────────────────────────────────────┘
         │
         ▼
  ┌─ API ───────────────────────────────────────────────────────────────┐
  │  POST /api/deepagents                                                │
  │  config: { skills: ["ticket-classifier"], use_local_sandbox: true }  │
  │  → PostgreSQL (deep_agent_templates)                                 │
  └──────────────────────────────────────────────────────────────────────┘


═══ STEP 3: Runtime — deepagent_factory.py ════════════════════════════════════

  User clicks "Test" → POST /api/chat/start
         │
         ▼
  ┌─ deepagent_factory.py ──────────────────────────────────────────────┐
  │  1. Read agent config from DB (skills: ["ticket-classifier"])       │
  │  2. Init sandbox dir (outputs/default/skills/)                      │
  │  3. Query Skill records from DB by skill_id                         │
  │  4. Generate SKILL.md on sandbox filesystem                         │
  │  5. Inject skill hint into system_prompt                            │
  │  6. create_deep_agent(skills=[sandbox_path])                        │
  └──────────────────────────────────────────────────────────────────────┘


═══ STEP 4: SkillsMiddleware (deepagents lib) ═════════════════════════════════

  create_deep_agent(skills=[path])
         │
         ▼
  ┌─ SkillsMiddleware ───────────────────────────────────────────────────┐
  │  1. Scan skills/ dir for SKILL.md files                             │
  │  2. Parse YAML frontmatter (name, description, tags...)             │
  │  3. Progressive disclosure: expose name+desc to LLM                 │
  │  4. LLM decides when to load full instructions                      │
  └──────────────────────────────────────────────────────────────────────┘


═══ STEP 5: User Chat → Skill Triggers ═══════════════════════════════════════

  User: "Order #12345 is 3 weeks late! This is ridiculous!"
         │
         ▼
  ┌─ LLM Reasoning ─────────────────────────────────────────────────────┐
  │  1. Matches "ticket-classifier" description                        │
  │  2. Loads full classification rules                                 │
  │  3. Applies rules → Priority: High, Category: Shipping             │
  │  4. Returns structured JSON classification                         │
  └──────────────────────────────────────────────────────────────────────┘


═══ DATA FLOW SUMMARY ═════════════════════════════════════════════════════════

  PostgreSQL          Filesystem                   Runtime
  ┌────────┐         ┌──────────────┐           ┌──────────────────┐
  │ skills │──sync──▶│ SKILL.md     │──load──▶  │ SkillsMiddleware  │
  │   DB   │         │  (sandbox)   │           │ (progressive)     │
  └────────┘         └──────────────┘           └────────┬─────────┘
  ┌────────┐                                              │
  │ agents │──config.skills──────────────────────────────▶│ LLM knows
  │   DB   │  ["ticket-classifier"]                       │ available
  └────────┘                                              │ skills
                                                          ▼
  ┌────────┐                                     ┌──────────────────┐
  │ skills │──instructions──────────────────────▶│ Full skill text  │
  │   DB   │  "# Ticket Classifier..."            │ injected into    │
  └────────┘                                     │ LLM context      │
                                                  └──────────────────┘
```

---

### Phase 2: Make Skill ↔ Prompt Connection Visible (Medium Impact, Medium Effort)

**Goal**: Make skill injection visible in the prompt assembly view and support prompt templates in skill instructions.

#### 2.1 Show skill segments in PromptCanvas

**Files**: [`src/pages/PromptAssemblyPage.tsx`](../../src/pages/PromptAssemblyPage.tsx), [`src/features/agents/ui/PromptCanvas.tsx`](../../src/features/agents/ui/PromptCanvas.tsx)

Changes:
- When an agent has `enable_skills: true`, `PromptCanvas` fetches the skill instructions
- Skill instructions appear as additional segments: `USER → BASE → [Skill: code-review] → [Skill: testing] → SUFFIX`
- Each skill segment shows: name, description, instructions preview
- User can see exactly what prompt content each skill contributes
- Calls `POST /api/deepagents/prompt-preview` with skills included → backend resolves skills and returns segments

**Backend**: Extend `/api/deepagents/prompt-preview` to accept `skill_ids` parameter and include resolved skill instructions as segments.

#### 2.2 Add prompt template variables to skills

**File**: [`src/features/agents/ui/SkillBuilderModal.tsx`](../../src/features/agents/ui/SkillBuilderModal.tsx)

Changes:
- Support `{{context}}`, `{{tools}}`, `{{user_input}}`, `{{date}}` in instructions
- Add a "Variables" info panel showing available template variables
- Live preview of rendered instructions

**Backend**: No changes — variable substitution happens at runtime in `_inject_skills()`. Just need an info panel in the UI.

---

### Phase 3: Prompt as First-Class Entity (High Impact, High Effort)

**Goal**: Extract prompts from JSON blobs into a proper database entity that agents and skills can reference.

#### 3.1 Create `prompts` table

**File**: `backend/models/prompt.py` (new)

```python
class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)       # With {{variable}} placeholders
    variables = Column(JSON, default=list)        # List of {name, type, default, description}
    version = Column(Integer, default=1)
    tags = Column(JSON, default=list)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

#### 3.2 Create prompts API

**File**: `backend/api/prompts/routes.py` (new)

Endpoints:
- `GET /api/prompts` — list all prompts
- `POST /api/prompts` — create prompt
- `GET /api/prompts/{id}` — get prompt detail (with all versions)
- `PUT /api/prompts/{id}` — update prompt (creates new version)
- `DELETE /api/prompts/{id}` — delete prompt
- `POST /api/prompts/{id}/render` — render prompt with variables

#### 3.3 Migrate agent configs to reference prompts

**Migration**: For existing agents, extract `system_prompt` → create `Prompt` record → store `prompt_id` in agent config.

**Files**:
- `backend/models/deep_agent.py` — add optional `system_prompt_id` field
- `backend/services/deepagent_factory.py` — resolve `prompt_id` → `Prompt.content` at runtime
- `backend/core/agents/factory.py` — resolve prompt references in `_construct_system_prompt_string()`

#### 3.4 Migrate skill instructions to reference prompts

**Migration**: For existing skills, option to convert `instructions` → `Prompt` record → store `prompt_id` in skill.

**Files**:
- `backend/models/skill.py` — add optional `instructions_prompt_id` field
- `backend/core/skills/registry.py` — resolve prompt reference when loading skills

#### 3.5 Make PromptAssemblyPage work standalone

**File**: [`src/pages/PromptAssemblyPage.tsx`](../../src/pages/PromptAssemblyPage.tsx)

Changes:
- Remove the requirement for `selectedAgentId`
- Add "New Prompt" flow: create prompt standalone
- Add "Link to Agent" or "Link to Skill" as secondary actions
- Listing view: all prompts in the system, filterable by tags

---

## File Change Summary

### ✅ All Completed Phases

| File | Change Type | Description |
|------|-------------|-------------|
| `src/features/agents/ui/DeepAgentBuilder.tsx` | **Add** | Skills section with toggle, picker modal, chips, auto-enable sandbox |
| `src/features/agents/ui/AgentLoadouts.tsx` | **Add** | Skills section + Skill Router model picker in AgentConfigView |
| `backend/models/deep_agent.py` | **Modify** | Added `skill_router_model` field to DeepAgentConfig |
| `backend/services/deepagent_factory.py` | **Modify** | Generic skill hint + Skill Router LLM + DB API key lookup |
| `backend/api/chat/routes.py` | **Modify** | Pass `user_message` to `create_deep_agent()` for routing; extract tool calls with `skill_name` |
| `backend/scripts/test_ticket_classifier.py` | **New** | End-to-end test: filesystem + DB → skill injection |
| `backend/scripts/create_ticket_skill.py` | **New** | Create ticket-classifier skill in PostgreSQL |
| `backend/scripts/test_multi_skill_auto_select.py` | **New** | Multi-skill auto-selection with generic prompt |
| `backend/scripts/test_skill_router.py` | **New** | Skill Router LLM test (5 scenarios, 100% accuracy) |
| `backend/scripts/update_ticker_prompt.py` | **New** | Update agent prompt to research agent pattern |
| `backend/scripts/set_skill_router.py` | **New** | Set `skill_router_model` on ticker_classifer |
| `backend/scripts/_update_prompt.py` | **New** | Update agent system prompt in DB |
| `rules.md` | **Modify** | Added filesystem-first testing methodology |
| `src/features/chat/types/chat.ts` | **Modify** | Added `skill_name` field to `ToolCall` and `ChatStreamEvent` |
| `src/features/chat/ui/GlobalChatModal.tsx` | **Modify** | Parse `skill_name` from SSE `tool_start` events during streaming |
| `src/features/chat/ui/MetricsPanel.tsx` | **Modify** | Display skill name badge next to each tool call (live + persisted) |
| `src/components/common/AgentChatTester.tsx` | **Modify** | Added `skill_name` to tool call tracking and display |
| `backend/scripts/test_subagent_skills.py` | **New** | Prove subagent+SkillsMiddleware isolation for multi-turn skills |

## ✅ Key Architecture Decisions

### 1. Skill Auto-Selection Works via SkillsMiddleware

The deepagents library's `SkillsMiddleware` handles progressive disclosure:
- It injects a `## Skills System` block listing all skill names + descriptions
- LLM reads descriptions and decides which skill to load via `read_file`
- System prompt only needs a generic instruction: *"You have SKILLS in /skills/. Use read_file to load..."*
- **No hardcoded skill names needed** in system prompt
- Works across 4+ skills (ticket-classifier, data-analysis, code-review, etc.)

## 🎯 Key Discovery: Skill-per-Subagent with Isolated SkillsMiddleware

**Status**: ✅ Proven via test script — all multi-turn skills tests pass.

### The Discovery

The deepagents framework's **SkillsMiddleware** is the key mechanism for progressive disclosure. It:
1. Scans `sources` directories for SKILL.md files
2. Reads YAML frontmatter → injects `<available_skills>` name+description catalog into system prompt
3. Intercepts `read_file("...SKILL.md")` → loads full instructions into LLM context

**The critical insight**: When you pass `skills` to the **main agent**, the main agent's `SkillsMiddleware` accumulates all loaded skills into one context. On turn 2+, the old skill instructions remain in the conversation history, poisoning the context.

**The fix**: Give each skill its **own subagent with its own isolated `SkillsMiddleware`**. The main agent stays clean — it delegates via `task()`:

```python
# NOT this (context bloat):
agent = create_deep_agent(skills=["/skills/"])  # ❌ all skills in one context

# BUT this (isolated):
subagents = []
for s in skill_records:
    skill_mw = SkillsMiddleware(
        backend=FilesystemBackend(root_dir=str(skills_root)),
        sources=[s.skill_id],  # only this skill's SKILL.md
        system_prompt=None,
    )
    subagents.append({
        "name": s.skill_id,
        "description": s.description,
        "middleware": [skill_mw],  # ← isolated SkillsMiddleware
    })

agent = create_deep_agent(
    subagents=subagents,  # each skill = one subagent
    # NO skills — main agent stays clean
)
```

### How SkillsMiddleware Works Under the Hood

```
SkillsMiddleware instance (per subagent)
  │
  ├── before_agent()     → reads SKILL.md frontmatter
  │                       → injects <available_skills> catalog
  │                       → [ticket-classifier] Classifies tickets...
  │
  └── modify_request()   → intercepts read_file("...SKILL.md")
                          → loads full instructions into this subagent only
                          → "## Ticket Classifier\n...classification rules..."
```

**Each subagent gets its own `SkillsMiddleware` with a separate `StateBackend` → skills state is fully isolated**. The main agent only sees the final result, not the skill instructions.

### Test Results (3/3 Passed)

| Turn | Subagent | SkillsMiddleware | Response Keywords |
|------|----------|-----------------|-------------------|
| 1 | `ticket-classifier` | `sources=[ticket-classifier]` | priority, category, sentiment |
| 2 | `code-review` | `sources=[code-review]` | SQL injection, security |
| 3 | `data-analysis` | `sources=[data-analysis]` | CSV, sales |

All 3 turns in the **same conversation thread**, no context pollution between turns.

### Architecture Diagram

```
Main Agent (clean context, no skills)
  system_prompt: "Delegate skill tasks using task()..."
  │
  ├── task("classify ticket", name="ticket-classifier")
  │   └── Subagent [ticket-classifier]
  │       └── SkillsMiddleware(sources=[ticket-classifier])
  │           → loads ticket-classifier/SKILL.md only
  │           → returns {priority, category, sentiment}
  │
  ├── task("review code", name="code-review")
  │   └── Subagent [code-review]
  │       └── SkillsMiddleware(sources=[code-review])
  │           → loads code-review/SKILL.md only
  │           → returns security review
  │
  └── task("analyze CSV", name="data-analysis")
      └── Subagent [data-analysis]
          └── SkillsMiddleware(sources=[data-analysis])
              → loads data-analysis/SKILL.md only
              → returns analysis
```

### Key Advantage: Dynamic from DB

Both the delegation hints AND subagents are generated dynamically from `skill_records`:

```python
delegation_hints = "\n".join(
    f"  - {s.skill_id}: {s.description}" for s in skill_records
)
# New skill in DB → auto-appears in hints + gets its own subagent
# Remove from DB → auto-disappears
```

### What We Learned

| Approach | Result | Why |
|----------|--------|-----|
| **Single agent + skills** | ❌ Multi-turn fails | Context accumulation poisons subsequent turns |
| **Subagent per skill** | ✅ 3/3 passes | Each subagent has isolated SkillsMiddleware |
| `SkillsMiddleware` via `skills=[]` | ✅ Works | Framework auto-creates it |
| `SkillsMiddleware` via `middleware=[]` | ✅ Works | We construct it manually (same effect) |

---

## ✅ Phase 2.3 — Skill Router LLM (Completed)

**Status**: ✅ Fully implemented and tested with 100% accuracy.

A separate LLM (deepseek) routes the user's message to the correct skill before the main agent loads it:

```
User message
     │
     ▼
┌─ Skill Router LLM (deepseek) ─────────────────────┐
│  Classifies user request against skill descriptions │
│  → "ticket-classifier"                              │
└────────────────────────────────────────────────────┘
     │
     ▼
┌─ Main Agent LLM (agnes) ───────────────────────────┐
│  Only the matched SKILL.md is loaded               │
│  Agent focuses entirely on the task                 │
└────────────────────────────────────────────────────┘
```

### Design Options

| Option | Pro | Con |
|--------|-----|-----|
| **Middleware**: Custom middleware before SkillsMiddleware | Transparent, no agent changes | Requires understanding deepagents middleware chain |
| **Pre-process**: Factory picks router LLM before `create_deep_agent()` | Simple, minimal changes | Two LLM calls; adds latency |
| **Config field**: `skill_router_model` in agent config | User-configurable | More UI work |

### ✅ Implementation — Skill Router LLM (Phase 2.3)

**Status**: Completed and tested with 100% accuracy on 5 scenarios.

The router is implemented in `deepagent_factory.py` as `DeepAgentFactory._run_skill_router()`:

```python
# In deepagent_factory.py, before calling create_deep_agent():
if config.skill_router_model and user_message and skill_records:
    matched_skill = await DeepAgentFactory._run_skill_router(
        router_model=config.skill_router_model,  # e.g. "deepseek:deepseek-chat"
        skill_records=loaded_skills,
        user_message=user_message,
    )
    if matched_skill:
        skills_config = [matched_skill]
        # Remove unmatched skill directories from sandbox
        for s in loaded_skills:
            if s.skill_id != matched_skill:
                shutil.rmtree(skill_dir, ignore_errors=True)
```

Key features:
- **API keys from DB**: Uses `get_api_key_from_db()` to fetch provider keys (not env vars)
- **Model-agnostic**: Works with `deepseek:` or `agnes:` prefixed model names
- **Graceful fallback**: If router fails or returns invalid skill, falls back to all skills
- **User message**: Passed from chat routes → `create_deep_agent()` → router

### Phase 3: Planned (High Effort)

| File | Change Type | Description |
|------|-------------|-------------|
| `backend/models/prompt.py` | **New** | Prompt ORM model |
| `backend/api/prompts/routes.py` | **New** | Prompts CRUD API |
| `backend/models/deep_agent.py` | **Modify** | Add `system_prompt_id` |
| `backend/models/skill.py` | **Modify** | Add `instructions_prompt_id` |
| `backend/core/agents/factory.py` | **Modify** | Resolve prompt references |
| `backend/services/deepagent_factory.py` | **Modify** | Resolve prompt references |
| `src/pages/PromptAssemblyPage.tsx` | **Modify** | Standalone mode |
| `backend/db/database.py` | **Modify** | Register Prompt model |

---

## LangChain Concept Mapping

| LangChain Concept | Current LangConfig | Target LangConfig |
|---|---|---|
| `PromptTemplate` | String in JSON | `Prompt` entity with `{{variables}}` |
| `PromptTemplate.partial()` | N/A | Runtime variable resolution |
| `Hub` (prompt sharing) | N/A | Prompt Library with tags/search |
| `BaseTool` | `ToolFactory` / `native_tools.py` | ✅ No change needed |
| `create_react_agent` | LangChain Agent mode | ✅ No change needed (but UI should name this clearly) |
| `StateGraph` | Workflow Canvas | ✅ No change needed |
| `interrupt_before` / checkpoint | HITL middleware | ✅ No change needed |
| Agent with skills | Disabled by default | Skill picker → `enable_skills: true` |
| Agent with memory | `enable_memory` toggle | ✅ Already in UI |
| Agent with RAG | `enable_rag` toggle | ✅ Already in UI |
| `Runnable` composition | Middleware stack | ✅ No change needed |

---

## Principles for Implementation

1. **UI-first normalization**: Don't change backend abstractions — build UI that activates existing capabilities. The backend is solid; the UI needs to expose what's already there.

2. **Skill is the composition unit**: Skill should be the smallest reusable unit of agent capability that users create, share, and compose. A skill = prompt + tools + triggers.

3. **Every connection must be visible**: If skill instructions are injected into the system prompt, the user must be able to see this in the Prompt Canvas. If a skill references tools, the user must see this in the Skill Builder.

4. **No new backend abstractions unless necessary**: Phase 1 requires zero backend changes. Phase 2 requires minimal backend changes. Only Phase 3 requires significant backend work (prompts table).

5. **Follow project rules**: All config in PostgreSQL (no new enums), Settings Panel as single entry point, implement in test-first order.

---

## References

- [Skill DB Model](../../backend/models/skill.py) — `Skill` table with full schema
- [Skill Registry](../../backend/core/skills/registry.py) — In-memory cache + DB CRUD
- [Skill Injector](../../backend/core/agents/factory.py#L848) — `_inject_skills()` runtime logic
- [Agent Factory](../../backend/core/agents/factory.py#L607) — `enable_skills` config read
- [DeepAgent Builder UI](../../src/features/agents/ui/DeepAgentBuilder.tsx) — Agent config form
- [Skill Builder UI](../../src/features/agents/ui/SkillBuilderModal.tsx) — Skill create/edit form
- [Skill Library UI](../../src/features/skills/ui/SkillLibrary.tsx) — Skill browsing
- [Prompt Canvas UI](../../src/features/agents/ui/PromptCanvas.tsx) — Prompt segment viewer
- [Prompt Assembly Page](../../src/pages/PromptAssemblyPage.tsx) — Prompt editing page
- [Navigation Header](../../src/components/layout/ModernHeader.tsx) — All nav tabs (Agents, Prompt, Skills, Tools)
- [Project Rules](../../rules.md) — Development guidelines

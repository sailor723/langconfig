# LangConfig

AI Agent configuration platform with dynamic model management, skills library, and multi-agent execution modes.

## Quick Start

```bash
# Backend
cd backend
.venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8765

# Frontend (port 1421 — layout2 VS Code-style shell)
cd ..
npx vite

# Or use the start script
bash start.sh
```

## Architecture

```
UI (React/Vite) ──→ BE (FastAPI/uvicorn) ──→ PostgreSQL 5432
                        │
                   Agent Factory
                        │
              ┌─────────┼─────────┐
              │         │         │
         Playground  LangChain  DeepAgent
        (model.invoke)  Agent    (skills+sandbox)
```

## VS Code-Style IDE Shell (layout2)

The UI has been refactored from a top-nav web layout to a **VS Code-inspired IDE shell**:

```
┌──────┬────────────┬───────────────────────┬──────────────┐
│ Act  │ Side Bar   │ Editor                │ Right Panel  │
│ Bar  │ (explorer/ │ (tabs + content)      │ Chat / Props │
│      │  search)   ├───────────────────────┤              │
│      │            │ Terminal / Exec / Results            │
├──────┴────────────┴───────────────────────┴──────────────┤
│ Status Bar (#007acc blue, full width)                    │
└──────────────────────────────────────────────────────────┘
```

| Component | Description |
|-----------|-------------|
| ActivityBar | 48px left icon strip (#181818), 6 activities (Workflows, DeepAgents, Agents, Library, Analysis, Settings) |
| LeftSidebar | Resizable (200-600px) file explorer + search panel |
| Workspace | Tabbed editor (drag-reorder, middle-click close, dirty dot) |
| NodeSidebar | Right panel (240-800px) — Chat + Properties tabs |
| BottomPanel | Terminal / Execution / Results (collapsible, 200px) |
| StatusBar | 22px blue (#007acc) bar with model + token + task info |

Live at `http://localhost:1421`. See [`src/components/layout2/README.md`](src/components/layout2/README.md) for full details (Phases 1-12 implemented).

## 3 Agent Execution Modes

| Mode | Backend | Description |
|---|---|---|
| **Playground** | `POST /api/models/invoke` | Raw `model.invoke()` — no tools, no agent |
| **LangChain Agent** | `AgentFactory.create_agent()` | Standard agent with tools, no sandbox/skills |
| **DeepAgent** | `create_deep_agent()` | Full agent with tools + skills + sandbox + middleware |

## Agent & Skill Generator CLI

One-shot agent creation from natural language. Uses `agent_gen_agent` (ID=69) to parse queries and auto-generate missing skills.

### SDK (`lib/langconfig_sdk/`)

```python
from langconfig_sdk import LangConfigClient

client = LangConfigClient()
agent = client.generate_agent("my-agent", skills=["ticket-classifier", "data-analysis"])
```

### CLI (`backend/scripts/agent_gen_cli.py`)

```bash
# Natural language — creates agent + auto-generates missing skills
cd backend && python scripts/agent_gen_cli.py create --name support-agent \
  -q "ticket classification, data analysis and web search"

# Explicit skill IDs (skip parsing)
python scripts/agent_gen_cli.py create --name support-agent \
  --skills ticket-classifier,data-analysis

# List agents / skills
python scripts/agent_gen_cli.py list-agents
python scripts/agent_gen_cli.py list-skills

# Dry-run (check only)
python scripts/agent_gen_cli.py create --name test --skills a,b,c --dry-run
```

### Flow

```
User query → agent_gen_agent (ID=69) parses NL → skill IDs extracted
    → check DB → missing? → create_skill() API → create agent
    → agent created with: middleware, subagents, local_sandbox
```

### Key SDK Methods

| Method | Description |
|---|---|
| `parse_query_to_skills(query)` | Uses agent_gen_agent to extract skill IDs from natural language |
| `create_skill(skill_id)` | Creates a skill in DB (auto-increments version if exists) |
| `create_agent(name, skills)` | Creates DeepAgent with auto-versioning (duplicate → -v2 suffix) |
| `skill_exists(skill_id)` | Check if skill exists in DB |
| `ensure_skills(ids)` | Create missing skills, return available list |
| `generate_agent(name, skills)` | ensure_skills + create_agent in one call |

### Version Control

- **Agents**: Duplicate names auto-append `-v2`, `-v3` suffix
- **Skills**: Duplicate IDs auto-increment version (`1.0.0` → `2.0.0`)
- Both stored in `config.version` field

## Model Management (Phase 5 — DB-Driven)

All model configuration is stored in PostgreSQL — no hardcoded enums.

```
models table (unified)
├── source='cloud'  → 21 models (seeded from scripts/seeds/seed_models.py)
│   Providers: openai, anthropic, deepseek, google, agnes, glm, minimax
└── source='local'  → user-configured (Ollama, LM Studio, vLLM, etc.)
    Added via Settings > Local Models UI
```

### Key Changes

| Before | After |
|---|---|
| `constants/models.py` enum (hardcoded) | `models/model.py` → PostgreSQL `models` table |
| `PROVIDER_MODELS` in PlaygroundPage.tsx | Dynamic from API `/api/settings/models` |
| `modelDisplayNames` in useAvailableModels.ts | `display_name` from DB seed data |
| `startswith()` routing in factory.py | `provider` field lookup from DB |
| 30s API timeout | 300s (5min) for agent responses |

### Adding a New Model

```sql
INSERT INTO models (model_id, display_name, provider, source, capabilities, is_active)
VALUES ('new-model', 'New Model', 'openai', 'cloud', '{"streaming": true}', true);
```

Or use Settings > API Keys to configure a new provider. No code changes needed.

## Skills Library

- 15 builtin + 20 personal/user-created skills stored in PostgreSQL (35 total on disk)
- Skills synced to agent sandbox at creation time (progressive disclosure)
- Agent reads `SKILL.md` on demand — meta-skill `skill-generator` can create new skills

## Recent Commits

- `bc08cb0` — Phase 7: Chinese preset chips + mock weather for Chinese cities
- `50570f2` — Phase 7: Playground preset query chips + tool calling + image support
- `ab100c0` — Phase 7: Playground popup modal opened via Play button
- `9f23e9c` — Phase 7: DeepSeek V4 + enriched model cards
- `e400ec4` — Phase 7: Model Cards — Set As Default flow
- `1a9bd84` — Phase 7: Model Cards panel to Settings
- `d6cea9f` — Phase 6: migrate API keys and model config from DB to .env
- `7ada47c` — Phase 4: agent-generated skills + Skills Library UI
- `21c164d` — Phase 3: DeepAgent skills with DB→sandbox sync
- `0aa08e6` — Phase 2: data-analysis skill
- *(previous)* — Phase 5: DB-driven model management (remove hardcoded enums)

## Phase 7 — Model Cards + Playground

See [`phase7/README.md`](phase7/README.md) for full details.

**Highlights:**
- **Model Cards panel** with provider logos, capability badges, pricing, speed, strength tagline
- **Set As Default** flow with live header badge
- **Playground popup modal** (▶ Play button) with system prompt, temperature, top_p, penalties, stop, JSON mode, tool calling, streaming, image input
- **8 preset chips** (Chinese-localized): 打招呼 / 数学 / JSON / 工具 / 搜索 / 流式 / 视觉 / 推理 — one-click demos with auto-send
- **4 mock demo tools** (no external API): get_weather (10 Chinese cities), get_current_time, search_web, calculate
- **Tool-calling agent loop** (max 3 turns) with structured tool call log returned to UI
- **Multimodal vision support** via `image_url` field
- **26 cloud models** with realistic 2026 specs (DeepSeek V4 Pro/Flash, GPT-5.5, Claude 4.8/4.6, Gemini 3.1 Pro, Qwen 3.5/3.6, Kimi K2.6, GLM 5.1, MiniMax M3, Gemma 4, etc.)

## Tests

```bash
cd backend
.venv/bin/python3 -m pytest tests/test_models_db_refactor.py -v
```

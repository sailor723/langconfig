# LangConfig

AI Agent configuration platform with dynamic model management, skills library, and multi-agent execution modes.

## Quick Start

```bash
# Backend
cd backend
.venv/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8765

# Frontend
cd ..
npx vite
```

## Architecture

```
UI (React/Vite) ──→ BE (FastAPI/uvicorn) ──→ PostgreSQL 5433
                        │
                   Agent Factory
                        │
              ┌─────────┼─────────┐
              │         │         │
         Playground  LangChain  DeepAgent
        (model.invoke)  Agent    (skills+sandbox)
```

## 3 Agent Execution Modes

| Mode | Backend | Description |
|---|---|---|
| **Playground** | `POST /api/models/invoke` | Raw `model.invoke()` — no tools, no agent |
| **LangChain Agent** | `AgentFactory.create_agent()` | Standard agent with tools, no sandbox/skills |
| **DeepAgent** | `create_deep_agent()` | Full agent with tools + skills + sandbox + middleware |

## Model Management (Phase 5 — DB-Driven)

All model configuration is stored in PostgreSQL — no hardcoded enums.

```
models table (unified)
├── source='cloud'  → 21 models (seeded from seed_models.py)
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

- 17 builtin + user-created skills stored in PostgreSQL
- Skills synced to agent sandbox at creation time (progressive disclosure)
- Agent reads `SKILL.md` on demand — meta-skill `skill-generator` can create new skills

## Recent Commits

- `7ada47c` — Phase 4: agent-generated skills + Skills Library UI
- `21c164d` — Phase 3: DeepAgent skills with DB→sandbox sync
- `0aa08e6` — Phase 2: data-analysis skill
- *(current)* — Phase 5: DB-driven model management (remove hardcoded enums)

## Tests

```bash
cd backend
.venv/bin/python3 -m pytest tests/test_models_db_refactor.py -v
```

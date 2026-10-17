# LangConfig

A local-first, self-hosted platform for building, running and inspecting AI agents and
workflows. Visual canvas + a VS Code-style IDE shell on top of **LangChain v1**,
**LangGraph** and **deepagents**. Everything — models, keys, agents, skills — lives in
your own PostgreSQL, so nothing leaves the machine.

```
┌──────┬────────────┬───────────────────────┬──────────────┐
│ Act  │ Side Bar   │ Editor                │ Chat /       │
│ Bar  │ (explorer/ │ (tabs + content)      │ Doc Chat /   │
│      │  search)   ├───────────────────────┤ Properties   │
│      │            │ Terminal / Exec / Results            │
└──────┴────────────┴───────────────────────┴──────────────┘
```

---

## Documentation

| Doc | What it answers |
|---|---|
| **[docs/usage.md](docs/usage.md)** | How to use it — the shell, the thirteen activities, first-agent and first-workflow walkthroughs |
| **[docs/installation.md](docs/installation.md)** | Install **and** update: local development, team install from a zip, and the seed out → push → pull → seed loop (plus a [Chinese edition](docs/installation.zh-CN.md)) |
| **[docs/system-architecture.md](docs/system-architecture.md)** | How it works — five-layer model, agent build pipeline, execution engine, data layer ([Chinese edition](docs/system-architecture.zh-CN.md)) |
| [docs/reference/](docs/reference/) | Deeper reference: storage map, data taxonomy, skill authoring, settings and tools design notes, studies and audits |
| [REFACTORING.md](REFACTORING.md) | Backend refactor history and known gaps |

---

## Quick start

**Prerequisites:** Python 3.13 · Node 24+ · PostgreSQL 16 with `pgvector`.

```bash
bash start.sh          # PostgreSQL + backend :8765 + frontend :1421
```

Or run the halves yourself:

```bash
cd backend && .venv/bin/python -m uvicorn main:app --port 8765   # API
npm run dev                                                      # UI
```

| Service | URL |
|---|---|
| IDE shell | http://localhost:1421 |
| API | http://localhost:8765 |
| Swagger / OpenAPI | http://localhost:8765/docs |
| Health | http://localhost:8765/api/chat/health |

Open the UI, then **Settings → API Keys** to add a provider key — keys are stored
encrypted in PostgreSQL, *not* in `.env`. Details in
[docs/installation.md](docs/installation.md).

---

## Three ways to run an agent

| Mode | Backend | What it is |
|---|---|---|
| **Playground** | `POST /api/models/invoke` | Raw `model.invoke()` — no tools, no agent, no memory |
| **LangChain Agent** | `AgentFactory.create_agent()` | Standard agent: prompt + tools |
| **DeepAgent** | `create_deep_agent()` | Tools + skills + filesystem sandbox + middleware + subagents |

Both agent kinds are rows in one `deep_agent_templates` table; a single flag
(`use_deepagents`) decides which runtime builds them. **Workflows** are the fourth mode: a
canvas graph of agent/tool/conditional nodes executed by LangGraph with Postgres
checkpointing.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 · TypeScript · Tailwind 4 · ReactFlow · Vite |
| Backend | Python 3.13 · FastAPI · LangChain v1 · LangGraph · deepagents 0.7.1 |
| Database | PostgreSQL 16 · pgvector · SQLAlchemy · Alembic |

**45 routers, 291 paths.** 48 tables. Agents, tools (64 built-in) and skills (43) are
seeded into the database and compiled from it at runtime — adding a model or a tool needs
no code change.

## Repository layout

| Path | Contents |
|---|---|
| `backend/api/` | REST + SSE routers |
| `backend/core/agents/factory/` | `AgentFactory` |
| `backend/services/deepagent_factory/` | `DeepAgentFactory` |
| `backend/core/workflows/executor/` | Workflow execution engine |
| `backend/core/settings/` | Namespaced settings documents |
| `src/components/layout2/` | IDE shell |
| `src/features/` | Canvas, chat, graph studio, knowledge, tools |
| `docs/` | Documentation (see above) |

## Tests

```bash
cd backend && .venv/bin/python -m pytest \
  --ignore=tests/test_neo4j_document_enrichment.py \
  --ignore=tests/test_pageindex_full_content_loader.py
npm run build
```

591 passed · 3 failed (pre-existing) · 18 skipped. The two ignores are stale modules that
break collection — see [REFACTORING.md](REFACTORING.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
Licensed under [MIT](LICENSE).

# LangConfig

Visual platform for building LangChain agents and LangGraph workflows.

## Stack

- **Frontend:** React 19 + TypeScript + Tailwind CSS 4 + ReactFlow (`src/`)
- **Backend:** Python 3.13 + FastAPI + LangChain v1.0 + LangGraph + deepagents 0.7.1 (`backend/`)
- **Database:** PostgreSQL 16 + pgvector + Alembic

## Commands

```bash
# Start development
bash start.sh                      # One-shot launcher: backend :8765 + frontend :1421
cd backend && uv run python main.py  # API server only :8765
npm run dev                        # Frontend only :1421

# Database
docker-compose up -d postgres      # Start PostgreSQL (or native on :5432)
cd backend && uv run alembic upgrade head # Run migrations

# Testing
cd backend && uv run pytest        # Backend tests
npm run build                      # Frontend build check
```

## Key Paths

| Path | Purpose |
|------|---------|
| `backend/core/workflows/executor/` | Workflow execution engine (mixin package: `execution.py`, `builder.py`, `nodes.py`) |
| `backend/core/agents/factory/` | Normal-agent creation (`AgentFactory.create_agent`) |
| `backend/services/deepagent_factory/` | DeepAgent creation (`DeepAgentFactory.create_deep_agent`) |
| `backend/api/` | REST API routes (49 routers registered in `main.py`) |
| `backend/models/` | SQLAlchemy ORM models |
| `backend/services/` | Business logic services |
| `src/features/workflows/` | Workflow canvas UI |
| `src/features/agents/` | Agent builder UI |
| `src/hooks/` | React hooks (useWorkflowStream, etc.) |

## API

- Base URL: `http://localhost:8765`
- Swagger docs: `http://localhost:8765/docs`
- Key endpoints:
  - `POST /api/orchestration/execute` - Run workflow (SSE)
  - `POST /api/chat/message/stream` - Chat with an agent (SSE)
  - `POST /api/rag/upload` - Upload a document to a RAG collection
  - `GET /signin` - Sign-in page (session cookie); `POST /api/auth/login` / `logout`
  - `GET /api/users/me` - Who is calling (session cookie or Basic via the LAN gate; loopback = owner)
  - `GET /api/users` - Account list and management (admin only)

## Shell Commands (Important!)

Development happens on **macOS** or **WSL2 + Ubuntu** with **bash syntax** (Git Bash/WSL on Windows, plain bash on macOS).

```bash
# CORRECT (bash syntax)
test -f .env && echo "exists" || echo "missing"
ls -la .env 2>/dev/null
grep "PATTERN" file.txt
cat file.txt | head -20
```

**Python commands:** Always use the project venv for consistency:

```bash
cd backend && .venv/bin/python -m pip install package
cd backend && .venv/bin/python -c "import module"
```

Or with uv: `cd backend && uv run python -c "import module"`

**Environment files:** There is ONE `.env` file:
- `/.env` - Project root. Used by frontend, docker, AND backend (FastAPI loads it via `backend/config.py` → `load_dotenv(../../.env)` + pydantic-settings `env_file`).

All API keys and infrastructure config live in the root `.env`. The previous `backend/.env` has been removed — any secrets that used to live there must be moved to the root file.

## DSH trains, Carrier runs

This repository is both a product (Carrier / LangConfig) and the thing an outside
harness authorises. The division is deliberate and was learned the hard way:

- **DSH (the harness) is where agents, skills, tools and prompts are built and
  validated.** It has the repository, a shell, the database, the browser and the test
  suite — i.e. every piece of evidence needed to decide whether a change is real.
- **Carrier is where those artefacts run.** An in-app agent sees only its own tool
  results: when a tool is not bound, a path is refused or a skill is stale, all it can
  report is "this failed". It cannot read `services/deepagent_factory/assembly.py`,
  restart the process, or reseed a tool row.

So the loop is: **an in-app agent reports what is missing → DSH fixes the platform →
refresh → verify with a real turn.** An agent that starts working around a platform
gap is a signal that the gap belongs to DSH, not that the agent needs more prompting.

What "train" means here, concretely:

| Artefact | Where it lives | How a change becomes visible |
|---|---|---|
| agent (prompt, tools, skills, guardrails) | `deep_agent_templates` | rewrite the row, then prove it with a real streaming turn |
| prompt body | same row, plus `backend/scripts/set_agent_prompt.py` | the machine tail is rebuilt from the row, never hand-edited |
| skill | `backend/skills/builtin/<id>/SKILL.md` | `POST /api/skills/reload-all` — a running registry does not notice a new file |
| native tool | `backend/tools/native_impl.py` + `SEEDABLE_TOOL_META` | `scripts/seeds/in/seed_builtin_tools.py --refresh`, then restart |
| behaviour that must not regress | `backend/tests/` | a guard test, because a prompt is not a gate |

Worked example (2026-11-11, the table-building agent): it reported 「我没有列目录的工具」 —
true, `glob` was in its config but the platform drops native fs tools when a disk backend is
active, and the SDK's set had no listing either. The fix was a `list_files` tool named so
that rule cannot remove it, a sandbox resolver for relative paths, and a reseed — none of
which the agent could do from inside a conversation. The handoff, not the prompting, was the
work.

## Detailed Docs

See `docs/` for architecture and design documentation:

| File | Contents |
|------|----------|
| `docs/system-architecture/system-architecture.md` | System design, five-layer model, agent landscape, storage strategy |
| `docs/installation/installation.md` | Install and update: local dev, team zip, and the seed out → push → pull → seed loop |
| `docs/usage.md` | User guide: the shell, the 14 activities, first-agent / first-workflow walkthroughs |
| `docs/system-architecture/` | How the system is built: storage map, data taxonomy, skill authoring, settings/tools design, audits, studies |
| `docs/tutorial/` | Training material: the 12-case run book, its HTML build, and the deep-research report template |
| `docs/installation/` | Install/update, Google OAuth, LAN access |
| `docs/assets/` | Diagrams for the run book (`.dot` sources + rendered `.svg/.png/.pdf`) |
| `docs/system-architecture/ecosystem-skills-plan-2026-11-09.md` | The upstream skill port: what was read, the ecosystem layer rules, and what the generated skills changed |
| `docs/system-architecture/skills-and-tools-review-2026-11-09.md` | Skills and tools review: the honest-skill test, and what to adopt / install next |
| `docs/system-architecture/sunhing-dashboards.md` | Sun Hing dashboard generation (deterministic generator, producer map, 28-KPI coverage, UI wiring) |
| `docs/installation/lan-access.md` | Letting other people use this instance over the network: the LAN gate, the /signin page and its sessions, what stays shared, and why per-user data is a rebuild |
| `REFACTORING.md` | Backend refactor status (god-module splits, verification methodology) |
| `docs/system-architecture/OKF_MINIMAL_PROFILE.md` | OKF knowledge-bundle profile (local-only, not committed) |
| `docs/system-architecture/PAGEINDEX_OKF_DESIGN.md` | PageIndex + OKF knowledge design note (local-only, not committed) |
| `backend/README.md` | Backend-specific setup |

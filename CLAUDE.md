# EBL Carrier

> Product: **EBL Carrier** (short: Carrier). Repo/package names still say `langconfig`.

Visual platform for building LangChain agents and LangGraph workflows.

> Note: `AGENTS.md` is the canonical agent instruction file for this repo.
> This file mirrors it (kept in sync; update both when facts change).

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
| `backend/api/` | REST API routes (43 routers registered in `main.py`) |
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
  - `POST /api/knowledge/documents` - Upload RAG document
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

## Detailed Docs

See `docs/` for architecture and design documentation:

| File | Contents |
|------|----------|
| `docs/system-architecture/system-architecture.md` | System design, five-layer model, agent landscape, storage strategy |
| `docs/installation/installation.md` | Install and update: local dev, team zip, and the seed out → push → pull → seed loop |
| `docs/usage.md` | User guide: the shell, the 13 activities, first-agent / first-workflow walkthroughs |
| `docs/system-architecture/` | How the system is built: storage map, data taxonomy, skill authoring, settings/tools design, audits, studies |
| `docs/tutorial/` | Training material: the 12-case run book, its HTML build, and the deep-research report template |
| `docs/installation/` | Install/update, Google OAuth, LAN access |
| `docs/assets/` | Diagrams for the run book (`.dot` sources + rendered `.svg/.png/.pdf`) |
| `docs/system-architecture/sunhing-dashboards.md` | Sun Hing dashboard generation (deterministic generator, producer map, 28-KPI coverage, UI wiring) |
| `docs/installation/lan-access.md` | Letting other people use this instance over the network: the LAN gate, the /signin page and its sessions, what stays shared, and why per-user data is a rebuild |
| `REFACTORING.md` | Backend refactor status (god-module splits, verification methodology, security-fix pass) |
| `docs/system-architecture/OKF_MINIMAL_PROFILE.md` | OKF knowledge-bundle profile (local-only, not committed) |
| `docs/system-architecture/PAGEINDEX_OKF_DESIGN.md` | PageIndex + OKF knowledge design note (local-only, not committed) |
| `backend/README.md` | Backend-specific setup |

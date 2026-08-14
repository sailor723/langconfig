# LangConfig Development Rules

## Settings & Configuration

### Rule 1: Two homes for settings — DB for product config, `.env` for secrets
Application configuration splits by ownership:
- **Product settings** (default model, model catalog, local model configs, search providers, temperature/token defaults) live in PostgreSQL — the `settings` and `models` tables.
- **Secrets** (API keys, base URLs, DB connection, infra config) live in the root `.env` file, loaded by `backend/config.py` (`Settings(BaseSettings)`). This is the Phase 6 migration: API keys were moved from DB to `.env`; the `settings` table does not hold keys anymore.

### Rule 2: No hardcoded enums for model/settings values
- Do **not** define Python enums or constants for model names, providers, or pricing.
- The `models` table (source: `cloud` | `local`) is the source of truth for the model catalog, seeded from `scripts/seeds/seed_models.py` CSV — no code changes needed to add a model.

### Rule 3: Settings Panel is the single entry point
The **only** way to update product settings in the database is through the **Settings Panel** UI or its corresponding API endpoints (`/api/system/settings/*`). No code should programmatically write to the `settings` table outside of the settings API.

### Rule 4: Read from DB at runtime
Any component that needs a product setting value (e.g., default model for new agents) must query the DB at runtime. Caching is acceptable for performance, but the DB is the authoritative source. Secrets are read from `.env` via `settings` at import time.

## Code Implementation Workflow

### Step 1: Write a test script first with mock data
Always start with a test script that uses mock data to verify the core logic works before touching any existing backend code.

Prefer **filesystem-first** testing for skills and agents — use `create_deep_agent(skills=[path])` directly with SKILL.md files on disk. No PostgreSQL needed for the core logic test. The DB is only a storage/management layer; the deepagents library natively reads skills from the filesystem.

### Step 2: Implement backend changes step by step
Make small, incremental changes to the backend code, one piece at a time.

### Step 3: Test each step after code is done
After each small implementation step, run the test script to verify the step works. If it fails, go back to Step 2 and fix the code before proceeding further.

### Step 4: Run full backend tests
Once all implementation steps are complete, run all backend tests to ensure everything works together.

### Step 5: Implement UI changes
Only after the backend is fully tested and working, proceed to implement the corresponding UI changes.

## Service Management

### Rule 1: Always use `start.sh` to restart services
When backend or frontend needs restarting (e.g., after code changes), always use:
```bash
cd /Users/weiping/dev/Learn/langchain-ai/langconfig && bash start.sh
```
This script:
- Kills previous processes on ports 8765 (BE) and 1420 (FE)
- Starts backend with `SKIP_STARTUP_API_TEST=true` (skips API key connection tests)
- Starts frontend via `npm run dev`
- Health-checks backend before returning

Never kill and restart processes manually.

## Testing Philosophy

### MVP First — simplest case always wins
Start with the most minimal working case. Get it green, then layer on complexity.

For skills:
1. **Filesystem test** (no DB): Create `SKILL.md` on disk → call `create_deep_agent(skills=[path])` → verify response contains skill keywords
2. **DB test**: Store skill in PostgreSQL → sync to filesystem → call `create_deep_agent(skills=[synced_path])` → verify
3. **API test**: `POST /api/skills` → `POST /api/deepagents` → `POST /api/chat/message` → verify

### Skill testing without PostgreSQL
The deepagents library's `SkillsMiddleware` reads SKILL.md files from the filesystem. You can test skills end-to-end without a running database:

```python
from deepagents import create_deep_agent
from langgraph.checkpoint.memory import MemorySaver

# Create a simple skill on disk
skill_path = "/tmp/skills/my-skill"
os.makedirs(f"{skill_path}/my-skill", exist_ok=True)
with open(f"{skill_path}/my-skill/SKILL.md", "w") as f:
    f.write("---\nname: my-skill\ndescription: My test skill\n---\n\nInstructions here.")

# Create agent with skills loaded from filesystem
agent = create_deep_agent(
    model="deepseek:deepseek-chat",
    system_prompt="You are a helpful assistant.",
    skills=[skill_path],
    checkpointer=MemorySaver(),
)
```

## Code Quality
(Add other project rules as needed)

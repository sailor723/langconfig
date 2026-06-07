# Phase 2: Tools — Definition, Registration, Execution

> Core question: How does LangConfig define, register, store, and dynamically bind tools to agents?

---

## Architecture Overview

```
                              Tool Definitions
      +----------------------------+---------------------------+
      |                            |                           |
      v                            v                           v
Native Tools (hardcoded)    Tool Templates (pre-built)   Custom Tools (user-defined)
backend/tools/native_tools.py  templates.py               models/custom_tool.py (DB)
      |                            |                           |
      |                            |  (user fills config)      |  (user defines fully)
      |                            v                           |
      |                    ToolFactory.create_tool()  <---------+
      +-------------------> ToolFactory.create_tool()  <--------+
                                       |
                                       v
                             AgentFactory._load_*_tools()
                             (backend/core/agents/factory.py)
                                       |
                                       v
                             Tool Constraint Wrapper
                             (tools/execution_wrapper.py)
                                       |
                                       v
                             Bound to Agent (create_agent())
```

---

## File-by-File Breakdown

### 1. Native Tools (Built-in)
**File**: [`backend/tools/native_tools.py`](../../backend/tools/native_tools.py)

Tools available to every agent without configuration. Divided into 3 categories:

| Category | Tools | Notes |
|---|---|---|
| **Web** | `web_search`, `web_fetch`, `tavily_search`, browser tools | DuckDuckGo (free, no key) + Yahoo fallback + Tavily (AI-optimized, API key) + Playwright |
| **Filesystem** | `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep` | DeepAgents-standard naming. `write_file` has workspace isolation + DB version tracking |
| **Future** | memory, reasoning | Registered in `TOOL_NAME_MAP` but implemented in `core/agents/memory.py` |

Key design:
- **`TOOL_NAME_MAP`** (L32-79) — maps legacy MCP names to current names for backward compatibility
- **`load_native_tools()`** (L1307) — registry dict matching tool names → tool functions
- **`get_available_tool_names()`** (L1388) — exposes available tools to frontend
- **Every tool returns `str`** — errors are returned as strings, never raised as exceptions

### 2. Custom Tools (User-defined)
**File**: [`backend/models/custom_tool.py`](../../backend/models/custom_tool.py)

**Enums & schemas**:
- `ToolType` enum → `API`, `DATABASE`, `CODE_EXECUTION`, `FILE_SYSTEM`, `COMMUNICATION`, `CUSTOM`
- `ToolTemplateType` enum → `slack`, `github`, `jira`, `notion`, `postgres`, etc.
- `CustomToolCreate/Update/Response` — Pydantic schemas for CRUD operations

**Flow**: user-defined tools stored in DB, created via UI or API.

```
POST /api/tools → stored in custom_tools table
    ↓
Agent config references custom_tool_ids: ["my_tool"]
    ↓
_load_custom_tools() @ factory.py#L1376 → DB lookup
    ↓
ToolFactory.create_tool(config) → BaseTool
```

`CustomTool` model stores: `tool_id`, `name`, `description` (critical for LLM), `implementation_config` (API URLs, webhooks), `input_schema` (JSON Schema), `output_format`.

| vs Native Tools | Native | Custom |
|---|---|---|
| **Where defined** | Hardcoded in `native_tools.py` | Stored in DB `custom_tools` table |
| **Referenced by** | String name: `"web_search"` | String ID: `"my_slack_bot"` |
| **Parameters** | Function params via `@tool` decorator | `input_schema` JSON Schema column |
| **Behavior** | Fixed Python logic | Dynamic — API, DB, notifications |
| **Creation** | Dev writes code | User configures via UI/API |

**Hands-on example** — creating a simple HTTP API tool via curl:

```bash
# 1. Create the tool
curl -s -X POST http://localhost:8765/api/custom-tools \
  -H "Content-Type: application/json" \
  -d '{
    "tool_id": "httpbin_test",
    "name": "HTTPBin Test",
    "description": "Returns request info for debugging via httpbin.org",
    "tool_type": "api",
    "implementation_config": {
      "url": "https://httpbin.org/get",
      "method": "GET",
      "headers": {},
      "timeout": 10
    },
    "input_schema": {
      "type": "object",
      "properties": {},
      "required": []
    },
    "output_format": "json",
    "tags": ["utility", "test"]
  }'

# 2. Test the tool
curl -s -X POST http://localhost:8765/api/custom-tools/httpbin_test/test \
  -H "Content-Type: application/json" \
  -d '{"test_input": {}}'

# Response:
# { "success": true, "output": "{...httpbin response...}", "execution_time_ms": 1286 }
```

**Key discovery**: URL template parameters (`{timezone}`) are substituted via `str.format()`, but dict-based body templates do not get the same substitution. This is an existing `ToolFactory` limitation.

### 3. Tool Templates (Pre-built Integrations)
**File**: [`backend/core/tools/templates.py`](../../backend/core/tools/templates.py)

Pre-built integrations defined as `ToolTemplate` objects, registered in `ToolTemplateRegistry`. Users pick a template and fill in configuration fields — no coding needed.

**Flow**:
```
User picks "Slack Notification" in UI
  → fills in webhook_url, channel, etc.
  → POST /api/tools (stores user config, references template_id)
  → Agent creation: ToolFactory.create_tool(config)
  → BaseTool bound to agent
```

**Key differences from custom tools**:

| Aspect | Template | Custom |
|---|---|---|
| **Definition** | Pre-built `ToolTemplate` in code | User-defined from scratch |
| **User effort** | Pick + fill config fields | Define everything |
| **Guidance** | `setup_instructions`, `example_use_cases`, `required_user_fields` | None |
| **Stored in DB** | User config only (references `template_id`) | Full tool definition |

**14 registered templates**:
- **Notification**: Slack, Discord
- **API**: Webhook
- **Image**: OpenAI DALLE-3, GPT-Image-1.5, Gemini Imagen3, Gemini Nano Banana
- **Video**: OpenAI SORA, Gemini Veo3, Gemini Veo3.1
- **CMS**: WordPress
- **Social**: Twitter
- **Database**: PostgreSQL
- **Data**: JSON Transform

Each template includes:
- `config_template` — default JSON config the user fills in
- `input_schema_template` — JSON Schema for tool parameters
- `required_user_fields` — fields the user must provide
- `setup_instructions` — step-by-step setup guide
- `example_use_cases` — suggested use cases

### 4. Tool Factory
**File**: [`backend/core/tools/factory.py`](../../backend/core/tools/factory.py)

The central hub that converts tool configs → `BaseTool` instances, regardless of origin (custom, template, or native).

**Architecture**:
```
tool_config (from DB or template)
  → validate_tool_config() — LangChain field requirements
  → _validate_tool_implementation() — type-specific validation
  → Routing by tool_type:
      ├─ "api"           → _create_api_tool()
      ├─ "notification"  → _create_notification_tool()
      ├─ "image_video"   → _create_image_video_tool()
      ├─ "database"      → _create_database_tool()
      └─ "data_transform" → _create_data_transform_tool()
  → Pydantic args schema from input_schema JSON Schema (cached)
  → StructuredTool.from_function(...) → BaseTool
```

**Key design points**:
- **Pydantic args schema** — JSON Schema → `create_pydantic_model()` dynamically, cached by hash
- **SSRF protection** — blocks private IPs, localhost, cloud metadata endpoints
- **MongoDB injection protection** — blocks `$where`, `$function`, `$accumulator`
- **Auth support** — API keys, bearer tokens, basic auth in headers
- **Artifact storage** — thread-safe `_pending_artifacts` dict for tool execution results

### 5. Tool Seed / Registry Population
**File**: [`backend/core/tools/seed.py`](../../backend/core/tools/seed.py)

- Seeds the database with initial native tools on first run
- Ensures tool definitions exist before any agent tries to load them

### 6. Tool CRUD API
**File**: [`backend/api/tools/routes.py`](../../backend/api/tools/routes.py)

- `GET /api/tools` — list all tools (native + custom + templates)
- `POST /api/tools` — create a new custom tool
- `PUT /api/tools/{id}` — update a custom tool
- `DELETE /api/tools/{id}` — delete a custom tool

### 7. Tool Loading in Agent Factory
**File**: [`backend/core/agents/factory.py`](../../backend/core/agents/factory.py)

Five loading methods called during `create_agent()` Step 3 (L392). Each accepts a list of identifiers and returns `List[BaseTool]`:

| Method | Line | Source | Key Detail |
|---|---|---|---|
| `_load_native_tools()` | L1234 | `native_tools.py` | Looks up tool names in `available_tools` registry dict |
| `_load_cli_tools()` | L1344 | CLI command config | Creates tools from `CliCommand` DB models (git, docker) |
| `_load_custom_tools()` | L1376 | DB `custom_tools` table | Fetches by `tool_id`, calls `ToolFactory.create_tool()`, tracks usage/error counts |
| `_load_memory_tools()` | L1467 | Vector store + memory | Creates search/retrieval tools from `AgentMemorySystem` |
| `_load_rag_tools()` | L1490 | RAG config | Creates codebase search tools for RAG workflows |

### 8. Execution Constraint Wrapper
**File**: [`backend/core/tools/execution_wrapper.py`](../../backend/core/tools/execution_wrapper.py)

- `wrap_tools_with_constraints()` — wraps each tool with:
  - **Timeout** — prevent hanging tool calls
  - **Retry** — retry on transient failures
  - **Exclusive execution** — prevent concurrent tool access

---

## Tool Loading Flow (in AgentFactory.create_agent)

```
Step 3 (L392):
  tools: List[BaseTool] = []         # Empty list

  # 1. Native tools by name
  if native_tool_names:
      tools += _load_native_tools(native_tool_names)  @ L1234

  # 2. CLI tools
  if cli_tools:
      tools += _load_cli_tools(cli_tools)             @ L1344

  # 3. Custom tools by DB ID
  if custom_tool_ids:
      tools += _load_custom_tools(custom_tool_ids)    @ L1376

  # 4. Memory tools (if memory enabled)
  if enable_memory:
      tools += _load_memory_tools(...)                @ L1467

  # 5. RAG tools (if RAG enabled)
  if enable_rag:
      tools += _load_rag_tools(...)                   @ L1490

Step 3b (L444):
  # Wrap with constraints (timeout, retry, exclusive)
  tools = wrap_tools_with_constraints(tools)

Step 7-8 (L631-675):
  # Pass tools to create_agent() — it handles binding internally
  create_agent_kwargs["tools"] = tools
  agent_graph = create_agent(**create_agent_kwargs)
```

**Key insight**: `create_agent()` from LangChain v1.0 handles tool binding internally — you no longer need to call `llm.bind_tools(tools)` manually.

**Key insight 2: Unified tool pattern** — All three categories (native, template, custom) reduce to the same structure:

| Component | Native | Template | Custom |
|---|---|---|---|
| **name** | Function name | `ToolTemplate.name` | `CustomTool.name` |
| **description** | Docstring → LLM prompt | `ToolTemplate.description` | `CustomTool.description` |
| **input schema** | Function params via `@tool` | `input_schema_template` | `input_schema` (JSON Schema) |
| **output** | Returns `str` | `output_format` | `output_format` |

The only real difference is **where they originate**:
- **Native** — hardcoded Python functions, always available to every agent
- **Template** — pre-built configs users fill in (API keys, endpoints) → stored as `ToolTemplate`
- **Custom** — fully user-defined, stored as `CustomTool` in DB, loaded by ID

All three end up as `BaseTool` instances passed to `create_agent(tools=...)`.

---

## Beyond Tools — Backend Architecture

The following sections cover the broader backend architecture that tools integrate with.

### 9. Execution Constraint Wrapper
**File**: [`backend/core/tools/execution_wrapper.py`](../../backend/core/tools/execution_wrapper.py)

Wraps `BaseTool` instances with runtime constraints from action presets:

```
wrap_tools_with_constraints(tools)
  → For each tool, look up ActionPreset by tool name
  → wrap_tool_with_constraints():
      ├── Timeout — `execute_with_timeout()` via `asyncio.wait_for()`
      │     ├─ strategy: "kill" (hard timeout, raises exception)
      │     └─ strategy: "graceful_shutdown" (logs warning, allows cleanup)
      ├── Retry — `execute_with_retries()` with exponential backoff
      │     └─ 1s → 2s → 4s → 8s (max), configurable via `max_retries`
      ├── Exclusive execution — `ExclusiveExecutionLock` (per-tool `asyncio.Lock`)
      │     └─ Prevents concurrent runs of the same tool (e.g., DB writes)
      └── Human-in-the-Loop (HITL) — `_request_hitl_approval()`
            └─ Publishes approval request to event bus, waits up to 5 min
            └─ Frontend listens to `hitl:requests` channel for approval UI
```

Key design:
- **Non-intrusive** — wraps existing tools without modifying them
- **Global lock manager** — `ExclusiveExecutionLock` using class-level `Dict[str, asyncio.Lock]`
- **Async-safe** — both sync and async functions handled via `loop.run_in_executor()`
- **External approval** — `approve_tool_execution()` function enables programmatic HITL responses

### 10. API Routes Architecture
**File**: [`backend/main.py`](../../backend/main.py) (router registration) + [`backend/api/`](../../backend/api/) (all route modules)

**22 route modules organized by domain**:

| Domain | Router Prefix | Endpoints |
|---|---|---|
| Workflows | `/api/workflows/` | CRUD, execution, versions, import/export |
| Orchestration | `/api/orchestration/` | Execute tasks, cancel, streaming |
| Projects | `/api/projects/` | CRUD |
| Tasks | `/api/tasks/` | CRUD, status |
| Agents | `/api/agents/` | Agent templates, CRUD |
| DeepAgents | `/api/deep-agents/` | Config, export |
| Chat | `/api/chat/` | Chat completion, streaming |
| Tools | `/api/custom-tools/` | CRUD, test execution |
| Skills | `/api/skills/` | CRUD |
| Memory | `/api/memory/` | Agent memory management |
| Knowledge | `/api/knowledge/` | RAG, store |
| System | `/api/` | Health, settings, debug, background tasks |
| Auth | `/api/auth/` | Google OAuth |
| HITL | `/api/hitl/` | Approval requests |
| Images | `/api/images/` | Upload/serve AI-generated images |
| Models | `/api/local-models/`, `/api/models/` | Config, capabilities |
| Workspace | `/api/workspace/` | File management |
| Presets | `/api/presets/` | Action presets library |
| Presentations | `/api/presentations/` | Generation |
| Schedules | `/api/schedules/` | Cron scheduling |
| Triggers | `/api/triggers/` | Event-based triggers |
| Webhooks | `/api/webhooks/` | Webhook receivers |
| Schemas | `/api/schemas/` | Structured output schemas |
| Checkpoints | (via workflows) | Restore workflow checkpoints |

Key design:
- **Domain-based organization** — each domain in its own directory with `routes.py`
- **Consistent patterns** — FastAPI `APIRouter(dependencies=[Depends(get_db)])`
- **SSE streaming** — `/api/orchestration/` supports Server-Sent Events for real-time updates

### 11. Database Models & Schema
**File**: [`backend/db/database.py`](../../backend/db/database.py) + [`backend/models/`](../../backend/models/) (15 model files)

**Database**: PostgreSQL with pgvector extension (unified DB for everything)

**Connection**:
- Sync: SQLAlchemy `create_engine()` with `QueuePool` (pool_size=10, max_overflow=20)
- Async: `create_async_engine()` with `asyncpg` driver
- Config: `DATABASE_URL` env var, default `postgresql://langconfig:langconfig_dev@localhost:5433/langconfig`

**Key models**:

| Model | Table | Key Columns |
|---|---|---|
| `Project` | `projects` | id, name, description, configuration (JSON), indexing_status |
| `WorkflowProfile` | `workflow_profiles` | id, name, blueprint (JSON), strategy (JSON), version |
| `Task` | `tasks` | id, project_id, status (enum), result (JSON), error_message |
| `Directive` | `directives` | id, project_id, goal_description, execution_plan (JSON) |
| `Settings` | `settings` | id=1 (singleton), api_keys (JSONB, encrypted), app config |
| `CustomTool` | `custom_tools` | tool_id, name, description, implementation_config, input_schema, usage_count, error_count |
| `Skill` | `skills` | id, name, description, tool_configs (JSON), context_prompt |
| `CustomSchema` | `custom_schemas` | id, name, schema_definition (JSON) |
| `WorkspaceFile` | `workspace_files` | id, project_id, path, content, version |
| `FileVersion` | `file_versions` | id, file_id, content, version_number |
| `AuditLog` | `audit_logs` | id, action, entity_type, entity_id, timestamp |
| `DeepAgent` | `deep_agents` | id, name, configuration (JSON), export_format |
| `BackgroundTask` | `background_tasks` | id, task_type, status (enum), progress, result (JSON) |
| `WorkflowSchedule` | `workflow_schedules` | id, workflow_id, cron_expression, enabled |
| `WorkflowTrigger` | `workflow_triggers` | id, workflow_id, trigger_type, config (JSON) |
| `OAuthToken` | `oauth_tokens` | id, provider, access_token (encrypted), refresh_token |

**Seed/Init**:
- [`db/init_postgres.sql`](../../backend/db/init_postgres.sql) — initial schema creation
- [`db/init_custom_tools.py`](../../backend/db/init_custom_tools.py) — seeds default tools
- [`core/tools/seed.py`](../../backend/core/tools/seed.py) — ensures tool definitions exist

### 12. Auth & API Key Encryption
**Files**: [`backend/services/encryption.py`](../../backend/services/encryption.py) + [`backend/config.py`](../../backend/config.py) + [`backend/models/settings.py`](../../backend/models/settings.py)

**API Key Flow**:
```
User enters key in Settings UI
  → POST /api/settings/api-keys (encrypted with Fernet)
  → Stored in settings.api_keys JSONB column: {"openai": "<encrypted>"}

At runtime:
  → get_api_key_from_db("openai_api_key")
  → Map key_name → provider (e.g., "openai_api_key" → "openai")
  → SQL: SELECT api_keys->>'openai' FROM settings WHERE id = 1
  → Decrypt with Fernet → return plaintext
  → If DB returns nothing → fallback to .env (os.getenv)
```

**Encryption** (`EncryptionService`, singleton):
- Algorithm: **Fernet** (AES-128-CBC + HMAC-SHA256, symmetric)
- Key derivation: **PBKDF2-HMAC-SHA256** (100K iterations) from `APP_ENCRYPTION_KEY` env var
- Salt: hardcoded (`b'langconfig_salt'`) for deterministic key derivation from env var
- Fallback dev key: `"langconfig-default-insecure-key-change-me"` (must change in production)

**Provider map** (config.py#L42):
```python
provider_map = {
    "openai_api_key": "openai",   "anthropic_api_key": "anthropic",
    "google_api_key": "google",   "cohere_api_key": "cohere",
    "replicate_api_key": "replicate",  "deepseek_api_key": "deepseek",
    "tavily_api_key": "tavily",
}
```

### 13. Agent Runtime (Execution Flow)
**Files**: [`backend/core/workflows/executor.py`](../../backend/core/workflows/executor.py) + [`backend/core/workflows/runner.py`](../../backend/core/workflows/runner.py) + [`backend/core/workflows/events/emitter.py`](../../backend/core/workflows/events/emitter.py)

**Full execution flow from API to agent**:

```
POST /api/orchestration/execute  (execution.py#L106)
  → BackgroundTasks.add_task(execute_workflow_background)  (execution.py#L164)
  → core/workflows/runner.execute_workflow()  (runner.py#L102)
      │
      ├── 1. Load WorkflowProfile from DB
      ├── 2. WorkflowFactory.create_workflow_structure(blueprint, strategy)
      │      → Creates LangGraph graph structure
      ├── 3. AgentFactory.create_agent(agent_config, ...)
      │      → Loads native, custom, memory, RAG tools
      │      → Creates compiled CompiledStateGraph
      ├── 4. wrap_tools_with_constraints(tools)
      │      → Applies timeout, retry, exclusive, HITL
      ├── 5. Create PostgresCheckpointer (checkpointing)
      ├── 6. Compile graph with checkpointer
      ├── 7. Create ExecutionEventCallbackHandler (observability)
      ├── 8. agent_graph.ainvoke(state, config={callbacks})
      │      → LangGraph runtime executes nodes
      │      → Tool calls, LLM calls, state transitions
      │      → Events streamed via SSE to frontend
      └── 9. Return final state → saved to task.result
```

**Key runtime features**:
- **Checkpointing** — `PostgresCheckpointer` saves state after each node for resume/restore
- **Cancellation** — `CancellationRegistry` enables stopping running workflows
- **SSE streaming** — `ExecutionEventCallbackHandler` emits real-time events (`CHAIN_START`, `TOOL_START`, `LLM_END`, etc.)
- **Progress tracking** — `ToolProgressContext` / `CustomEventContext` for frontend progress bars
- **Workflow context** — `WorkflowContext` provides runtime config (user, credentials, model prefs) separate from checkpointed state

---

## Key LangChain APIs Used

| API | Purpose |
|---|---|
| `BaseTool` / `StructuredTool` | Tool interface |
| `tool()` decorator | Convert function to tool |
| `InjectedToolArg` | Dependency injection for tools |
| `create_agent(tools=...)` | Automatic tool binding |

---

## Key Takeaways

1. **Three tool categories**: Native (built-in), Custom (user-defined via DB), Template (pre-built integrations)
2. **Tools are loaded by name or ID** — no hardcoded tool lists in agent configs
3. **Execution constraints** are applied uniformly via the wrapper layer
4. **Tool binding is now automatic** — LangChain v1.0 `create_agent()` handles it
5. **Unified database** — PostgreSQL with pgvector handles everything: app data, vectors, LangGraph checkpoints
6. **Dual-source API keys** — Database (encrypted) > .env fallback, managed via Settings UI
7. **Streaming-first runtime** — SSE events for every step: chain start/end, tool calls, LLM token usage

---

## Suggested Study Order

1. Read [`native_tools.py`](../../backend/tools/native_tools.py) — understand the built-in tools ✅
2. Read [`custom_tool.py`](../../backend/models/custom_tool.py) — understand the tool schema + enums ✅
3. Read [`templates.py`](../../backend/core/tools/templates.py) — understand pre-built integrations ✅
4. Read [`factory.py`](../../backend/core/tools/factory.py) — understand `ToolFactory` ✅
5. Read [`factory.py`](../../backend/core/agents/factory.py#L1376-L1465) — understand `_load_custom_tools()` ✅
6. Read [`execution_wrapper.py`](../../backend/core/tools/execution_wrapper.py) — understand constraint wrapping ✅
7. Read [`routes.py`](../../backend/api/tools/routes.py) — understand the CRUD API ✅
8. **Hands-on**: Create a custom tool via CLI and test it ✅
# LangConfig — Project Overview

**LangConfig** is an open-source AI Agent configuration platform — a visual IDE for building, testing, and deploying LangChain agents and LangGraph workflows.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React 19 + TypeScript + Tailwind CSS 4 + ReactFlow + Vite |
| **Backend** | Python 3.11+ / FastAPI + LangChain v1.0 + LangGraph |
| **Database** | PostgreSQL 16 + pgvector (for embeddings/RAG) + Alembic migrations |
| **Desktop** | Tauri 2 (Rust wrapper for desktop app) |
| **Auth** | Google OAuth |
| **Infra** | Docker Compose (PostgreSQL + Redis) |

---

## Architecture

```
React UI (port 1420) ──→ FastAPI Backend (port 8765) ──→ PostgreSQL (port 5433)
                              │
                         Agent Factory
                              │
                   ┌──────────┼──────────┐
                   │          │          │
              Playground   LangChain   DeepAgent
             (raw model)   Agent w/    (skills +
                              tools     sandbox +
                                         middleware)
```

The backend also supports **MCP (Model Context Protocol)** tools, **SSE streaming** for real-time agent responses, and **pgvector** for RAG-based knowledge retrieval.

---

## Project Structure

- **`backend/`** — FastAPI server with:
  - `api/` — REST route modules (agents, chat, workflows, tools, knowledge, MCP, auth, etc.)
  - `core/` — Business logic: Agent factory, workflow executor, middleware, tools, codegen, skills
  - `models/` — SQLAlchemy ORM models (database-driven, no hardcoded enums)
  - `services/` — Business services (MCP manager, chat sessions, encryption, file storage, scheduler, etc.)
  - `db/` — Database initialization and migrations (Alembic)
  - `schemas/` — Pydantic schemas for data validation
  - `tools/` — Native Python tools
  - `skills/` — Built-in skills library

- **`src/`** — React frontend with:
  - `features/` — Feature modules: agents, chat, knowledge, memory, settings, skills, tools, workflows
  - `components/` — Shared UI components
  - `hooks/` — Custom React hooks
  - `contexts/` — React context providers
  - `pages/` — Page-level components
  - `types/` — TypeScript type definitions

- **`src-tauri/`** — Tauri desktop wrapper (Rust)
- **`learning/`** — Learning plan with 6 phases of examples
- **`scripts/`** — Utility scripts (setup, cleanup, testing)

---

## Key Features

1. **3 Agent Execution Modes:**
   - **Playground** — Raw `model.invoke()`, no tools
   - **LangChain Agent** — Standard agent with tools
   - **DeepAgent** — Full-featured agent with tools + skills + sandbox + middleware pipeline

2. **Visual Workflow Canvas** — Drag-and-drop workflow builder using ReactFlow (node-based LangGraph editor)

3. **Skills Library** — 17+ built-in skills (code review, data analysis, debugging, security, etc.) + user-created skills stored in PostgreSQL, synced to agent sandboxes

4. **Tool System** — Native tools (web, filesystem, memory, reasoning, delegation), MCP tools, and user-custom tools with a builder UI

5. **DB-Driven Model Management** — All model configs in PostgreSQL (no hardcoded enums). Supports OpenAI, Anthropic, DeepSeek, Google, GLM, MiniMax, and local models (Ollama, LM Studio, vLLM)

6. **RAG / Knowledge Base** — Document upload with vector embeddings via pgvector + LlamaIndex

7. **Real-time Streaming** — SSE-based streaming for agent responses and workflow execution

8. **Human-in-the-Loop** — Approval gates for sensitive operations

9. **MCP Protocol Support** — Both as a client (consuming MCP tools) and server (exposing tools via MCP)

10. **Scheduling & Triggers** — Cron-based workflow scheduling + file watcher triggers

---

# Phase 5: DeepAgent — Subagent Orchestration

> How LangConfig's DeepAgent system extends simple agents with planning, middleware, subagent delegation, guardrails, and HITL via the deepagents library.

---

## Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │         DeepAgentConfig              │
                    │  (model, tools, middleware,          │
                    │   subagents, backend, guardrails)    │
                    └───────────┬─────────────────────────┘
                                │
                                v
                    ┌─────────────────────────────────────┐
                    │      DeepAgentFactory                │
                    │  (merges config + guardrails,        │
                    │   resolves tool names,               │
                    │   builds interrupt_on map)           │
                    └───────────┬─────────────────────────┘
                                │
                                v
                    ┌─────────────────────────────────────┐
                    │    create_deep_agent()               │
                    │  (deepagents library)                │
                    │  compiles LangGraph graph with:      │
                    │  ├─ Middleware chain                 │
                    │  ├─ Subagent delegates               │
                    │  ├─ HITL (HumanInTheLoopMiddleware)  │
                    │  └─ Backend storage                  │
                    └───────────┬─────────────────────────┘
                                │
                                v
                    ┌─────────────────────────────────────┐
                    │      Compiled LangGraph Agent        │
                    │  (runs with astream_events v2,       │
                    │   SSE streaming, checkpointing)      │
                    └─────────────────────────────────────┘
```

---

## 1. Data Model

### DeepAgentConfig — Full Config Schema

**File**: [`backend/models/deep_agent.py`](../../backend/models/deep_agent.py#L178-L250)

The top-level config schema that defines every aspect of a deep agent:

```python
class DeepAgentConfig(BaseModel):
    model: str                                         # e.g. "deepseek-chat", "gpt-4o"
    temperature: float = 0.7
    reasoning_effort: str = "low"
    system_prompt: str = ""
    native_tools: List[str] = []                       # Tool IDs from tool templates
    cli_tools: List[str] = []
    use_deepagents: bool = True                        # Flag: deep vs normal agent
    middleware: List[MiddlewareConfig] = []             # Middleware chain
    subagents: List[SubAgentConfig] = []               # Subagent delegates
    backend: BackendConfig = BackendConfig()            # Storage backend
    guardrails: GuardrailsConfig = GuardrailsConfig()   # HITL + token limits
```

### Storage in PostgreSQL

All agents (both "normal" and "deep") are stored in the **`deep_agent_templates`** table:

| Column | Type | Description |
|--------|------|-------------|
| `id` | Integer (PK) | Auto-increment ID |
| `name` | String(200) | Agent name |
| `config` | JSON | `DeepAgentConfig` — the full blueprint |
| `guardrails_config` | JSON | HITL interrupts + token limits |
| `middleware_config` | JSON | Middleware list |
| `subagents_config` | JSON | Subagent configs |
| `backend_config` | JSON | Backend settings |

The `config.use_deepagents` boolean determines which factory is used at runtime:

```python
# backend/api/chat/routes.py#L598-606
if config.use_deepagents:
    agent_instance, ... = await DeepAgentFactory.create_deep_agent(config)
else:
    agent_instance, ... = await AgentFactory.create_agent(config)  # normal agent
```

### SubAgentConfig

**File**: [`backend/models/deep_agent.py#L20-L80`](../../backend/models/deep_agent.py#L20-L80)

Subagents can be either **dictionary-based** or **compiled**:

```python
class SubAgentConfig(BaseModel):
    name: str                                                # Subagent name
    model: Optional[str] = None                              # Override model
    system_prompt: Optional[str] = None                      # Override system prompt
    tools: Optional[List[str]] = None                        # Tools for this subagent
    max_iterations: int = 25
    type: SubAgentType = SubAgentType.DICT                   # DICT or COMPILED
```

### BackendConfig

**File**: [`backend/models/deep_agent.py#L90-L120`](../../backend/models/deep_agent.py#L90-L120)

```python
class BackendConfig(BaseModel):
    type: str = "state"         # state | store | filesystem | vectordb | composite
    config: Dict[str, Any] = {}
    mappings: Optional[Dict[str, Any]] = None  # For composite backends
```

### GuardrailsConfig

**File**: [`backend/models/deep_agent.py#L130-L170`](../../backend/models/deep_agent.py#L130-L170)

```python
class GuardrailsConfig(BaseModel):
    interrupts: Dict[str, Any] = {}       # {"tools": true} or {"tool_name": {config}}
    token_limits: Dict[str, int] = {}     # max_total_tokens, eviction_threshold, ...
    enable_auto_eviction: bool = False
    enable_summarization: bool = False
    long_term_memory: bool = False
```

---

## 1.5 Tool Resolution: String IDs → Python Implementation

A key architectural insight: the DB only stores **string identifiers** for tools — not the actual implementations. Each agent has its own `native_tools` list in `config`.

### Example: search agent (id=12) stored in DB

```json
"native_tools": ["web_search", "tavily_search", "memory_recall", "memory_store", "enable_memory"]
```

These are **just string IDs** — no Python code, no metadata in the DB. Each agent defines its own tool list independently:

| Agent | `native_tools` in DB |
|---|---|
| id=1 Deep Code Researcher | `["ls", "read_file", "write_file", "edit_file", "glob", "grep", "web_search"]` |
| id=6 Hello World Agent | `[]` (no tools) |
| id=10 greeting agent | `["memory_recall", "memory_store", "enable_memory"]` |
| id=12 search agent | `["web_search", "tavily_search", "memory_recall", "memory_store", "enable_memory"]` |

### Resolution chain at runtime

```
DB: config.native_tools = ["tavily_search", ...]   ← just string IDs
                            │
                            ▼
TOOL_NAME_MAP               ← normalizes aliases (e.g. "tavily" → "tavily_search")
[/backend/tools/native_tools.py#L72](../../backend/tools/native_tools.py#L72)
                            │
                            ▼
load_native_tools()          ← resolves "tavily_search" → Python @tool function
[/backend/tools/native_tools.py#L1414](../../backend/tools/native_tools.py#L1414)

available_tools = {
    "tavily_search": tavily_search,   ← the async def below
    "web_search":    web_search,
    "memory_store":  memory_store,
    ...
}
                            │
                            ▼
@tool tavily_search(query, max_results)   ← actual implementation
[/backend/tools/native_tools.py#L334](../../backend/tools/native_tools.py#L334)
                            │
                            ▼
TOOL_REGISTRY               ← UI metadata (name, description, category, requires_api_key)
[/backend/tools/native_tools.py#L1546](../../backend/tools/native_tools.py#L1546)
                            │
                            ▼
GET /api/tools/registry     ← frontend displays available tools
[/backend/api/tools/registry.py](../../backend/api/tools/registry.py)
```

### Key takeaway

The DB stores a **reference** (the tool name string), not the tool itself. The Python code in `native_tools.py` is the single source of truth for both:
- **Implementation**: the `@tool` function that executes the logic
- **Registry metadata**: the descriptions and categories shown in the UI

To add a new tool to an agent, you just add its string ID to `native_tools` in the DB. No other DB changes needed.

---

## 2. Middleware System

**File**: [`backend/core/middleware/deep.py`](../../backend/core/middleware/deep.py)

Deep agents use a composable middleware system that hooks into the agent's execution lifecycle:

| Middleware | Purpose | Config |
|---|---|---|
| `TodoListMiddleware` | Manages a todo list that persists across sessions | `{"max_items": 10}` |
| `FilesystemMiddleware` | Agent-managed file I/O with working directory | `{"allowed_paths": [...]}` |
| `HumanInTheLoopMiddleware` | Pauses execution for human approval before tool calls | Handled via `interrupt_on` |

Middleware is configured via the `DeepAgentConfig.middleware` array. The deepagents library's `create_deep_agent()` automatically registers these middleware instances in the agent's middleware chain.

---

## 3. Guardrails & HITL (Human-in-the-Loop)

This is the key integration we implemented. Unlike Phase 4 (which covers LangGraph's `interrupt_before`/`interrupt_after` for normal agents), deep agents use a **per-tool interrupt** mechanism.

### Configuration

Set via `guardrails_config.interrupts` in the database:

```json
{
  "interrupts": { "tools": true }
}
```

This is stored as a separate DB column (`guardrails_config`) and merged into `agent_config` at runtime:

```python
# backend/api/chat/routes.py#L512-515
agent_config = agent.config.copy()
agent_config["guardrails"] = agent.guardrails_config.copy()  # merge guardrails
```

### Factory Mapping (bool → InterruptOnConfig)

**File**: [`backend/services/deepagent_factory.py#L259-330`](../../backend/services/deepagent_factory.py#L259-330)

The factory resolves `"tools"` wildcard to actual tool names and builds the proper `interrupt_on` dict:

```python
raw_interrupts = {"tools": true}

# Resolve "tools" → actual tool names
available_tool_names = ["web_search", "tavily_search", "memory_recall", ...]
interrupt_on = {
    "web_search":    {"allowed_decisions": ["approve", "edit", "reject", "respond"], ...},
    "tavily_search": {"allowed_decisions": ["approve", "edit", "reject", "respond"], ...},
    ...
}

agent_kwargs["interrupt_on"] = interrupt_on
```

### HumanInTheLoopMiddleware

**File**: [`langchain/agents/middleware/human_in_the_loop.py`](../../backend/.venv/lib/python3.13/site-packages/langchain/agents/middleware/human_in_the_loop.py)

This middleware is automatically registered by `create_deep_agent()` when `interrupt_on` is provided. It:

1. Intercepts tool calls in the `after_model` hook
2. Checks if the tool name matches an entry in `interrupt_on`
3. Calls `interrupt(hitl_request)` → raises `GraphInterrupt`
4. Agent pauses, state is checkpointed
5. On resume (`Command(resume={"decisions": [{"type": "approve"}]})`), execution continues

### Normal Agent HITL (interrupt_before)

**File**: [`backend/core/agents/factory.py#L323-L340`](../../backend/core/agents/factory.py#L323-L340)

Normal agents (`use_deepagents=False`) use a different HITL mechanism via LangGraph's native `interrupt_before`:

| Parameter | Type | Description |
|---|---|---|
| `interrupt_before` | `list[str]` | Pause before nodes: `["tools"]` or `["model"]` |
| `interrupt_after` | `list[str]` | Pause after nodes |

**Detection**: After `astream_events` completes, check `state.next` instead of `state.interrupts`:

```python
state_snapshot = await agent_instance.aget_state(
    {"configurable": {"thread_id": session_id}}
)
if state_snapshot and state_snapshot.next:
    # state.next = ("tools",) → paused before tools node
    tool_calls = extract_tool_calls_from_last_message(state_snapshot)
    yield interrupt_event(tool_calls)
```

**Resume**: Send a simple resume value (not the decisions structure used by deep agents):

```python
await agent_instance.ainvoke(
    Command(resume="continue"),
    config={"configurable": {"thread_id": session_id}}
)
```

Key differences from deep agent HITL:

| Aspect | Deep Agent | Normal Agent |
|---|---|---|
| Mechanism | `HumanInTheLoopMiddleware.after_model()` → `interrupt()` | `interrupt_before=["tools"]` |
| Interrupt type | `GraphInterrupt` (raised exception) | LangGraph native pause |
| Detection | `state.interrupts` | `state.next` (contains paused nodes) |
| Resume format | `{"decisions": [{"type": "approve"}]}` | Simple value (`"continue"`, `True`, etc.) |
| Requires checkpointer | Yes (PostgreSQL) | Yes (required for any interrupt) |

### SSE Streaming & Interrupt Detection

**File**: [`backend/api/chat/routes.py`](../../backend/api/chat/routes.py)

The SSE streaming endpoint handles interrupts via post-stream state check (since deepagents swallows `GraphInterrupt` internally):

```python
# After astream_events completes, check for pending interrupts
state_snapshot = await agent_instance.aget_state(
    {"configurable": {"thread_id": session_id}}
)
if state_snapshot.interrupts:
    yield f"data: {json.dumps({'type': 'interrupt', 'data': ...})}\n\n"
```

### Resume Endpoint

**File**: [`backend/api/chat/routes.py#L1196-L1250`](../../backend/api/chat/routes.py#L1196-L1250)

```python
POST /api/chat/{session_id}/resume
Body: {"action": "approve"}  # or "reject", "edit", "respond"

# Internally sends:
Command(resume={"decisions": [{"type": "approve"}]})
```

---

## 4. Data Flow: DB → Runtime

The full lifecycle of a deep agent:

```
1. User creates agent via UI
   → POST /api/deepagents/
   → saved to deep_agent_templates (PostgreSQL)

2. User selects agent & starts chat
   → POST /api/chat/start {agent_id: 12}
   → loads deep_agent_templates row

3. routes.py merges config + guardrails_config
   → agent_config["guardrails"] = guardrails_config

4. DeepAgentFactory.create_deep_agent(config)
   → parses guardrails.interrupts
   → resolves "tools" → actual tool names
   → builds interrupt_on dict
   → calls create_deep_agent(interrupt_on=...)

5. deepagents library compiles LangGraph graph
   → registers HumanInTheLoopMiddleware
   → registers other middleware
   → returns compiled agent

6. SSE streaming begins
   → astream_events v2 yields tokens
   → tool call triggers interrupt
   → HumanInTheLoopMiddleware calls interrupt()
   → agent pauses, state checkpointed

7. User approves/rejects via API
   → POST /api/chat/{session_id}/resume
   → Command(resume={"decisions": [...]})
   → agent resumes from checkpoint
```

---

## 5. CRUD API

**File**: [`backend/api/agents/deep_agents.py`](../../backend/api/agents/deep_agents.py)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/deepagents/` | List all deep agents (used by agent selector dropdown) |
| `POST` | `/api/deepagents/` | Create a new deep agent |
| `GET` | `/api/deepagents/{id}` | Get agent details |
| `PUT` | `/api/deepagents/{id}` | Update agent config |
| `DELETE` | `/api/deepagents/{id}` | Delete agent |
| `POST` | `/api/deepagents/prompt-preview` | Preview assembled prompt from USER/BASE/CUSTOM/SUFFIX components |
| `PATCH` | `/api/deepagents/{id}/prompt` | Save `custom_prompt` and `custom_suffix` to agent config (preserved across Builder saves) |
| `GET` | `/api/tools/registry` | List all available native tools with metadata (name, description, category, requires_api_key) |
| `POST` | `/api/deepagents/{id}/export` | Export agent as standalone code |

---

## Key Files Reference

| File | Purpose |
|---|---|
| [`backend/models/deep_agent.py`](../../backend/models/deep_agent.py) | `DeepAgentConfig`, `SubAgentConfig`, `MiddlewareConfig`, `BackendConfig`, `GuardrailsConfig`, `DeepAgentTemplate` (SQLAlchemy model) |
| [`backend/services/deepagent_factory.py`](../../backend/services/deepagent_factory.py) | `DeepAgentFactory` — builds deep agent from config, assembles full prompt (USER + custom_prompt/BASE + custom_suffix), maps guardrails → `interrupt_on` |
| [`backend/api/agents/deep_agents.py`](../../backend/api/agents/deep_agents.py) | CRUD endpoints + prompt-preview + save-prompt + tool-registry endpoints |
| [`backend/api/chat/routes.py`](../../backend/api/chat/routes.py) | SSE streaming with interrupt detection, resume endpoint |
| [`backend/core/middleware/deep.py`](../../backend/core/middleware/deep.py) | Deep agent middleware (TodoList, Filesystem) |
| [`backend/core/templates/deep_agent.py`](../../backend/core/templates/deep_agent.py) | Built-in deep agent templates (Code Researcher, etc.) |
| [`src/lib/api-client.ts`](../../src/lib/api-client.ts) | API client methods including `previewPromptAssembly()`, `saveAgentPrompt()`, `listToolRegistry()` |
| [`src/features/agents/ui/DeepAgentBuilder.tsx`](../../src/features/agents/ui/DeepAgentBuilder.tsx) | Agent config form with HITL toggle, file tool warning, all guardrails config |
| [`src/features/agents/ui/AgentLoadouts.tsx`](../../src/features/agents/ui/AgentLoadouts.tsx) | Agent list with import/export, inline chat testing |
| [`src/features/agents/ui/PromptCanvas.tsx`](../../src/features/agents/ui/PromptCanvas.tsx) | Visual prompt assembly component — shows USER, BASE/CUSTOM, SUFFIX segments |
| [`src/features/tools/ToolLibrary.tsx`](../../src/features/tools/ToolLibrary.tsx) | Browse all native tools by category, search by name/ID/description |
| [`src/pages/PromptAssemblyPage.tsx`](../../src/pages/PromptAssemblyPage.tsx) | Standalone Prompt Assembly page with model selector, example prompts, CUSTOM/SUFFIX editors, Save to Agent button |

## Prompt Assembly

The system prompt for a deep agent is assembled from up to 4 components:

```
[USER]\n\n[BASE or CUSTOM]\n\n[SUFFIX]
```

- **USER** — Your custom instructions (passed as `system_prompt=` to `create_deep_agent`)
- **BASE** — SDK default prompt (`BASE_AGENT_PROMPT`, ~2258 chars), always present unless replaced
- **CUSTOM** — Replaces BASE when set via profile or saved `custom_prompt` in agent config
- **SUFFIX** — Model-specific guidance appended last (from HarnessProfile or saved `custom_suffix`)

Users can:
1. Edit USER, CUSTOM, and SUFFIX in the **Prompt** page (top nav)
2. Click **Save to Agent** to persist `custom_prompt` and `custom_suffix` to agent config
3. The factory assembles the full prompt at runtime: `system_prompt + "\n\n" + custom_prompt + "\n\n" + custom_suffix`
4. These fields survive Builder saves (PUT endpoint preserves them during config replacement)

## Tool Library

The **Tool Library** (`/tools`) lists all native tools available for deep agents, grouped by category:

| Category | Tools |
|---|---|
| Web & Search | web_search, web_fetch, web_scrape, web_fetch_all, web_search_news, tavily_search |
| File System | list_files, read_files, write_files, file_system |
| Memory | store_memory, read_memory |
| Reasoning | final_result |
| Delegation | delegate_task |

Each tool shows its name, description, tool ID, and whether it requires an API key.

---

## Tools: Custom Tools & Sandboxed Execution

Deep Agents can call **any custom tool** you define alongside built-in harness tools (filesystem, planning, subagent delegation).

### 1. Custom Tools

The simplest way to define a tool is with the `@tool` decorator. The function's docstring becomes the tool's description.

```python
from langchain.tools import tool

@tool
def slack_send_message(text: str, file_path: str | None = None) -> str:
    """Send a message to Slack, optionally with a file attachment.

    Args:
        text: Text content of the message
        file_path: Optional path to a file to attach
    """
    # ... integration logic here
    return "Message sent."
```

**Key rules for custom tools** (from the [LangChain tools docs](https://docs.langchain.com/oss/python/langchain/tools)):
- Type hints are **required** — they define the tool's input schema
- The docstring should clearly describe the tool's purpose
- Use `snake_case` for tool names
- Return a `string` (plain text), a `dict` (structured data), or a `Command` (state update)

### 2. Tool Resolution Chain

String IDs from the database are resolved to actual Python `@tool` functions at runtime:

```
DB: config.native_tools = ["web_search", "tavily_search"]   ← string IDs
       │
       ▼
TOOL_NAME_MAP                                                ← normalize aliases
[backend/tools/native_tools.py#L72](../../backend/tools/native_tools.py#L72)
       │
       ▼
load_native_tools()                                          ← resolve → @tool function
[backend/tools/native_tools.py#L1390](../../backend/tools/native_tools.py#L1390)
       │
       ▼
available_tools = {                                          ← dict of tool name → callable
    "web_search":    web_search,
    "tavily_search": tavily_search,
    ...
}
       │
       ▼
DeepAgentFactory._load_base_tools()                          ← builds tool list
[backend/services/deepagent_factory.py#L371](../../backend/services/deepagent_factory.py#L371)
       │
       ▼
create_deep_agent(tools=[...])                               ← passed to the agent
```

### 3. LocalShellBackend: Sandboxed Code Execution

When `use_local_sandbox: true` is set in the `DeepAgentConfig`, the factory creates a `LocalShellBackend` rooted at the task workspace. This gives the agent an **`execute`** tool for running shell commands (Python scripts, pip install, etc.).

**Config field** ([`backend/models/deep_agent.py`](../../backend/models/deep_agent.py#L210-L216)):

```python
use_local_sandbox: bool = Field(
    default=False,
    description=(
        "If True, creates a LocalShellBackend sandbox rooted at the task workspace. "
        "The agent gains an `execute` tool for running shell commands (e.g. Python scripts), "
        "and file operations are scoped to the sandbox directory."
    )
)
```

**Factory integration** ([`backend/services/deepagent_factory.py#L255-L282`](../../backend/services/deepagent_factory.py#L255-L282)):

```python
if getattr(config, 'use_local_sandbox', False):
    from deepagents.backends import LocalShellBackend
    from services.workspace_manager import get_workspace_manager

    workspace_mgr = get_workspace_manager()
    sandbox_path = workspace_mgr.get_task_workspace_with_override(
        project_id=project_id, workflow_id=workflow_id, task_id=task_id,
        custom_output_path=custom_output_path,
    )
    sandbox_path.mkdir(parents=True, exist_ok=True)

    local_sandbox_backend = LocalShellBackend(
        root_dir=str(sandbox_path),
        timeout=120,
        max_output_bytes=100000,
        inherit_env=True,
    )

# Then passed to create_deep_agent:
agent_kwargs["backend"] = local_sandbox_backend
```

### 4. DB-Backed Custom Tools (Python Function Type)

Beyond native tools (hardcoded in `native_tools.py`) and `@tool` decorators (code-defined), tools can be stored entirely in the PostgreSQL database as **`PYTHON_FUNCTION`** custom tools. This allows users to define, edit, and manage tools through the UI without any code deployment.

#### Storage Model

**File**: [`backend/models/custom_tool.py`](../../backend/models/custom_tool.py)

Each custom tool is stored in the `custom_tools` table:

| Column | Type | Description |
|--------|------|-------------|
| `tool_id` | String (PK) | Unique ID (e.g. `math_sqrt`) |
| `name` | String | Display name |
| `description` | Text | Tool description (shown to LLM) |
| `tool_type` | String | `"python_function"` |
| `implementation_config` | JSON | `{ code, function_name, args_schema }` |
| `project_id` | Integer (FK) | Scoped to a project |

#### Implementation Config Structure

```json
{
  "code": "import math\ndef sqrt(x: float) -> str:\n    if x < 0:\n        return 'Error: Negative input not supported'\n    return str(math.sqrt(x))",
  "function_name": "sqrt",
  "args_schema": {
    "x": {"type": "float", "description": "Number to find the square root of"}
  }
}
```

#### Runtime Resolution

**File**: [`backend/core/tools/factory.py#L2270-L2350`](../../backend/core/tools/factory.py#L2270-L2350)

When an agent config references custom tools via `config.custom_tools = ["math_sqrt", ...]`, the `AgentFactory` loads them at runtime:

```python
# AgentFactory._load_custom_tools() -> ToolFactory._create_python_function_tool()
# For each tool_id in config.custom_tools:
#   1. Query custom_tools table by tool_id
#   2. exec() the Python code from implementation_config.code
#   3. Wrap the function in StructuredTool with coroutine support
#   4. Bind to agent via create_agent(tools=[...])
```

Key implementation details:

```python
# backend/core/tools/factory.py
async def _create_python_function_tool(tool_config, project_id):
    impl_config = tool_config["implementation_config"]
    
    # 1. exec the user's code
    local_ns = {}
    exec(code_str, {"math": __import__("math"), "json": json, "typing": __import__("typing")}, local_ns)
    fn = local_ns[function_name]
    
    # 2. Create async wrapper
    async def _run(**kwargs) -> str:
        result = fn(**kwargs)
        return str(result)
    
    # 3. Build Pydantic args schema from impl_config.args_schema
    InputModel = create_model(...)
    
    # 4. Return StructuredTool
    return StructuredTool.from_function(coroutine=_run, name=name, description=desc, args_schema=InputModel)
```

#### Usage Example: math_agent (id=40)

Rather than hardcoding a `calculator` tool in `native_tools.py`, we created separate math functions as DB-backed tools:

| tool_id | Function | Code |
|---------|----------|------|
| `math_sqrt` | `sqrt(x)` → `math.sqrt(x)` | `import math` |
| `math_add` | `add(a, b)` → `a + b` | Simple arithmetic |
| `math_multiply` | `multiply(a, b)` → `a * b` | Simple arithmetic |

Agent config:
```json
{
  "custom_tools": ["math_sqrt", "math_add", "math_subtract", "math_multiply", "math_divide"],
  "native_tools": ["ls", "read_file", ...],
  "use_deepagents": false
}
```

This approach offers several advantages over native tools:
- **No code deploy** — Add/edit tools via the `custom_tools` table directly
- **User-defined** — Non-developers can create custom tools through the frontend
- **Scoped to projects** — Each tool can be associated with a specific project
- **No registry needed** — Tools are resolved from DB at runtime, no `TOOL_NAME_MAP` or `TOOL_REGISTRY` maintenance

### 4a. Custom Tool Builder UI

The `CustomToolBuilder` ([`src/features/tools/ui/CustomToolBuilder.tsx`](../../src/features/tools/ui/CustomToolBuilder.tsx)) provides a visual editor for creating and managing custom Python tools.

**Edit flow**: On the Tools page ([`src/features/tools/ToolLibrary.tsx`](../../src/features/tools/ToolLibrary.tsx)), custom tools appear as cards. Hover to reveal an **Edit** (pencil) button that opens the builder pre-loaded with the existing tool data. The `CustomToolBuilder` receives `existingToolId` prop and fetches the tool data via `GET /api/custom-tools/{tool_id}`.

### 4b. Python Code Verification with AI Fix

A **Verify Code** button sits next to the Python Code editor. It calls `POST /api/custom-tools/verify-code` ([`backend/api/tools/routes.py`](../../backend/api/tools/routes.py)) which performs two-stage validation:

| Stage | Method | Catches |
|---|---|---|
| **1. AST Analysis** | `ast.parse()` + name resolution | Undefined variables (e.g. `{a1}` instead of `{a}`), syntax structure issues |
| **2. Compile + Exec** | `compile()` + `exec()` | Syntax errors, missing function definition, non-callable types |

When errors are found and `auto_fix=true`, the backend sends the broken code + error details to an LLM (DeepSeek Chat by default) for a suggested fix:

```
Request:  broken code + error list
Response: { suggested_code, explanation }
```

The frontend shows:
1. **Red/green border** on the code editor indicating validity
2. **Line-by-line error list** with type and message
3. **"Show AI Suggested Fix"** button — reveals the LLM-generated fix
4. **Apply Fix** button — replaces the editor content with the fix
5. **Copy** button on the code editor for easy clipboard sharing

#### Verification Endpoint

```python
POST /api/custom-tools/verify-code
{
  "code": "def my_hello(a, b): ...",
  "function_name": "my_hello",
  "description": "Tool description",
  "auto_fix": true
}

Response:
{
  "is_valid": false,
  "errors": [{"line": 3, "message": "Undefined variable 'a1'", "type": "NameError"}],
  "suggested_code": "def my_hello(a, b): ...",  # AI fixed version
  "explanation": "Fixed typo: a1 → a"
}
```

#### Key implementation details:
- **AST name resolution** walks the function body, collects `param_names ∪ assigned_names ∪ builtins`, and reports any unknown `Name` nodes in Load context
- **LLM provider priority**: DeepSeek Chat → OpenAI → Anthropic → Google (whichever has a configured API key)
- The suggested code is re-verified after LLM generation to catch persistent errors

### 4c. Copy Button on Code Editor

The Python Code editor header includes a **Copy** button that copies the current editor content to the system clipboard. Shows a green "Copied" confirmation for 2 seconds.

---

### 4d. End-to-End Walkthrough: Create a Custom Tool → Link to Agent → Run

This walkthrough covers the full lifecycle of a custom Python function tool, from creation through agent execution.

#### Step 1: Create the Custom Tool

1. Navigate to the **Tools** page in the app (top nav)
2. Click the **"Custom Tool"** tab, then click **"Create Custom Tool"**
3. Fill in the Basic Information:
   - **Tool ID**: `my_hello` (unique identifier, kebab-case)
   - **Tool Name**: `my_hello` (display name)
   - **Description**: `this is for testing tool with python code, use it when query is about testing tools`
4. Select **"Python Function"** as the Tool Type
5. In the Python Function section:
   - **Function Name**: `my_hello`
   - **Python Code**:
     ```python
     def my_hello(a: float, b: float) -> float:
         """My custom function., this is updated version"""
         print(f"hello world, your input is {a} and {b}")
         return a + b
     ```
   - Click **"Verify Code"** to check for errors — green border means valid
6. In **Input Schema**, add two parameters:
   - `a`: type `number`, description `First parameter`
   - `b`: type `number`, description `Second parameter`
7. Click **Save** — you'll see a success message

#### Step 2: Link the Tool to an Agent

1. Navigate to the **Agent Builder** page (top nav)
2. Click **"New Agent"** or edit an existing agent
3. Fill in:
   - **Name**: `my_hello`
   - **Model**: `deepseek-chat` (or any configured model)
4. In the **Tools** section, find **Custom Tools** — add `my_hello` to the list
   - The agent config stores this as `"custom_tools": ["my_hello"]`
5. Set the **System Prompt**:
   ```
   this is for testing tools via my_hello tool, please do use my_hello tool for user greeting
   ```
6. **Save** the agent

What happens under the hood:
- The agent config is saved to the `deep_agent_templates` table in PostgreSQL
- The `custom_tools` field stores the string ID `"my_hello"` — no Python code, just a reference
- At runtime, `AgentFactory._load_custom_tools()` ([`backend/core/agents/factory.py#L1457`](../../backend/core/agents/factory.py#L1457)) resolves the ID to the actual tool

#### Step 3: Start a Chat & Run the Agent

1. Go to the **Chat** page
2. Select the `my_hello` agent from the agent selector
3. Start a new chat session
4. Send a message that the tool can process: `what is 3 + 5?`

What happens at runtime:

```
User: "what is 3 + 5?"
         │
         ▼
POST /api/chat/message/stream
  → session resolved to agent_id=42
  → agent.config loaded from deep_agent_templates
  → config.custom_tools = ["my_hello"]
         │
         ▼
AgentFactory.create_agent(agent_config)
  ├─ LLM created (deepseek-chat)
  ├─ Native tools loaded (ls, read_file, ...)
  ├─ Custom tools loaded:
  │     └─ AgentFactory._load_custom_tools(["my_hello"])
  │           ├─ Query custom_tools WHERE tool_id='my_hello'
  │           ├─ ToolFactory.create_tool(tool_config)
  │           │     └─ exec(code) → wraps in StructuredTool
  │           └─ Returns [StructuredTool(name="my_hello")]
  └─ create_agent(model, tools=[..., my_hello], system_prompt=...)
         │
         ▼
Agent receives: "what is 3 + 5?"
  → LLM sees available tools: [my_hello(a: float, b: float) -> float]
  → LLM decides: call my_hello(a=3.0, b=5.0)
  → Tool executes: returns 8.0
  → LLM responds: "3 + 5 equals 8."
         │
         ▼
Response streamed to UI via SSE
```

#### Step 4: Verify It Works

You can verify the tool was loaded correctly by checking the backend logs:

```
📦 Custom tool IDs from config: ['my_hello']
✓ Loaded 1 custom tools: ['my_hello']
🔧 TOOLS LOADED: ['ls', 'read_file', ..., 'my_hello']
```

The tool name appears in the final tools list alongside native tools, confirming it was successfully bound to the agent.

#### Key Points

| Stage | Storage | Resolution |
|---|---|---|
| **Tool Creation** | `custom_tools` table (full Python code + schema) | `POST /api/custom-tools` |
| **Tool Linking** | `deep_agent_templates.config.custom_tools` (string ID only) | UI checkboxes / manual edit |
| **Runtime** | `AgentFactory._load_custom_tools()` queries DB, `exec()`s code, wraps in `StructuredTool` | `create_agent(tools=...)` |

- The tool's **description** field is what the LLM sees to decide when to call the tool — make it descriptive
- The **system prompt** can reinforce when to use the tool
- Custom tools are resolved **at agent creation time**, not at startup — so new tools are immediately available without restarting the server
- The tool function's **type hints** define the input schema that the LLM sees
- Tools must be **synchronous** (not `async def`) — the framework wraps them automatically

---

When a `backend` is passed, the harness automatically registers the following tools on top of the existing middleware tools:

| Tool | Description |
|---|---|
| `ls` | List files in a directory |
| `read_file` | Read file contents (with pagination and multimodal support) |
| `write_file` | Create new files |
| `edit_file` | Perform exact string replacements in files |
| `glob` | Find files matching a glob pattern |
| `grep` | Search file contents |
| `execute` | Run shell commands (sandbox backends only) |
| `task` | Spawn a subagent to handle a delegated task |
| `write_todos` | Manage a structured todo list |

### 4. MCP Tools

Deep Agents also support [Model Context Protocol (MCP)](https://docs.langchain.com/oss/python/deepagents/tools#mcp-tools) servers. LangConfig's existing MCP infrastructure handles this:

- **MCP Manager**: [`backend/services/mcp_manager.py`](../../backend/services/mcp_manager.py) — server lifecycle and tool discovery
- **MCP Config API**: [`backend/api/mcp/config.py`](../../backend/api/mcp/config.py) — per-user credentials
- **MCP Tool Schemas**: [`backend/schemas/mcp_tools.py`](../../backend/schemas/mcp_tools.py) — server definitions

### 5. Data Analysis Pattern (Walkthrough)

The data analysis pattern combines a sandbox backend with a custom `save_analysis_result` tool, following the [official tutorial](https://docs.langchain.com/oss/python/deepagents/data-analysis).

#### 5a. The `save_analysis_result` Native Tool

A custom `@tool` registered in [`backend/tools/native_tools.py`](../../backend/tools/native_tools.py#L1393-L1411):

```python
@tool
def save_analysis_result(text: str, file_path: str | None = None) -> str:
    """Save analysis report and optionally copy an attached file (e.g. a plot)
    to the output directory.

    Args:
        text: Text content of the analysis report
        file_path: Optional path of a file attachment in the sandbox
    """
    output_dir = Path("./_analysis_output")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "analysis_report.txt"
    report_path.write_text(text)
    if file_path:
        fp = Path(file_path)
        if fp.exists():
            local_path = output_dir / fp.name
            local_path.write_bytes(fp.read_bytes())
    return f"Analysis results saved to {output_dir.resolve()}."
```

Registered in 4 places:
| # | Location | Purpose |
|---|---|---|
| 1 | `@tool` function definition | The implementation |
| 2 | `TOOL_NAME_MAP` | Normalizes string ID → canonical name |
| 3 | `available_tools` (in `load_native_tools()`) | Runtime tool resolution |
| 4 | `TOOL_REGISTRY` | UI metadata (name, description, category) |

#### 5b. Static File Serving

Generated files (charts, reports) are served via a FastAPI endpoint in [`backend/main.py`](../../backend/main.py#L255-L280):

```python
@app.get("/api/files/{filename:path}")
async def serve_output_file(filename: str):
    """Serve generated files from backend/outputs/."""
    from services.workspace_manager import get_workspace_manager
    workspace_mgr = get_workspace_manager()

    # Try default dir first (chat sessions)
    file_path = workspace_mgr.base_dir / "default" / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))

    # Fallback: search all output directories
    found = list(workspace_mgr.base_dir.rglob(filename))
    if found:
        return FileResponse(str(found[0]))
```

This allows agents to embed images in chat responses using:
```markdown
![Sales Analysis](/api/files/sales_analysis_chart.png)
```

#### 5c. Full Agent Workflow

```
1. Agent reads CSV data with read_file
2. Agent writes a Python analysis script with write_file
3. Agent runs the script with execute("python3 analysis.py")
   → pandas + matplotlib generate summaries & plots
4. Agent saves results with save_analysis_result
5. Agent displays the chart inline in the chat response:
   ![Chart](/api/files/sales_analysis_chart.png)
```

#### 5d. Uploading CSV Files

The existing chat file upload button (paperclip icon) also copies CSV files to the sandbox workspace for agent access.

**How it works** ([`backend/api/chat/routes.py#L1658`](../../backend/api/chat/routes.py#L1658)):

```python
# When a CSV file is uploaded via the chat upload endpoint, it's automatically
# copied to outputs/default/ so the agent can read it via read_file / execute.
if file.filename.lower().endswith('.csv'):
    ws_mgr = get_workspace_manager()
    sandbox_path = ws_mgr.base_dir / "default" / file.filename
    sandbox_path.parent.mkdir(parents=True, exist_ok=True)
    sandbox_path.write_bytes(content)
```

**Agent access**: Once uploaded, the agent can access the CSV with:
```
read_file("your_file.csv")     # Read the CSV content
execute("python3 -c \"import pandas; print(pandas.read_csv('your_file.csv'))\"")
```

The file is also indexed for RAG (existing behavior), so the agent can answer questions about it without reading the raw file.

**Auto-analysis trigger** ([`src/features/chat/ui/MessagesPanel.tsx`](../../src/features/chat/ui/MessagesPanel.tsx#L556)):
After a CSV upload completes, the frontend automatically sends an analysis
message to the agent — no manual typing required. The agent then runs the
full Auto-Analysis Workflow defined in its system prompt.

**CSV skip indexing**: CSV files skip RAG indexing (`IndexingStatus.READY`
is set immediately) since they're accessed directly via the sandbox, not via
semantic search. This prevents the "failed" status indicator that would appear
when the RAG indexer fails on CSV content ([`backend/api/chat/routes.py`](../../backend/api/chat/routes.py#L1700)).

#### 5e. Creating the Agent via UI

1. Open **DeepAgent Builder** → **New Agent**
2. Fill in:
   - **Name**: `data_analysis_agent`
   - **Model**: `deepseek-chat` (or any)
   - **Native Tools**: select `save_analysis_result`
   - **LocalSandbox**: ✅ enable the checkbox (under Memory & Storage section)
3. **System Prompt** (paste in CUSTOM or system_prompt field):
   ```text
   You are a data analysis agent with a local sandbox environment.

   Capabilities:
   - read_file: read CSV and other data files
   - write_file: create Python analysis scripts
   - execute: run Python scripts (pandas, matplotlib are available)
   - save_analysis_result: save analysis reports and plot files

   Workflow:
   1. First use read_file to examine the data
   2. Write a Python script with pandas + matplotlib via write_file
   3. Execute it with execute("python3 <script>.py")
   4. Save results with save_analysis_result

   When displaying generated files in your response, use markdown image
   syntax with the /api/files/ URL:
     ![Chart description](/api/files/filename.png)
   ```

#### 5f. Standalone Demo

A self-contained example script at [`learning/phase5/examples/data_analysis_agent.py`](examples/data_analysis_agent.py) can be run directly with uv:

```bash
cd backend && uv run data_analysis_agent.py
```

This script:
- Creates a `LocalShellBackend` sandbox at `./_data_analysis_sandbox/`
- Uploads a sample CSV (5 days of sales data)
- Defines a `save_analysis_result` tool
- Creates a DeepAgent with `create_deep_agent(tools=[save_analysis_result], backend=sandbox)`
- Sends an analysis request and streams the response

#### 5g. Frontend `use_local_sandbox` Checkbox

Added to [`DeepAgentBuilder.tsx`](../../src/features/agents/ui/DeepAgentBuilder.tsx) in the **Memory & Storage** section:

```tsx
// Local Sandbox toggle
<div className="mt-4">
  <label className="flex items-center gap-2 text-sm font-medium ...">
    <input
      type="checkbox"
      checked={config.use_local_sandbox ?? false}
      onChange={(e) => updateConfig('use_local_sandbox', e.target.checked)}
    />
    LocalSandbox (Code Execution)
  </label>
  <p className="text-xs ...">
    Enable a local shell sandbox for code execution. The agent gains an
    <code>execute</code> tool for running Python scripts and shell commands.
  </p>
</div>
```

#### 5h. Auto-Analysis System Prompt

For **agent 37** (`analysis agent`), the system prompt includes an
**Auto-Analysis Workflow** that triggers immediately after CSV upload:

```text
Auto-Analysis Workflow (triggered when user uploads a CSV file):
1. IMMEDIATELY use read_file to examine the uploaded CSV
2. Generate a comprehensive overview covering 10 key metrics:
   - Row count, column count, data types, missing values
   - Descriptive statistics, distributions, correlations
   - Time-based trends, top/bottom values, outliers
   - Group aggregations, category summaries
3. From the 10 metrics, identify the top 3 most impactful findings
4. Provide a detailed analysis combining all insights
5. Present key takeaways and actionable recommendations
6. Be ready to answer follow-up queries about the data
```

The prompt also instructs the agent to use `matplotlib subplots(ncols=2)`
when generating charts, keeping visualizations compact with 2 charts per row.

#### 5i. Chat UI Adjustments

Several frontend changes improve the chat experience:

| Change | File | Effect |
|---|---|---|
| Wider modal | `GlobalChatModal.tsx` | `max-w-7xl` → `max-w-[95vw]` |
| Full-width messages | `MessagesPanel.tsx` | Removed inner `max-w-6xl` limit, uses `w-full mx-8` |
| Wider message bubbles | `MessagesPanel.tsx` | `max-w-3xl` → `max-w-6xl` (50% wider) |
| Smaller font | `MessagesPanel.tsx` | `prose-sm` → `prose-xs` at `0.81rem` |
| Upload auto-refresh | `SessionDocumentsPanel.tsx` | Document list refreshes via `refreshKey` prop |

### 6. Skills System for Data Analysis

The **Skills system** packages expertise into discoverable `SKILL.md` files that
agents automatically load. Unlike Native Tools (which contain executable code),
Skills are **structured prompts** that tell the agent *how* to use existing tools.

#### 6a. Skill vs Native Tool

| | **Native Tool** | **Skill** |
|---|---|---|
| What | Python `@tool` function | `SKILL.md` file with metadata + instructions |
| Execution | Runs actual code | Injected into agent system prompt |
| Location | `tools/native_tools.py` | `skills/builtin/<name>/SKILL.md` |
| Registration | 4 places in Python | Auto-discovered from filesystem |
| Lifecycle | Code deployment | Versioned, tagged, usage-tracked |

#### 6b. The `data-analysis` Skill

Created at [`backend/skills/builtin/data-analysis/SKILL.md`](../../backend/skills/builtin/data-analysis/SKILL.md).

This skill unifies **CSV** and **SQL** analysis into one workflow:

```
data-analysis SKILL.md
├── CSV  → read_file + pandas
├── SQL  → execute("python3 -c \"from sqlalchemy import...\"") + pandas
└── Unified pandas analysis + matplotlib charts
```

Key capabilities:

| Data Source | How it works | Tools Used |
|---|---|---|
| **CSV (uploaded)** | Agent reads file via `read_file` + `pandas.read_csv()` | `read_file`, `execute` |
| **SQL (PostgreSQL)** | Agent runs Python with `sqlalchemy` + `pandas.read_sql()` | `execute` (sandbox inherits `DATABASE_URL` env) |
| **Visualization** | Agent writes matplotlib script and executes it | `write_file`, `execute` |
| **Saving results** | Agent calls the native tool | `save_analysis_result` |

No new native tools were needed — the Skill leverages the existing sandbox
(`execute`, `read_file`, `write_file`) and the existing `DATABASE_URL`
connection configured in [`backend/db/database.py`](../../backend/db/database.py).

#### 6c. How It Gets Loaded

Skills are auto-discovered on server startup by the `SkillRegistry`
([`backend/core/skills/registry.py`](../../backend/core/skills/registry.py)):

```
skills/builtin/data-analysis/SKILL.md
  → SkillLoader parses YAML frontmatter + markdown instructions
  → SkillRegistry indexes in memory + persists to DB
  → SkillMatcher matches against user context
  → Instructions injected into agent system prompt
```

No UI configuration is needed — placing the file in the `skills/builtin/`
directory is sufficient.

#### 6d. Extending to Other Databases

The same pattern works for any SQLAlchemy-supported database:

- **SQLite**: `sqlite:///path/to/db.sqlite`
- **MySQL**: `mysql+pymysql://user:pass@host/db`
- **SQL Server**: `mssql+pyodbc://user:pass@host/db`

The agent just needs the connection string passed in the analysis request.

#### 6e. DB → Sandbox Integration in LangConfig

LangConfig's `deepagent_factory.py` implements the DB→sandbox pattern:

1. **`DeepAgentConfig.skills`** ([`models/deep_agent.py`](../../backend/models/deep_agent.py#L237)) stores skill IDs as `List[str]`
2. **At agent creation**, the factory ([`deepagent_factory.py`](../../backend/services/deepagent_factory.py#L293)):
   - Loads skill records from PostgreSQL `skills` table
   - Reconstructs `SKILL.md` from DB fields (name, description, tags, instructions)
   - Writes to `outputs/default/skills/<id>/SKILL.md` in the sandbox
   - Passes `skills=[str(skills_root)]` to `create_deep_agent()`
3. **Agent uses progressive disclosure** — reads SKILL.md only when user request matches skill description

#### 6f. Agent-Generated Skills (Meta-Skills)

Skills can now create other skills — the agent generates, designs, and saves reusable skills to the database.

**Architecture:**

```
User: "Create a skill for analyzing Twitter data"
      │
      ▼
Agent (research agent with skill-generator skill)
      │
      ├── 1. Reads skill-generator/SKILL.md (meta-skill)
      ├── 2. Researches best practices (internet-research skill)
      ├── 3. Designs name, description, tags, triggers, instructions
      ├── 4. Calls create_skill() native tool
      │         └── writes to PostgreSQL skills table
      └── 5. Confirms → skill appears in Skills Library
```

**Components:**

| Component | Where | Purpose |
|---|---|---|
| `create_skill` tool | [`native_tools.py`](../../backend/tools/native_tools.py#L1420) | Agent writes skills to DB |
| `update_skill` tool | [`native_tools.py`](../../backend/tools/native_tools.py#L1460) | Agent updates existing skills |
| `delete_skill` tool | [`native_tools.py`](../../backend/tools/native_tools.py#L1500) | Agent deletes skills |
| `skill-generator` skill | [`skills/builtin/skill-generator/SKILL.md`](../../backend/skills/builtin/skill-generator/SKILL.md) | Meta-skill teaching agents to design and create skills |

**Key design decisions:**
- **No new UI** — users create skills by chatting with the agent, not filling forms
- **Full CRUD via tools** — agent can create, update, and delete skills
- **Skill Generator is itself a skill** — uses progressive disclosure like any other skill
- **Research Agent as unified agent** — one agent with multiple skills replaces many specialized agents

#### 6g. Skills Library UI Improvements

| Change | Description |
|---|---|
| **Navigation tab** | Added "Skills" button to `ModernHeader` toolbar (Prompt and Community tabs) |
| **Create Skill button** | Blue button in Skills Library header, opens `SkillBuilderModal` |
| **Detail modal** | Full-screen modal replaces cramped bottom panel — shows all fields, triggers, instructions, examples |
| **DB-direct queries** | `list_skills` and `get_skill` endpoints now query PostgreSQL directly (not registry cache) so tool-created skills appear immediately |
| **Reload button** | Fires `POST /api/skills/reload-all` to sync filesystem → DB, then refreshes list |

#### 6h. Key Learnings

| Lesson | Detail |
|---|---|
| **No code needed** | SQL integration via Skill required zero new Python code — just instructions in `SKILL.md` |
| **Leverage sandbox** | The sandbox's `execute` + `inherit_env=True` gives full access to existing tools |
| **Skills vs Tools** | Skills = "what to do" (prompt), Tools = "how to do it" (code) |
| **Auto-discovery** | Skills are auto-loaded from disk, no DB setup needed |

#### 5j. Key Learnings

| Lesson | Detail |
|---|---|
| **Directory alignment** | `LocalShellBackend` root and `FilesystemMiddleware` workspace must point to the same directory. Chat sessions default to `outputs/default/`. |
| **File sharing** | Without `embedding base_url` in DeepAgent responses, charts must be served via a separate `/api/files/` static endpoint. |
| **Dependencies** | `pandas` and `matplotlib` must be added to `backend/pyproject.toml` for analysis scripts. |
| **Untracked files** | Generated sandbox dirs (`_data_analysis_sandbox/`, `_analysis_output/`) should be gitignored. |

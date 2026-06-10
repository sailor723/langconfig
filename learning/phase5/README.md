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

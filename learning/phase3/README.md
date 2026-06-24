# Phase 3: Memory Systems

> How LangConfig agents actively manage long-term memory via tool-based persistence, and how context is assembled from multiple sources.

> **Last refreshed 2026-06-24.** Major refactor: `SimpleMemory` replaced the deprecated `AgentMemorySystem` (which was a VectorStore wrapper). See [§ Drift Log](#drift-log-since-phase-3) for details.

---

## SimpleMemory (current implementation)

**File**: [`backend/core/agents/memory.py`](../../backend/core/agents/memory.py)

`SimpleMemory` is the current text-based memory system. It gives agents **explicit memory control through tools** — agents decide what to remember, search their own memories, and build up project-specific knowledge over time.

### Memory Types

```python
class MemoryType(str, Enum):
    FACT = "fact"           # Factual information about the project
    DECISION = "decision"   # Architectural or design decisions
    PATTERN = "pattern"     # Code patterns or conventions discovered
    LEARNING = "learning"   # Bugs fixed, lessons learned
    CONTEXT = "context"     # Important contextual information
    RELATIONSHIP = "relationship"  # Relationships between components
```

### Two Memory Tools

| Tool | Schema | Behavior |
|---|---|---|
| `memory_store` | `MemorySaveArgs` | Saves a memory to PostgreSQL `agent_memories` table (or in-memory dict fallback) |
| `memory_recall` | `MemoryRecallArgs` | Retrieves memories by query (full-text LIKE search, no embeddings) |

### Tool Argument Schemas (Pydantic Guardrails)

- **`MemorySaveArgs`** (L47): `memory_content` (str), `memory_type` (enum), `importance` (1-10), `tags` (list, optional)
- **`MemoryRecallArgs`** (L101): `query` (str), `memory_type` (optional filter), `limit` (1-15), `min_importance` (optional)

### Scoping & Multi-Tenancy

Each memory is scoped to a `(project_id, agent_id)` pair. Memories are stored in the `agent_memories` table with composite index on `(project_id, agent_id)`.

### How Memory Tools Are Loaded

**File**: [`backend/core/agents/tool_loader.py`](../../backend/core/agents/tool_loader.py#L370-L396)

```python
async def ToolLoader.load_memory(vector_store, project_id, task_id):
    from core.agents.memory import get_or_create_memory
    from db.database import AsyncSessionLocal

    db_session = AsyncSessionLocal()
    memory_system = get_or_create_memory(
        project_id=project_id,
        agent_id=f"task_{task_id}",
        db_session=db_session,
    )
    memory_tools = memory_system.create_memory_tools()
    # Returns [memory_store, memory_recall] — ready for agent binding
```

The memory tools are produced as `StructuredTool` instances (via `StructuredTool.from_function()`) and mixed into the agent's tool list alongside native, custom, and template tools.

> **Note**: The `vector_store` parameter is currently accepted but not used by `SimpleMemory` (kept for backward compat with the old `AgentMemorySystem` signature).

---

## Vector Store Initialization

**File**: [`backend/services/llama_config.py`](../../backend/services/llama_config.py)

### Embedding Model Priority Chain

```
1. Ollama (local) — nomic-embed-text:latest (768d)
2. OpenAI — text-embedding-3-large (1024d, multimodal)
3. HuggingFace — all-MiniLM-L6-v2 (384d, fallback)
```

### PGVectorStore Setup

```python
def get_vector_store(project_id: int, embed_dim=None) -> PGVectorStore:
    table_name = f"data_project_index_{project_id}"
    vector_store = PGVectorStore.from_params(
        database=database_name,
        host=...,
        port=...,
        user=...,
        password=...,
        table_name=table_name,
        embed_dim=embed_dim,
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
        }
    )
```

Key details:
- **Multi-tenancy**: Each project gets its own table (`data_project_index_{project_id}`)
- **HNSW indexing**: Configurable parameters for recall vs speed trade-off
- **Auto-dimension detection**: `get_embedding_dimension()` returns 1024 (OpenAI), 768 (Ollama nomic), or 384 (HuggingFace)
- **HyDE support**: LiteLLM proxy configures an LLM in Settings for hypothetical document embeddings

---

## Memory API Routes

**File**: [`backend/api/memory/routes.py`](../../backend/api/memory/routes.py)

Prefix: `/api/memory`

| Endpoint | Method | Description |
|---|---|---|
| `/api/memory/projects/{project_id}/memories` | GET | List memories with filters (type, agent_id, importance) |
| `/api/memory/projects/{project_id}/memories/search` | POST | Semantic search via VectorStore |
| `/api/memory/projects/{project_id}/memories/stats` | GET | Aggregated statistics (by type, by agent, avg importance) |

The list endpoint queries the underlying PostgreSQL table directly (bypassing LangChain's VectorStore) using raw SQL with metadata filters.

---

## Context Synthesis

**File**: [`backend/core/context/synthesis.py`](../../backend/core/context/synthesis.py)

Whenever an agent runs, context is assembled **just-in-time** from multiple sources:

```
assemble_context_package(state)
  → WorkflowState (current graph state, scratchpad, handoff summaries)
  → Memory results (via memory_retrieve tool calls during execution)
  → Global agent instructions (system prompt)
  → Token budget allocation
```

### Compaction Flow

```python
synthesize_and_compact_context(state, max_tokens=4000)
  → 1. Measure token count of scratchpad
  → 2. If above compaction_threshold (75% of max):
       Use LLM to summarize early history via COMPACTION_PROMPT
       Preserve recent N steps uncompacted (default: 3)
    → 3. If still over budget:
       Hard truncation fallback (drop oldest entries)
```

The compaction prompt uses XML-tagged context and clear compression strategies:
```
Summarize Early History → Preserve Key Details → Maintain Actionability → Format output
```

---

## Context Compactor

**File**: [`backend/core/context/compactor.py`](../../backend/core/context/compactor.py)

A dedicated `ContextCompactor` class with:

```python
class ContextCompactor:
    def __init__(self, llm, max_context_tokens=8000,
                 compaction_threshold=0.75, preserve_recent_steps=3):
        ...

    def needs_compaction(self, state) -> bool
    def compact(self, state) -> WorkflowState
```

- Uses LLM summarization for intelligent compression
- Preserves recent handoff steps without compaction
- Rough token estimation (4 chars/token) with `tiktoken` fallback in synthesis.py

---

## Memory-Aware Agent Prompt

**File**: [`backend/core/agents/memory.py`](../../backend/core/agents/memory.py#L388)

Agents configured with memory tools receive a system prompt that teaches them *when* to use memory:

```
MEMORY TOOLS AVAILABLE:
  1. memory_store() — Save important facts, decisions, patterns
  2. memory_retrieve() — Search using natural language

WHEN TO USE:
  - Before implementing → check for existing patterns/decisions
  - After discovering something → save to memory
  - When debugging → search for related past issues
```

---

## Two Persistence Layers: thread_id vs agent_id

This is crucial to understand: LangConfig has **two separate persistence systems** serving different purposes, each with its own scoping key.

| # | Layer | Scoped By | What It Persists | Technology | When It's Used |
|---|-------|-----------|-----------------|------------|----------------|
| **1** | **Checkpointer** | `thread_id` | Graph state, message history across conversation turns | `PostgresSaver` (PostgreSQL) | Every `workflow.ainvoke()` call |
| **2** | **Memory Tools** | `agent_id` + `project_id` | Facts, decisions, patterns the agent learns | `agent_memories` table (PostgreSQL) | Agent calls `memory_store()` / `memory_recall()` |

> **Note**: An earlier draft of this doc described a third layer ("Store API" via `namespace`). That layer was documented but **never implemented** — see [Drift Log](#drift-log-since-phase-3) for details. The current `create_deep_agent()` call doesn't use the LangGraph Store API.

### Layer 1: Checkpointer (thread_id)

**Files**: [`checkpointing/manager.py`](../../backend/core/workflows/checkpointing/manager.py), [`runner.py`](../../backend/core/workflows/runner.py), [`executor.py`](../../backend/core/workflows/executor.py)

The **checkpointer** is LangGraph's native persistence. It saves the entire graph state after each node execution, enabling:
- **Conversation continuity** — Resume a chat across turns
- **HITL resumption** — Pause → wait for approval → resume from same state
- **Error recovery** — Roll back to last successful checkpoint

```python
# In runner.py — each execution gets a unique thread_id
thread_id = execution_id or f"run_{task_id}_{uuid4().hex[:8]}"
config = {"configurable": {"thread_id": thread_id}}
result = await workflow.ainvoke(initial_state, config)
```

```python
# In executor.py — workflow executions
config = {
    "configurable": {
        "thread_id": f"workflow_{workflow.id}_task_{task_id}"
    },
    "callbacks": [callback_handler],
}
```

```python
# In chat/routes.py — chat sessions use session_id as thread_id
result = agent_instance.invoke(
    {"messages": [new_message]},
    config={"configurable": {"thread_id": session.session_id}}
)
```

**thread_id patterns used across the codebase:**
| Context | thread_id format |
|---|---|
| Simple agent execution | `run_{task_id}_{uuid_hex}` |
| Workflow execution | `workflow_{workflow.id}_task_{task_id}` |
| Chat session | `{session.session_id}` (UUID) |
| Node-level execution | `node_{node_id}_task_{task_id}` |

The checkpointer stores data in the `checkpoints` and `checkpoint_blobs` PostgreSQL tables (created by `PostgresSaver.setup()`).

```sql
-- Checkpoints are queried by thread_id pattern
SELECT checkpoint, metadata, created_at
FROM checkpoints
WHERE checkpoint_namespace = 'langconfig_workflows'
AND checkpoint_id LIKE 'run_42_%'
ORDER BY created_at DESC
LIMIT 1;
```

### Layer 2: Memory Tools (agent_id + project_id)

**File**: [`core/agents/memory.py`](../../backend/core/agents/memory.py)

The **memory tools** are agent-facing tools that use semantic search over a VectorStore. They are **independent of `thread_id`** — they use `agent_id` (task-scoped) and `project_id`.

```python
# In factory.py — memory tools are loaded with agent_id, NOT thread_id
memory_system = AgentMemorySystem(
    vector_store=vector_store,
    project_id=project_id,
    agent_id=f"task_{task_id}"  # ← task-scoped, stable across runs
)
```

Key distinction from the checkpointer:

| Aspect | Checkpointer (thread_id) | Memory Tools (agent_id) |
|---|---|---|
| **What it stores** | Graph state, messages | Semantic facts, decisions |
| **How it's accessed** | Automatically by LangGraph | Agent explicitly calls tools |
| **Search** | Exact thread_id lookup | Semantic similarity |
| **Scope** | Per conversation run | Cross-conversation (project-wide) |
| **LLM involvement** | None | Agent decides what/when to save |
| **Data model** | Binary blobs + JSON | Embeddings + metadata |

### Layer 3: Store API (namespace)

**File**: [`checkpointing/manager.py`](../../backend/core/workflows/checkpointing/manager.py#L178-L250)

The **Store** is LangGraph v1.0's new long-term memory API. Unlike the checkpointer (per-thread) and memory tools (agent-driven), the Store enables **cross-thread, cross-session** memory via namespaced key-value storage.

```python
# Initialized during app startup (stateless, global instance)
store = await initialize_store()

# Passed to workflow config
config = {
    "configurable": {
        "thread_id": thread_id,
        "store": store  # ← enables runtime.store API
    }
}

# Agents access it via runtime.store during execution
# runtime.store.put(namespace, key, value)  — save cross-session
# runtime.store.get(namespace, key)         — retrieve cross-session
```

The Store uses `AsyncPostgresStore` which stores data in `store` and `store_blobs` PostgreSQL tables.

### Summary: Which One to Use?

| You need... | Use... |
|---|---|
| Resume conversation across turns | Checkpointer (`thread_id`) |
| Agent remembers project facts across conversations | Memory Tools (`agent_id`) |
| Cross-session, cross-agent shared knowledge | Store API (`namespace`) |
| Rollback on error | Checkpointer (`thread_id`) |

---

## Key Takeaways

1. **Active, not passive** — Memory is an agent capability, not just RAG. Agents decide what to save and when to retrieve.
2. **Two-pronged system** — `SimpleMemory` (agent-facing tools) + `ContextSynthesis`/`Compactor` (framework-managed context window)
3. **Two persistence layers (only)** — Checkpointer (thread_id, graph state) + Memory Tools (agent_id, semantic facts). The documented "Store API" layer was never implemented.
4. **thread_id is for checkpointing, NOT memory** — The `SimpleMemory` uses `agent_id` + `project_id`, completely independent of LangGraph's `thread_id`
5. **Multi-tenant by project_id** — Each project gets its own row set in the `agent_memories` table
6. **Graceful degradation** — Missing VectorStore just skips memory tools (no crash), compaction has hard-truncation fallback
7. **Embedding flexibility** — Priority chain from local (Ollama) → cloud (OpenAI) → fallback (HuggingFace)

---

## Drift Log (since Phase 3)

**Refreshed 2026-06-24.** Phase 3 was the "Memory Systems" phase. The codebase has evolved significantly: the original `AgentMemorySystem` (VectorStore-based) was deprecated in favor of `SimpleMemory` (text-based + PostgreSQL). This section tracks what changed so the doc stays useful.

### File size growth

| File | Phase 3 size | Current (2026-06-24) | Delta | Notes |
|---|---|---|---|---|
| `backend/core/agents/memory.py` | (smaller, no SimpleMemory) | **531 lines** | +531 | Now contains SimpleMemory (current) + deprecated AgentMemorySystem wrapper + module-level create_memory_tools |
| `backend/core/context/synthesis.py` | (smaller) | **488 lines** | +488 | Added handoff text formatting, context extraction |
| `backend/core/context/compactor.py` | (smaller) | **247 lines** | +247 | |
| `backend/api/memory/routes.py` | (smaller) | **337 lines** | +337 | |
| `backend/services/llama_config.py` | (smaller) | **354 lines** | +354 | Now mostly used by RAG, not memory |

### What was added (not in Phase 3)

| Feature | When | Where | Why missing from Phase 3 doc |
|---|---|---|---|
| **SimpleMemory class** | Phase 4 | `memory.py:168` | Replaced VectorStore-based AgentMemorySystem with text-based + PostgreSQL |
| **Memory prompt template** | Phase 4 | `memory.py:332, 400` | Teaches agents *when* to use memory tools |
| **Backward compat shim** | Phase 4 | `memory.py:518` | `AgentMemorySystem` kept as wrapper around SimpleMemory |
| **Tool extraction to `tool_loader.py`** | Phase 5 | `tool_loader.py:370` | Memory loading moved out of factory.py |
| **DELETE memory endpoint** | Phase 4 | `api/memory/routes.py:257` | Single memory deletion |
| **CLEAR project memories endpoint** | Phase 4 | `api/memory/routes.py:294` | Bulk clear |

### What BROKE since Phase 3

| Item | Phase 3 claim | Reality | When broken |
|---|---|---|---|
| **VectorStore for memory** | Tools use PGVectorStore with semantic search | Tools use **text-only LIKE search** (no embeddings) | Phase 4 |
| **`memory_retrieve` tool** | Listed in README | Actually **`memory_recall`** (typo or rename) | Phase 4 |
| **`MemorySearchArgs` schema** | Listed in README | Actually **`MemoryRecallArgs`** | Phase 4 |
| **`AgentMemorySystem` as main class** | Documented as the primary entry | **DEPRECATED**, replaced by `SimpleMemory` | Phase 4 |
| **Layer 3: Store API (namespace)** | Documented as 3rd persistence layer | ❌ **Not implemented** (claim only) | Never implemented |
| **Line numbers** | factory.py#L1467-L1492 | Now in `tool_loader.py:370` | Phase 5 |

### What was REMOVED since Phase 3

| Item | Where removed | Notes |
|---|---|---|
| `AgentMemorySystem` as standalone | `memory.py:518` | Now deprecated wrapper only |

### Dead code (verified 2026-06-24)

| Code | Lines | Status | Notes |
|---|---|---|---|
| `class AgentMemorySystem` | `memory.py:518-531` | DEPRECATED wrapper | Just instantiates `SimpleMemory`. Used for backward compat. Safe to delete if no external callers. |
| `def create_memory_tools(project_id, agent_id)` (module-level) | `memory.py:439-516` | DEAD CODE | Unused — only `SimpleMemory.create_memory_tools()` (method, L198) is called by `tool_loader.py:391` |

### Recommendations

**Priority 1 (high signal, low risk) — DONE 2026-06-24:**
- ✅ **Refreshed README**: replaced `AgentMemorySystem` references with `SimpleMemory`
- ✅ **Fixed tool names**: `memory_retrieve` → `memory_recall`
- ✅ **Fixed schema names**: `MemorySearchArgs` → `MemoryRecallArgs`
- ✅ **Updated line numbers**: factory.py → tool_loader.py
- ✅ **Added Drift Log** section

**Priority 2 (medium effort, low risk) — DONE 2026-06-24:**
- ✅ **Remove `AgentMemorySystem` class** (~18 lines) — deprecated wrapper
- ✅ **Remove module-level `create_memory_tools()`** (~16 lines) — unused
- ✅ **Deduplicate memory prompt** — extracted shared `_format_memories_for_display()` helper used by both `_recall_from_db` and `_recall_from_inmem`
- ✅ **`vector_store` param** — already removed (SimpleMemory has no such param)
- ✅ **Audit `services/llama_config.py`** — removed `get_langchain_vector_store()` (~99 lines, dead since AgentMemorySystem was deleted)

**Priority 3 — DONE 2026-06-24 (with revisions):**
- ✅ **Migrated to DeepAgent's `MemoryMiddleware`** — added in commit `2fad2ab` and `32d008c`
- AGENTS.md is loaded per-project at `.workspace_data/projects/{id}/AGENTS.md`
- Loaded into system prompt via `MemoryMiddleware.wrap_model_call()`
- UI: "AGENTS.md" button in `ModernHeader` opens editor modal
- Per-project scope (chosen over per-user or global)
- Default ON, opt-out via `config.disable_memory_middleware = True`

See [§ Final System Prompt Walkthrough](#final-system-prompt-walkthrough) below for how it composes at runtime.

---

## Final System Prompt Walkthrough

When a DeepAgent runs in this project, the system prompt sent to the LLM is built in **7 layers**, in order:

```
┌─────────────────────────────────────────────────────────────────────┐
│ [1] AGENT'S CONFIGURED SYSTEM PROMPT                                │
│     Source: agent.config.system_prompt                              │
│     Example: "You are a helpful AI assistant with planning, ..."   │
│     197 chars for demo_deep_agent                                   │
├─────────────────────────────────────────────────────────────────────┤
│ [2] LANGUAGE INSTRUCTION                                            │
│     Source: settings.language (e.g. "zh")                           │
│     Example: "\n\n**Language**: Respond in Chinese."                │
│     ~50 chars (only if language != en/en-US/en-GB)                  │
├─────────────────────────────────────────────────────────────────────┤
│ [3] AGENTS.MD BLOCK ← MemoryMiddleware                              │
│     Source: .workspace_data/projects/{id}/AGENTS.md                 │
│     Wrapped in: <agent_memory>...</agent_memory>                    │
│     4,374 chars for project 1                                       │
│     Contents: project base, settings resolution, KB, tools,         │
│               conventions, memory guidelines, notes                 │
├─────────────────────────────────────────────────────────────────────┤
│ [4] MEMORY_GUIDELINES BLOCK ← MemoryMiddleware                      │
│     Source: hardcoded in deepagents middleware/memory.py            │
│     Wrapped in: <memory_guidelines>...</memory_guidelines>          │
│     ~3.5 KB                                                         │
│     Contents: trust/verification, when to save/recall, examples     │
├─────────────────────────────────────────────────────────────────────┤
│ [5] TODO LIST INSTRUCTIONS (if TodoListMiddleware enabled)          │
│     Source: deepagents library auto-injection                       │
│     How to use write_todos / mark in_progress / etc.                │
├─────────────────────────────────────────────────────────────────────┤
│ [6] SUBAGENT TOOL DESCRIPTION (if subagents configured)             │
│     Source: deepagents library auto-injection                       │
│     How to use the `task` tool to delegate to subagents             │
├─────────────────────────────────────────────────────────────────────┤
│ [7] TOOL PROMPTS (auto-injected)                                    │
│     Source: from agent.config.tools / native_tools / custom_tools    │
│     All 9 native + 5 custom tools listed with their schemas         │
└─────────────────────────────────────────────────────────────────────┘

TOTAL: ~10-12 KB sent to the LLM (model depends on agent.config.model)
```

### Example: `demo_deep_agent` (id=84) on project 1

```python
# Final system message sent to minimax-m3:

[1] "You are a helpful AI assistant with planning, research, and task delegation capabilities.
     When facing complex multi-step tasks, use the `task` tool to delegate specialized work
     to subagents. 你可以会数学

     **Language**: Respond in Chinese."

[2] <agent_memory>
     # My First Project — Project Base Configuration
     ... (4,374 chars of project context) ...
     </agent_memory>

     <memory_guidelines>
     ... (3.5 KB of memory rules) ...
     </memory_guidelines>

[3] Todo List instructions (write_todos, etc.)

[4] `task` tool description (subagent delegation)

[5] Tool prompts:
     - Native: ls, read_file, write_file, edit_file, glob, grep, web_search, web_fetch, tavily_search
     - Custom: math_add, math_subtract, math_multiply, math_divide, math_sqrt
```

### How to verify it's working

1. Open `ModernHeader` → click "AGENTS.md" button
2. Edit content → Save
3. Next chat run with a DeepAgent in this project will see the new content
4. Or use the API: `curl http://localhost:8765/api/projects/1/agents-md`

### Settings Precedence (Important!)

The AGENTS.md content is **context for the agent**, NOT configuration. For actual runtime behavior, precedence is:

| Priority | Location | What it controls |
|---|---|---|
| 1 | `agent.config.*` (per-agent) | **THE actual config used** |
| 2 | `project.configuration.*` (per-project) | Project defaults (often dead code) |
| 3 | `settings` (global) | App-wide (api keys, embedding model, language) |
| 4 | AGENTS.md (filesystem) | **Just context** — no code reads it (except MemoryMiddleware) |

The AGENTS.md **tells the agent about the project**, but doesn't change what code runs.

### Example AGENTS.md

See [`example-AGENTS.md`](./example-AGENTS.md) for a fully populated project-level AGENTS.md.

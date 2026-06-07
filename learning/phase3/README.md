# Phase 3: Memory Systems

> How LangConfig agents actively manage long-term memory via vector store tools, and how context is assembled from multiple sources.

---

## Agent Memory System

**File**: [`backend/core/agents/memory.py`](../../backend/core/agents/memory.py)

The `AgentMemorySystem` gives agents **explicit memory control through tools** — agents decide what to remember, search their own memories, and build up project-specific knowledge over time.

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
| `memory_store` | `MemorySaveArgs` | Saves a `Document` to VectorStore with metadata (memory_id, type, importance, tags, created_at) |
| `memory_retrieve` | `MemorySearchArgs` | Semantic search via `asimilarity_search_with_relevance_scores()`, filters by `min_relevance` threshold |

### Tool Argument Schemas (Pydantic Guardrails)

- **`MemorySaveArgs`**: `memory_content` (str), `memory_type` (enum), `importance` (1-10), `tags` (list, optional)
- **`MemorySearchArgs`**: `query` (str), `memory_type` (optional filter), `min_relevance` (0.0-1.0), `limit` (1-15)

### Scoping & Multi-Tenancy

Each memory is scoped to a `(project_id, agent_id)` pair:

```python
self.base_metadata = {
    "project_id": self.project_id,
    "doc_type": "agent_memory"  # Differentiates from standard RAG docs
}
```

All VectorStore operations use `filter=self.base_metadata` to ensure strict isolation.

### How Memory Tools Are Loaded

**File**: [`backend/core/agents/factory.py`](../../backend/core/agents/factory.py#L1467-L1492)

```python
async def _load_memory_tools(vector_store, project_id, task_id):
    memory_system = AgentMemorySystem(
        vector_store=vector_store,
        project_id=project_id,
        agent_id=f"task_{task_id}"
    )
    memory_tools = memory_system.create_memory_tools()
    # Returns [memory_store, memory_retrieve] — ready for agent binding
```

The memory tools are produced as `StructuredTool` instances (via `StructuredTool.from_function()`) and mixed into the agent's tool list alongside native, custom, and template tools.

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

## Three Persistence Layers: thread_id vs agent_id vs Store

This is crucial to understand: LangConfig has **three separate persistence systems** serving different purposes, each with its own scoping key.

| # | Layer | Scoped By | What It Persists | Technology | When It's Used |
|---|-------|-----------|-----------------|------------|----------------|
| **1** | **Checkpointer** | `thread_id` | Graph state, message history across conversation turns | `PostgresSaver` (PostgreSQL) | Every `workflow.ainvoke()` call |
| **2** | **Memory Tools** | `agent_id` + `project_id` | Semantic facts, decisions, patterns the agent learns | `PGVectorStore` (pgvector) | Agent calls `memory_store()` / `memory_retrieve()` |
| **3** | **Store API** | `namespace` (cross-thread) | Long-term memory across different workflow sessions | `AsyncPostgresStore` (PostgreSQL) | Accessed via `runtime.store` in LangGraph |

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
2. **Two-pronged system** — `AgentMemorySystem` (agent-facing tools) + `ContextSynthesis`/`Compactor` (framework-managed context window)
3. **Three persistence layers** — Checkpointer (thread_id, graph state), Memory Tools (agent_id, semantic facts), Store API (namespace, cross-session memory)
4. **thread_id is for checkpointing, NOT memory** — The AgentMemorySystem uses `agent_id` + `project_id`, completely independent of LangGraph's `thread_id`
5. **Multi-tenant vector store** — Each project gets its own PGVector table with HNSW indexing
6. **Graceful degradation** — Missing VectorStore just skips memory tools (no crash), compaction has hard-truncation fallback
7. **Embedding flexibility** — Priority chain from local (Ollama) → cloud (OpenAI) → fallback (HuggingFace)
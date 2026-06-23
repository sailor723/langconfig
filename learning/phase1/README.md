# Phase 1: LLM & Agent Creation

> Core question: How does LangConfig turn a config dict into a runnable LangGraph agent?

---

> **Note: Two Agent Creation Paths**
>
> LangConfig has **two separate** agent creation pipelines:
>
> | Path | Class | File | Final Call | Used For |
> |---|---|---|---|---|
> | **LangGraph Agent** (we are here) | `AgentFactory` | [`factory.py`](../../backend/core/agents/factory.py) | `langchain.agents.create_agent()` (L675) | Simple agents, single-purpose tasks |
> | **DeepAgent** (separate path) | `DeepAgentFactory` | [`deepagent_factory.py`](../../backend/services/deepagent_factory.py) | `deepagents.create_deep_agent()` (L242) | Complex agents with subagents, middleware, guardrails |
>
> This phase focuses on the **LangGraph Agent** path only. DeepAgent is covered in Phase 5.

## Architecture Overview (LangGraph Agent Path)

```
User Config (JSON)
       |
       v
AgentConfigV2 (Pydantic model, validated)
       |
       v
AgentFactory.create_agent()  <-- the central orchestrator (L168)
       |
       +-- 0. Validate config (_validate_agent_config @ L128)
       +-- 1. Extract configuration from dict         (L251)
       +-- 1b. Dynamic model routing (opt-in)          (L332)
       +-- 2. Create LLM with fallbacks                (L377)
       |       |
       |       +-- _create_llm_with_fallbacks() @ L1032
       |               |
       |               +-- _create_llm() @ L1131
       |                       |
       |                       +-- deepseek-*  -> ChatOpenAI (OpenAI-compatible API)
       |                       +-- local-*     -> ChatOpenAI (local model config from DB)
       |                       +-- gpt-*       -> init_chat_model(provider="openai")
       |                       +-- claude-*    -> init_chat_model(provider="anthropic")
       |                       +-- gemini-*    -> init_chat_model(provider="google_genai")
       |
       +-- 3. Load tools (native, CLI, custom, memory, RAG)  (L392)
       +-- 3b. Wrap tools with execution constraints          (L444)
       +-- 4. Handle structured output                        (L463)
       +-- 5. Augment context with pattern recommendations    (L539)
       +-- 6. Construct system prompt                         (L547)
       +-- 6a. Inject skills (optional)                       (L558)
       +-- 6b. Setup middleware (v1.0) or hooks (legacy)      (L584)
       +-- 6c. Setup callbacks (LangFuse tracing)             (L615)
       +-- 7. Build create_agent_kwargs                       (L628)
       +-- 8. Call create_agent() (LangChain v1.0)            (L675)
       |
       v
CompiledStateGraph (runnable LangGraph agent)
```

---

## File-by-File Breakdown

### 1. Model Definitions
**File**: [`backend/constants/models.py`](../../backend/constants/models.py) — *intentionally empty placeholder*

> **⚠️ Phase 5 drift (commit `ade43ad`):** Models moved from a Python enum to the PostgreSQL `models` table.
> See `models/model.py` for the SQLAlchemy definition and `scripts/seed_models.py` for the seed data (23 cloud models).
> The old `ModelChoice` enum was removed; this file remains as a placeholder for legacy imports.

- `ModelChoice` enum — **REMOVED in Phase 5**
- `DEFAULT_MODEL` — now hardcoded in [`backend/core/agents/factory.py:55`](../../backend/core/agents/factory.py#L55) as `"claude-haiku-4-5-20251015"` (was `deepseek-chat` pre-Phase 5)
- Models live in PostgreSQL → queryable via [`backend/core/agents/factory.py:_create_llm()`](../../backend/core/agents/factory.py)

### 2. Agent Config Schema
**File**: [`backend/models/agent_config_schema.py`](../../backend/models/agent_config_schema.py)

- `AgentConfigV2` — the Pydantic model that defines the shape of an agent config
- **Key fields**: `model`, `temperature`, `max_tokens`, `system_prompt`, `tools` (unified `ToolConfig`), `streaming`, `enable_memory`, `enable_structured_output`, `interrupt_before/after` (HITL), `middleware`
- `ToolConfig` consolidates 4 tool arrays: `native`, `cli`, `custom`, `mcp`

### 3. Agent Factory (The Heart)
**File**: [`backend/core/agents/factory.py`](../../backend/core/agents/factory.py)

#### Step 0: Validate Config (`_validate_agent_config` @ L128)
Checks 9 things:
1. `model` is required
2. `temperature` must be 0.0–2.0
3. `max_tokens` must be 1–500000
4. Model name is in `SUPPORTED_MODELS` (warning only, doesn't fail)
5. Structured output + tools = mutually exclusive (error)
6. Tool lists must contain strings
7. Interrupt node names must be "agent" or "tools"
8. Middleware must be a list
9. Fallback models must be strings

**Key design choice**: validation errors are logged as warnings — the agent still gets created. Resilience over strictness.

#### Step 1: Extract Configuration (L251)
Pulls every field from the config dict with defaults:
- `model_name`, `temperature`, `max_tokens`, `streaming`
- `native_tool_names` — merges legacy `mcp_tools` into `native_tools`
- `fallback_models`, `enable_memory`, `long_term_memory`
- `middleware_list`, `model_hooks`
- `output_schema`, `enable_structured_output`
- `interrupt_before/after` (HITL)
- `enable_multimodal_input`

#### Step 1b: Dynamic Model Routing (L332, opt-in)
If `enable_model_routing=True`, a `ModelRouter` analyzes the task and may swap the model for cost optimization:
```python
model_name = router.route(
    original_model=model_name,
    context_length=len(context),
    tool_count=tool_count,
    strategy=routing_strategy,  # "balanced", "cost_optimized", etc.
    requirements=routing_requirements
)
```

#### Step 2: Create LLM with Fallbacks (L377)
Calls [`_create_llm_with_fallbacks()`](file:///Users/weiping/dev/Learn/langchain-ai/langconfig/backend/core/agents/factory.py#L1032) which:
1. Tries primary model
2. If fallback models provided, tries each one
3. Returns `primary_llm.with_fallbacks(fallbacks)` for chain-of-resilience
4. If primary fails but a fallback succeeds, promotes fallback to primary

The actual LLM creation is in [`_create_llm()`](file:///Users/weiping/dev/Learn/langchain-ai/langconfig/backend/core/agents/factory.py#L1131) which handles 4 model categories:

| Model prefix | What happens | API Key Source |
|---|---|---|
| `deepseek-*` | `ChatOpenAI(model, api_key=settings.DEEPSEEK_API_KEY, base_url=settings.DEEPSEEK_API_BASE)` | settings (PG > .env) |
| `local-*` | Looks up local model config from DB, then `ChatOpenAI` | LocalModel table in PG |
| `gpt-*` | `init_chat_model(model, model_provider="openai", api_key=...)` | settings.OPENAI_API_KEY |
| `claude-*` | `init_chat_model(model, model_provider="anthropic", api_key=...)` | settings.ANTHROPIC_API_KEY |
| `gemini-*` | `init_chat_model(model, model_provider="google_genai", api_key=..., convert_system_message_to_human=True)` | settings.GOOGLE_API_KEY |

#### Step 3: Load Tools (L392)
Loads tools by name/ID from 4 sources:
- **Native tools** (`file_read`, `web_search`, etc.) from `backend/tools/native_tools.py`
- **CLI tools** (git, docker)
- **Custom tools** loaded from DB by ID
- **Memory tools** (`memory_store`, `memory_retrieve`) if `enable_memory=True`
- **RAG tools** if `enable_rag=True`

#### Step 3b: Wrap Tools with Execution Constraints (L444)
Wraps tools with timeouts, retries, and exclusive execution via `execution_wrapper.py`.

#### Step 4: Handle Structured Output (L463)
If `enable_structured_output=True` and no tools are bound:
- `ProviderStrategy` — uses native model structured output (faster)
- `ToolStrategy` — wraps output as a tool call (fallback)

#### Step 5: Augment Context with Pattern Recommendations (L539)
Uses `_augment_context_with_patterns()` to enrich context with learning/pattern recommendations.

#### Step 6: Construct System Prompt (L547)
Builds: `[Guardrails] -> [Memory instructions] -> [Base prompt] -> [Task context]`

#### Step 6a: Inject Skills (L558, opt-in)
If `enable_skills=True`, matches relevant skills from the skill registry and injects them into the prompt.

#### Step 6b: Setup Middleware or Hooks (L584)
- **v1.0 middleware** preferred (if `middleware_list` or `enable_default_middleware`)
- **Legacy hooks** fallback (if `model_hooks` or `enable_default_hooks`)

#### Step 6c: Setup Callbacks (L615)
Configures LangFuse tracing, token tracking, and other observability callbacks.

#### Step 7: Build create_agent_kwargs (L628)
Section header `# 7. Create LangGraph Agent (v1.0 API)` — builds the keyword arguments dict (L631-674):
```python
create_agent_kwargs = {
    "model": llm_or_model,       # Unbound LLM or selector callable
    "tools": tools or [],        # create_agent handles binding internally
    "system_prompt": system_prompt_str,
    "response_format": structured_output_strategy,  # optional (L645)
    "middleware": middleware,                         # optional (L649)
    "interrupt_before": nodes,                        # optional HITL (L668)
    "interrupt_after": nodes,                         # optional HITL (L674)
}
```

#### Step 8: Create LangGraph Agent (L675)
The final LangChain v1.0 invocation:
```python
agent_graph = create_agent(**create_agent_kwargs)
```

Returns a `CompiledStateGraph` — the runnable LangGraph agent.

After creation, verification happens (L677-692):
- Logs tool binding success/failure
- Logs parallel vs sequential tool execution mode
- Logs registered callback types (LangFuse, etc.)

---

## Data Flow: Config -> Runnable Agent

```
Frontend (JSON)
  |  POST /api/agents/templates or /api/workflows/execute
  v
API Route (backend/api/agents/routes.py or backend/api/workflows/execution.py)
  |  Extracts agent_config from request
  v
AgentFactory.create_agent(agent_config, project_id, task_id, context)  @ L168
  |  Returns (agent_graph, tools, callbacks)
  v
Workflow Executor (backend/core/workflows/executor.py)
  |  Invokes agent_graph.ainvoke() with streaming/callbacks
  v
SSE Stream back to Frontend
```

---

## Key LangChain APIs Used

| API | Purpose |
|---|---|
| `init_chat_model()` | Create LLM from model name string (handles provider routing) |
| `create_agent()` | LangChain v1.0 unified agent creator (replaces create_react_agent) |
| `ChatOpenAI` | Direct provider wrapper (for OpenAI-compatible APIs like DeepSeek) |
| `BaseChatModel` | Abstract base for all chat models |
| `BaseTool` / `StructuredTool` | Tool interface |
| `ChatPromptTemplate` | Prompt construction |
| `CompiledStateGraph` | Runnable LangGraph agent |

---

## Key Takeaways

1. **`_create_llm()` at L1131** is where the actual model initialization happens — it's the bridge between a model string and a working LLM instance
2. **DeepSeek gets special treatment** — uses `ChatOpenAI` directly instead of `init_chat_model` because it's OpenAI-compatible
3. **`init_chat_model()` is used for standard providers** (OpenAI, Anthropic, Google) — handles provider routing automatically
4. **Resilience is baked in** — fallback models, validation warnings instead of errors, try/catch around tool wrapping
5. **Everything is configurable** — every feature (memory, RAG, HITL, middleware, skills) is opt-in via the config dict
# LangConfig Learning Plan

> A structured study plan covering LangChain, LangGraph, and DeepAgent concepts mapped to their LangConfig implementations.

---

## Phase 1: Foundation — LLM & Agent Creation

| Concept (LangChain/LangGraph) | LangConfig Implementation |
|---|---|
| `init_chat_model()` — unified model init across providers | [`backend/core/agents/factory/assembly.py`](../backend/core/agents/factory/assembly.py) — `AgentFactory.create_agent()` |
| `ChatOpenAI` / per-provider wrappers | [`backend/core/agents/factory/llm.py`](../backend/core/agents/factory/llm.py) — how it resolves model name -> provider + API key |
| `BaseChatModel` abstraction | [`backend/core/agents/factory/assembly.py`](../backend/core/agents/factory/assembly.py) — type hints and fallback logic |
| Agent configuration schema | [`backend/models/agent_config_schema.py`](../backend/models/agent_config_schema.py#L108) — `AgentConfigV2` full schema |
| Config validation (bounds, mutual exclusion) | [`backend/core/agents/factory/validation.py`](../backend/core/agents/factory/validation.py) — `_validate_agent_config()` |

**Goal**: Understand how LangConfig takes a config dict (model, temperature, tools) and produces a compiled LangGraph agent.

---

## Phase 2: Tools — Definition, Registration, Execution

| Concept (LangChain) | LangConfig Implementation |
|---|---|
| `BaseTool` / `StructuredTool` | [`backend/core/tools/factory/base.py`](../backend/core/tools/factory/base.py) — `ToolFactory` creates tools dynamically |
| Tool type taxonomy | [`backend/models/custom_tool.py`](../backend/models/custom_tool.py#L16-L30) — `ToolType`, `ToolTemplateType` enums |
| Tool templates (Slack, API, DB, etc.) | [`backend/core/tools/templates/`](../backend/core/tools/templates/) — per-category tool templates |
| Tool execution wrapper (artifacts, error handling) | [`backend/core/tools/execution_wrapper.py`](../backend/core/tools/execution_wrapper.py) |
| Native tools (file I/O, search, etc.) | [`backend/tools/native_tools.py`](../backend/tools/native_tools.py) |
| Tool seeding / registry | [`backend/core/tools/seed.py`](../backend/core/tools/seed.py) |
| Tool CRUD API | [`backend/api/tools/routes.py`](../backend/api/tools/routes.py) |

**Goal**: Understand how custom tools are defined, validated, stored, and dynamically bound to agents at runtime.

---

## Phase 3: Memory Systems

| Concept (LangChain/LangGraph) | LangConfig Implementation |
|---|---|
| `VectorStore` abstraction (long-term memory) | [`backend/core/agents/memory.py`](../backend/core/agents/memory.py#L80-L179) — `AgentMemorySystem` with `save_to_memory` / `search_memory` tools |
| Memory types (FACT, DECISION, PATTERN, etc.) | [`backend/core/agents/memory.py`](../backend/core/agents/memory.py#L40-L50) — `MemoryType` enum |
| Pydantic-validated memory tool arguments | [`backend/core/agents/memory.py`](../backend/core/agents/memory.py#L54-L78) — `MemorySaveArgs`, `MemorySearchArgs` |
| Vector store initialization (Chroma/Ollama) | [`backend/services/llama_config.py`](../backend/services/llama_config.py) |
| Memory management API (view/search/stats) | [`backend/api/memory/routes.py`](../backend/api/memory/routes.py) |
| Context synthesis (assembling context from memory) | [`backend/core/context/synthesis.py`](../backend/core/context/synthesis.py) |
| Context compaction (token management) | [`backend/core/context/compactor.py`](../backend/core/context/compactor.py) |

**Goal**: Understand how agents actively manage long-term memory via tool calls, and how context is assembled from multiple sources.

---

## Phase 4: Human-in-the-Loop (HITL)

| Concept (LangGraph) | LangConfig Implementation |
|---|---|
| `interrupt_before` / `interrupt_after` nodes | [`backend/core/agents/factory/assembly.py`](../backend/core/agents/factory/assembly.py) — interrupt node config |
| HITL approval/rejection API | [`backend/api/hitl/routes.py`](../backend/api/hitl/routes.py#L40-L80) — `POST /api/hitl/{id}/approve` |
| HITL workflow nodes | [`backend/core/workflows/nodes.py`](../backend/core/workflows/nodes.py#L40-L80) — `handle_hitl_node` |
| Checkpointing (resume after interrupt) | [`backend/core/workflows/checkpointing/`](../backend/core/workflows/checkpointing/) — `manager.py`, `cancellation.py` |
| Event bus for real-time SSE updates | [`backend/services/event_bus.py`](../backend/services/event_bus.py) |

**Goal**: Understand the full HITL flow — how an agent pauses, waits for human approval via API, and resumes execution.

---

## Phase 5: DeepAgent — Subagent Orchestration

| Concept (DeepAgent) | LangConfig Implementation |
|---|---|
| `DeepAgentConfig` (full config schema) | [`backend/models/deep_agent.py`](../backend/models/deep_agent.py#L178-L250) |
| `SubAgentConfig` — subagent delegation | [`backend/models/deep_agent.py`](../backend/models/deep_agent.py#L20-L80) — dictionary vs compiled subagents |
| Middleware system (TodoList, Filesystem, etc.) | [`backend/core/middleware/deep.py`](../backend/core/middleware/deep.py) — `TodoListMiddleware` |
| `MiddlewareConfig` / `BackendConfig` / `GuardrailsConfig` | [`backend/models/deep_agent.py`](../backend/models/deep_agent.py#L90-L170) |
| DeepAgent templates (Code Researcher, etc.) | [`backend/core/templates/deep_agent.py`](../backend/core/templates/deep_agent.py) |
| DeepAgent CRUD API | [`backend/api/agents/deep_agents.py`](../backend/api/agents/deep_agents.py) |

**Goal**: Understand how DeepAgent extends simple agents with planning, middleware, subagent delegation, and guardrails.

---

## Phase 6: Workflow Orchestration (LangGraph Graph)

| Concept (LangGraph) | LangConfig Implementation |
|---|---|
| `StateGraph` definition | [`backend/core/workflows/graph.py`](../backend/core/workflows/graph.py) — `create_workflow_graph()` |
| `WorkflowState` (state schema) | [`backend/core/workflows/state.py`](../backend/core/workflows/state.py) |
| Workflow nodes (init, execute, critique, retry, complete) | [`backend/core/workflows/nodes.py`](../backend/core/workflows/nodes.py) |
| Official LangGraph patterns (agent, supervisor, swarm) | [`backend/core/workflows/official_patterns.py`](../backend/core/workflows/official_patterns.py) |
| Supervisor / swarm patterns | [`backend/core/workflows/supervisor.py`](../backend/core/workflows/supervisor.py), [`backend/core/workflows/swarm.py`](../backend/core/workflows/swarm.py) |
| Workflow execution & runner | [`backend/core/workflows/executor/`](../backend/core/workflows/executor/), [`backend/core/workflows/runner.py`](../backend/core/workflows/runner.py) |

**Goal**: Understand how LangConfig compiles and runs full LangGraph workflows with conditional routing, retry, and HITL.

---

## Phase 7: Middleware System (LangGraph v1.0)

| Concept (LangGraph v1.0) | LangConfig Implementation |
|---|---|
| `AgentMiddleware` base class | [`backend/core/middleware/core.py`](../backend/core/middleware/core.py#L30-L60) |
| `before_model()` / `after_model()` hooks | [`backend/core/middleware/core.py`](../backend/core/middleware/core.py#L60-L120) |
| Dynamic prompts via `@dynamic_prompt` | [`backend/core/middleware/core.py`](../backend/core/middleware/core.py) |
| Middleware presets | [`backend/core/middleware/presets.py`](../backend/core/middleware/presets.py) |
| Routing middleware (agent -> subagent routing) | [`backend/core/middleware/routing.py`](../backend/core/middleware/routing.py) |

**Goal**: Understand how LangConfig's middleware system replaces legacy hooks with composable, reusable patterns.

---

## Phase 8: Code Generation & Export

| Concept | LangConfig Implementation |
|---|---|
| LangGraph workflow code generation | [`backend/core/codegen/langgraph.py`](../backend/core/codegen/langgraph.py) |
| Custom tool code generation | [`backend/core/codegen/generators/custom_tools.py`](../backend/core/codegen/generators/custom_tools.py) |
| Workflow exporter (export graphs as code) | [`backend/core/codegen/workflow_exporter.py`](../backend/core/codegen/workflow_exporter.py) |
| Streamlit app generation from workflows | [`backend/core/codegen/generators/streamlit_app.py`](../backend/core/codegen/generators/streamlit_app.py) |

**Goal**: Understand how LangConfig can generate runnable Python code from configured workflows — a key differentiator.

---

## Phase 9: UI — Agents, Workflows & Studio (UX Walkthrough)

> Companion guide to the backend phases — focuses on the **mental model** of how Agents and Workflows are exposed in the UI, where things live (Studio, Library, Agents), and how to navigate (Save → Library → right-click → Rename → Run → Results).

| Topic | LangConfig Implementation |
|---|---|
| Agent vs Workflow concept | [`learning/phase6-ui/README.md`](phase6-ui/README.md) |
| Studio (visual canvas) | [`src/features/workflows/canvas/WorkflowCanvas.tsx`](../src/features/workflows/canvas/WorkflowCanvas.tsx) |
| Library (saved workflows browser) | [`src/components/layout2/WorkflowStudioPage.tsx`](../src/components/layout2/WorkflowStudioPage.tsx) |
| Agent builder UI | [`src/components/layout2/AgentEditor.tsx`](../src/components/layout2/AgentEditor.tsx), [`src/components/layout2/DeepAgentEditor.tsx`](../src/components/layout2/DeepAgentEditor.tsx) |
| Test Agent modal (streaming chat) | [`src/features/chat/ui/ChatPage.tsx`](../src/features/chat/ui/ChatPage.tsx) |
| Modern header / navigation | [`src/components/layout/ModernHeader.tsx`](../src/components/layout/ModernHeader.tsx) |

**Goal**: Build a clear mental model of Agent vs Workflow, learn the UI lifecycle (Save → Library → Rename → Run → Results), and understand why Start/End control nodes are required.

---

## Suggested Study Order

1. **Phase 1 -> 2 -> 3** (core: LLM -> Tools -> Memory) — the building blocks of any agent
2. **Phase 4** (HITL) — adds human interaction on top of the agent loop
3. **Phase 5** (DeepAgent) — extends to multi-agent / subagent patterns
4. **Phase 6** (Workflows) — full graph orchestration
5. **Phase 7** (Middleware) — advanced composability
6. **Phase 8** (CodeGen) — export/deploy

For each phase:
1. Read the LangChain/LangGraph official docs on the concept
2. Read the LangConfig implementation file
3. Trace the full flow: API route -> service -> model -> execution
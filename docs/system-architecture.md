# LangConfig System Architecture

> Visual overview of the LangConfig platform (Agent IDE). Built with Mermaid — open this
> file in the IDE Markdown preview to render the diagrams.

---

## 1. What is LangConfig?

LangConfig is a **visual platform for building, testing, and shipping LangChain agents and
LangGraph workflows**. It works as a full **Agent IDE ("Workbench" mode)** — you design
agents on a canvas, configure tools/middleware/skills in side panels, chat with them to
verify behavior, and finally **export them as standalone Python** that runs outside the
platform (just like you develop in VS Code, then ship the app).

The product is a **dually-kept system**: a lightweight React IDE shell (Obsidian/VS Code
style: activity bar, sidebar, tabbed workspace, bottom panel) in front of a FastAPI
backend that compiles persisted agent definitions into real LangGraph executables at
runtime.

### Tech stack

| Layer        | Technology                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------ |
| Frontend     | React 19 + TypeScript + Tailwind CSS 4 + ReactFlow                                               |
| Backend      | Python 3.11/3.13 + FastAPI + LangChain V1 + LangGraph + deepagents 0.7.1                         |
| Database     | PostgreSQL 16 + pgvector + SQLAlchemy + Alembic                                                  |
| Runtime libs | deepagents SDK, langchain/langgraph, LLM providers (DeepSeek / OpenAI-compatible), Tavily search |

### The five-layer mental model

```mermaid
flowchart TB
    L1["1 · UI LAYER<br/>React IDE shell (src/)"]
    L2["2 · API LAYER<br/>FastAPI routers (backend/api/)"]
    L3["3 · SERVICE LAYER<br/>Builders, exporters, workspace (backend/services/)"]
    L4["4 · CORE ENGINES<br/>workflows, codegen, skills, middleware (backend/core/)"]
    L5["5 · DATA & RUNTIME LIBS<br/>PostgreSQL + deepagents/langchain"]

    L1 --> L2 --> L3 --> L4 --> L5
    L3 --> L5
    L4 --> L5

    classDef layer fill:#f8fafc,stroke:#64748b,color:#111;
    class L1,L2,L3,L4,L5 layer;
```

Each layer has a **strict responsibility**:

1. **UI** — renders canvas/editors, never talks to the DB; only calls the typed API clients in `src/lib/api/`.
2. **API** — FastAPI routers are thin *controllers*: validate input, delegate to services, stream SSE. They contain almost no business logic.
3. **Service** — *builders* (`AgentFactory`, `DeepAgentFactory`), *exporters* (`ExportService`), workspace/memory/scheduler managers.
4. **Core engines** — reusable engines: workflow executor, checkpointing, events, codegen, skills registry, middleware, context management.
5. **Data & runtime** — PostgreSQL tables and the external SDKs the services orchestrate.

> **The key architectural rule:** agents are *not* stored as executable code — they are stored
> as **JSON config rows** in PostgreSQL and **compiled into LangGraph graphs at runtime** by
> the service layer. This is why you can edit an agent in the UI and immediately re-run it.

---

## 2.

<u><wbr> The layer map (everything at a glance)</u>

```mermaid
%%{init: {"themeVariables": {"fontSize": "18px"}}}%%
flowchart TB
    subgraph UI["1 · FRONTEND LAYER — React 19 + TypeScript + Tailwind 4"]
        direction LR
        A1["IDE shell<br/>components/layout2/"]
        A2["Features<br/>workflows · agents · deepagent studio · chat"]
        A3["API clients<br/>lib/api/ (typed)"]
    end

    subgraph API["2 · API LAYER — FastAPI · 40 routers (main.py)"]
        direction LR
        R1["agents + deepagents<br/>CRUD · prompt-preview · export"]
        R2["chat + workflows<br/>SSE · orchestration · hitl"]
        R3["rag + doc_chat + memory<br/>knowledge · store · agents_md"]
        R4["tools + skills + workspace<br/>models · settings"]
    end

    subgraph SVC["3 · SERVICE LAYER — builders + managers"]
        direction LR
        F1["AgentFactory<br/>core/agents/factory"]
        F2["DeepAgentFactory<br/>services/deepagent_factory"]
        E1["ExportService<br/>services/export_service"]
        W1["WorkspaceManager<br/>+ 20 support services"]
    end

    subgraph CORE["4 · CORE ENGINES"]
        direction LR
        C1["workflows<br/>executor · checkpoints · events"]
        C2["codegen"]
        C3["skills + middleware"]
        C4["models + context"]
    end

    subgraph LIB["RUNTIME LIBRARIES"]
        direction LR
        L1["deepagents SDK"]
        L2["langchain V1 + langgraph"]
        L3["LLM providers"]
        L4["Tavily search"]
    end

    subgraph DB["5 · DATA LAYER"]
        D1(("PostgreSQL 16<br/>+ pgvector :5432"))
        D2["Tables:<br/>deep_agent_templates · custom_tools · skills<br/>workflows · agent_memories · execution_events"]
    end

    A3 --> R1
    A3 --> R2
    A3 --> R3
    A3 --> R4

    R1 --> F1
    R1 --> F2
    R1 --> E1
    R2 --> F1
    R2 --> F2
    R3 --> F1
    R4 --> F1

    F1 --> C1
    F1 --> C3
    F1 --> C4
    F2 --> C1
    F2 --> C3
    C1 --> L2

    F1 --> L2
    F2 --> L1
    L1 --> L2
    F1 --> L3
    F2 --> L3

    F1 --> D1
    F2 --> D1
    C1 --> D1
    D1 --> D2

    classDef ui fill:#e2e8f0,stroke:#334155,color:#0f172a,font-size:18px;
    classDef api fill:#bfdbfe,stroke:#1d4ed8,color:#1e3a8a,font-size:18px;
    classDef svc fill:#bbf7d0,stroke:#15803d,color:#14532d,font-size:18px;
    classDef core fill:#ddd6fe,stroke:#6d28d9,color:#4c1d95,font-size:18px;
    classDef lib fill:#fde68a,stroke:#b45309,color:#78350f,font-size:18px;
    classDef db fill:#fecaca,stroke:#b91c1c,color:#7f1d1d,font-size:18px;

    class A1,A2,A3 ui;
    class R1,R2,R3,R4 api;
    class F1,F2,E1,W1 svc;
    class C1,C2,C3,C4 core;
    class L1,L2,L3,L4 lib;
    class D1,D2 db;
```

---

## 3. What is `backend/api/agents/deep_agents.py`?

It is the **REST API router (controller) for DeepAgents** — registered in `main.py` as the
"DeepAgents configuration and export" router. It does **not** build agents and does **not**
export by itself; it:

| Endpoint group                                                                  | Responsibility                         | Delegates to                                                 |
| ------------------------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------ |
| `POST/GET /api/deepagents/`, `GET /api/deepagents/{id}`, `GET /templates` | DeepAgent CRUD + built-in templates    | `models.deep_agent` (DB)                                   |
| `POST /api/deepagents/prompt-preview`                                         | System-prompt assembly preview         | deepagents harness profiles (`_harness_profile_for_model`) |
| `/export`, `/code`                                                          | Export`.py` CLI / langconfig bundles | `services/export_service.py` (`ExportService`)           |

The actual builders are `core/agents/factory/` (normal agents) and
`services/deepagent_factory/` (deep agents) — `deep_agents.py` only exposes them over HTTP.

**The `use_deepagents` flag is the source of truth.** It lives in the agent's stored JSON
`config` and decides at runtime whether a row is treated as a normal agent or a DeepAgent:

- `api/agents/deep_agents.py` reads `config.get("use_deepagents", False)` to separate the two lists.
- `api/workflows/crud.py` checks the same flag (plus node type / `deepAgentId`) when a workflow
  node contains an agent, so the right factory is used during execution.

---

## 4. Frontend layer deep-dive (`src/`)

The UI is an **IDE shell** (Obsidian/VS Code style) that maximizes canvas space for visual
workflow design.

### The IDE shell — `src/components/layout2/`

| Component                                                          | Purpose                                                                             |
| ------------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| `AgentEditor` / `AgentHomePage`                                | 4-section structured editor (Overview · Prompt · Tools · JSON) for normal agents |
| `DeepAgentEditor` / `DeepAgentCreator` / `DeepAgentHomePage` | Same 4-section editor for DeepAgents, with export buttons                           |
| `WorkflowEditor` / `WorkflowStudioPage`                        | Visual workflow builder                                                             |
| `NodeSidebar`                                                    | Right-hand config panel for the selected canvas node                                |
| `SkillEditorTab` / `SkillBrowserSidebar`                       | Skill authoring + browsing                                                          |
| `ToolEditor`                                                     | Custom tool builder                                                                 |
| `ModelHomePage` / `SearchProvidersSidebar`                     | Model defaults + search-provider API keys                                           |
| `KnowledgeView` / `NotebookViewer`                             | RAG knowledge + notebooks                                                           |
| `PromptBrowserSidebar`                                           | Prompt library                                                                      |
| `editorChatToolbar` / `chatStore.ts` / `useLayout.tsx`       | In-editor chat + layout state                                                       |

### Feature modules — `src/features/`

| Module                                                                         | Purpose                                                                                                                                                                       |
| ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workflows/`                                                                 | Full ReactFlow canvas (nodes, edges, node-config, toolbar, results, execution, settings)                                                                                      |
| `agents/ui/PromptCanvas.tsx`                                                 | Visual prompt editing                                                                                                                                                         |
| `deepagent-studio-v2/`                                                       | Modern DeepAgent studio:`ModernStudioCanvas`, agent picker, capability bar, main/sub-agent nodes, tool nodes, auto-layout                                                   |
| `chat/`                                                                      | Chat UI with SSE streaming (`useChatController`, `useChatStreaming`, `streamChatEvents.ts`), sessions, files, metrics, HITL interrupts, thinking blocks, analysis panel |
| `tools/ui/`                                                                  | `CustomToolBuilder` + `ToolTemplateGallery`                                                                                                                               |
| `knowledge/`, `memory/`, `settings/ui/`, `projects/AgentsMdEditor.tsx` | Supporting views                                                                                                                                                              |

### Typed API clients — `src/lib/api/`

`agents.ts`, `chat.ts`, `workflows.ts`, `tools.ts`, `skills.ts`, `documents.ts`, `files.ts`,
`projects.ts`, `schedules.ts`, `settings.ts`, `triggers.ts`, `backgroundTasks.ts` — one thin
fetch wrapper per backend domain. **No component talks to the backend directly**; everything
goes through these clients, which keeps the API surface testable and consistent.

```mermaid
flowchart LR
    subgraph Pages["pages/"]
        P1["HomePage"] --> P2["PlaygroundPage"]
        P3["SettingsPage"] --> P4["ProjectsPage"]
        P5["AnalysisPage"] --> P6["PromptAssemblyPage"]
    end
    subgraph Shell["components/layout2/ (IDE shell)"]
        SH1["Activity Bar + Sidebar"] --> SH2["Tabbed Workspace"]
        SH2 --> SH3["NodeSidebar (config)"]
        SH2 --> SH4["Bottom Panel (chat/logs)"]
    end
    subgraph Clients["lib/api/ (typed clients)"]
        C1["agents.ts · chat.ts · workflows.ts"]
        C2["tools.ts · skills.ts · files.ts · settings.ts"]
    end
    Shell --> Clients
    Pages --> Shell
    Clients -->|"HTTP / SSE :8765"| API["FastAPI backend"]
```

---

## 5. Backend API layer — the 40 routers

`backend/main.py` registers **40 routers** on the FastAPI app. They are thin controllers:
parse the request, delegate to a service/factory, and stream the result.

| Group                | Routers (in`main.py` order)                                                                               | Purpose                                                                                                                   |
| -------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Health & debug       | `health`, `debug`                                                                                       | Liveness + dev-only diagnostics                                                                                           |
| Agents               | `agents` (templates), `agent_generator`, `action_presets`, `images`                                 | Normal-agent CRUD, AI agent generation, action presets, image storage                                                     |
| DeepAgents           | `deepagents`, `chat`                                                                                    | DeepAgent CRUD/export + DeepAgent chat testing                                                                            |
| Workflows            | `workflows`, `orchestration`, `hitl`, `checkpoints`                                                 | Workflow CRUD/execute, simplified orchestration, human-in-the-loop approvals, checkpoint restore                          |
| Chat & memory        | `memory`, `store`, `agents_md_router`, `chat_skill_review`                                          | Agent memory, long-term store, AGENTS.md (MemoryMiddleware), data-skill review                                            |
| Knowledge / RAG      | `rag`, `graphindex_chat`, `doc_chat`, `kv`, `analysis`                                            | RAG ingestion/search, graph-index chat, folder-based doc-chat, KV store, CSV→SQLite→charts                              |
| Tools & skills       | `custom_tools`, `tool_registry`, `skills`                                                             | User tools, native tool registry (single source of truth), skills system                                                  |
| Workspace & projects | `projects`, `tasks`, `workspace`, `background_tasks`                                                | Projects, task workspaces, file trees, background job queue                                                               |
| Models & settings    | `settings`, `search_providers`, `local_models`, `model_capabilities`, `model_routes`, `schemas` | Config, search-provider keys, local models, capability profiles, model invocation (Playground), structured-output schemas |
| Automation & extras  | `schedules`, `triggers`, `webhooks`, `notebooks`, `presentations`, `google_auth`                | Cron scheduling, file-watch triggers, webhook receivers, notebooks, presentation generation + OAuth                       |

```mermaid
flowchart LR
    subgraph Routers["FastAPI app (main.py)"]
        RA["agents + deepagents + chat"]
        RW["workflows + orchestration + hitl + checkpoints"]
        RK["rag + doc_chat + graphindex_chat + kv + analysis"]
        RT["custom_tools + tool_registry + skills"]
        RM["memory + store + agents_md"]
        RX["schedules + triggers + webhooks + notebooks"]
    end
    Routers --> SVC["Service / Factory layer"]
    SVC --> CORE["Core engines"]
    SVC --> DB[("PostgreSQL")]
```

---

## 6. Service layer deep-dive (`backend/services/`)

This is the brain: **builders** turn persisted config into runnable graphs; **managers**
own the filesystem, workspaces, and side effects.

### Builders (compile config → LangGraph)

| Service                                                      | Entry point                                                     | Produces                                                   |
| ------------------------------------------------------------ | --------------------------------------------------------------- | ---------------------------------------------------------- |
| `core/agents/factory/assembly.py`                          | `AgentFactory.create_agent()` (L29)                           | Normal agent via langchain V1`create_agent`              |
| `services/deepagent_factory/assembly.py`                   | `DeepAgentFactory.create_deep_agent()` (L29)                  | DeepAgent via`deepagents.create_deep_agent`              |
| `services/deepagent_factory/{preflight,shared,support}.py` | helpers                                                         | Config validation, shared wiring, SDK compatibility guards |
| `services/export_service.py`                               | `ExportService.export_standalone()` / `export_langconfig()` | Standalone`.py` repo or import/export bundle             |

### Managers & support services

| Service                                                                                                                           | Responsibility                                                                      |
| --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `workspace_manager.py`                                                                                                          | Project/task workspace directories; sandbox and filesystem backends are scoped here |
| `chat_session_manager.py`                                                                                                       | Chat session lifecycle (start/end/resume/recover)                                   |
| `conversation_context.py`, `context_window_manager.py`, `context_retrieval.py`, `context_document_indexer.py`             | Context packing, token-window management, retrieval                                 |
| `mcp_manager.py`                                                                                                                | MCP server/tool loading                                                             |
| `scheduler_service.py`, `triggers/file_watcher.py`                                                                            | Cron + file-watch triggers                                                          |
| `presentation_service.py`, `dashboard_generator.py`, `data_dashboard.py`, `data_skill_generator.py`, `csv_to_sqlite.py` | Data analysis → presentations/dashboards                                           |
| `notebook_kernel_manager.py`                                                                                                    | Python kernel for notebooks                                                         |
| `event_bus.py`, `audit_service.py`, `deepagents_instrumentation.py`                                                         | Observability, audit logs, Langfuse callbacks                                       |
| `local_model_service.py`, `llama_config.py`                                                                                   | Local model config                                                                  |
| `oauth_service.py`, `encryption.py`                                                                                           | Google OAuth + secret encryption                                                    |
| `diff_service.py`, `file_storage.py`, `image_storage.py`, `storage_estimator.py`                                          | Diff/versioning + storage                                                           |
| `agents_md_service.py`                                                                                                          | Project`AGENTS.md` for MemoryMiddleware                                           |
| `token_counter.py`, `output_formatter.py`                                                                                     | Token counting, response formatting                                                 |
| `agent_generator_service.py`, `agent_utils.py`                                                                                | AI agent generation, model resolution (`resolve_model`)                           |
| `workflow_config_service.py`                                                                                                    | Workflow config helpers                                                             |

---

## 7. Core engines deep-dive (`backend/core/`)

Reusable engines that both agent types and workflows share.

### `core/agents/`

- `factory/` — `assembly.py` (the `AgentFactory.create_agent` builder), `llm.py` (LLM wiring + subagent construction), `prompting.py`, `validation.py`, `shared.py`
- `specialized/` — `json_agent.py`, `pandas_agent.py`, `sql_agent.py` (typed specialist agents)
- `delegation.py`, `memory.py`, `model_profiles.py`, `multimodal.py`, `templates.py`, `templates_specialized.py`, `tool_loader.py` (`ToolLoader.load_native`)

### `core/workflows/` — the execution engine (see §9)

`executor/builder.py` · `executor/execution.py` · `executor/nodes.py` · `executor/shared.py` ·
`checkpointing/manager.py` (Postgres checkpointer) · `events/emitter/` (progress, callbacks) ·
`graph.py`, `graph_state.py`, `nodes.py`, `runner.py`, `state.py` ·
`supervisor.py`, `swarm.py`, `official_patterns.py` (reusable graph topologies)

### `core/codegen/`

`langgraph.py`, `workflow_exporter.py`, and `generators/` — `api_server.py`, `custom_tools.py`,
`nodes.py`, `nodes_configurable.py`, `routing.py`, `streamlit_app.py`, `streamlit_configurable.py`,
`templates.py`, `tools.py` — turns workflows into runnable code artifacts (Streamlit apps, API servers).

### `core/context/` — `compactor.py`, `content_blocks.py`, `runtime.py`, `synthesis.py`

### `core/middleware/` — `core.py`, `advanced.py`, `deep.py`, `dynamic_tools.py`, `presets.py`,

`question_detection.py`, `routing.py`, `tool_selection.py`

### `core/skills/` — `registry.py`, `sync.py`, `matcher.py`, `loader.py`

### `core/tools/` — `factory/` (base, builders, models), `adapters/llamaindex.py`,

`templates/` (api/cms/data/database/image/notification/python/social/video), `bigtool_registry.py`,
`execution_wrapper.py`, `seed.py`

### `core/models/` — `registry.py`, `router.py`, `selector.py`, `hooks.py` (model routing/capabilities)

---

## 8. Agent build pipeline (runtime)

Both agent types are compiled on every chat/execution from their stored JSON config.

### Normal agent path

`AgentFactory.create_agent()` (`core/agents/factory/assembly.py:29`) → langchain V1
`create_agent` (the same API the exported code uses). Subagents are built recursively with
`create_agent` in `core/agents/factory/llm.py:281`.

### DeepAgent path

`DeepAgentFactory.create_deep_agent()` (`services/deepagent_factory/assembly.py:29`) does, in order:

1. **Import guard** — if `deepagents` isn't installed, fall back to a regular agent (`_fallback_to_regular_agent`).
2. **Config validation** — warnings, not hard failures.
3. **Observability** — Langfuse callbacks (`_setup_callbacks`).
4. **Load base tools** — native + custom + MCP + vector store (`_load_base_tools`).
5. **Middleware tools** — from configured middleware types (`DeepAgentsMiddlewareFactory.create_all_tools`).
6. **Subagents** — compiled separately with workspace context for file-writing tools.
7. **Middleware instances** — MemoryMiddleware (AGENTS.md via FilesystemBackend), FilesystemMiddleware (scoped to task workspace), SummarizationMiddleware (token trigger), SubAgentMiddleware (adds the `task` tool).
8. **Checkpointer** — PostgreSQL conversation persistence (`get_checkpointer()`).
9. **Skills staging** — equip configured skills by copying them into `<workspace>/skills/` and pointing `SkillsMiddleware` at them with a `FilesystemBackend`.
10. **Sandbox** — optional `LocalShellBackend` for an `execute` shell tool.
11. **`deepagents.create_deep_agent(...)`** → compiled `LangGraph CompiledStateGraph` ready to stream.

### The full pipeline

```mermaid
flowchart LR
    P1["API call:<br/>POST /api/deepagents/{id}/chat<br/>or workflow node"] --> P2["DeepAgentFactory.create_deep_agent()"]
    P2 --> P3["Load tools<br/>native + custom + MCP<br/>(tool dedup when disk backend set)"]
    P3 --> P4["Stage skills into<br/><workspace>/skills/<br/>+ FilesystemBackend"]
    P4 --> P5["deepagents.create_deep_agent<br/>(skills, middleware, subagents)"]
    P5 --> P6["CompiledStateGraph<br/>(Postgres checkpointer)"]
    P6 --> P7["SSE stream:<br/>tool calls + final answer"]
    P7 --> P8["Conversation persisted<br/>in PostgreSQL"]

    style P5 fill:#fef3c7,stroke:#d97706,color:#111
    style P6 fill:#fee2e2,stroke:#dc2626,color:#111
```

*Normal agents follow the same path via `AgentFactory.create_agent()` → langchain V1 `create_agent`
(no skills/sandbox steps).*

### Tool deduplication note

The deepagents library always injects its own **FilesystemMiddleware** (required middleware)
with `ls / read_file / write_file / edit_file / glob / grep` tools scoped to the backend root.
When a **disk backend** (skills/sandbox/Filesystem) is active, the assembly drops our native
filesystem tools so the agent exposes one set of file tools — the backend-scoped ones win.

---

## 9. Workflow execution engine (`core/workflows/`)

Workflows are **visual graphs** (ReactFlow on the frontend) persisted as JSON nodes/edges,
then executed by this engine.

```mermaid
flowchart TB
    subgraph HTTP["API (api/workflows/)"]
        H1["POST /api/workflows/{id}/execute"]
        H2["POST /api/workflows/execute<br/>(execution.py)"]
        H3["GET /api/workflows/{id}/stream<br/>(SSE)"]
        H4["GET /api/workflows/{id}/events<br/>GET /tasks/{id}/events"]
    end

    subgraph ENGINE["core/workflows/"]
        E1["graph.py · graph_state.py<br/>Build StateGraph from stored nodes"]
        E2["executor/execution.py<br/>Run + persist execution state"]
        E3["checkpointing/manager.py<br/>PostgresSaver checkpoints"]
        E4["events/emitter/<br/>progress + callback events"]
        E5["supervisor.py · swarm.py<br/>Multi-agent topologies"]
        E6["runner.py · nodes.py<br/>Node dispatch (agent / tool / deepagent / llm)"]
    end

    H1 --> E1
    H2 --> E2
    E1 --> E6
    E6 --> E4
    E2 --> E3
    E3 --> DB[("PostgreSQL<br/>executions · events")]
    E4 --> H3
    E4 --> H4

    style E2 fill:#dcfce7,stroke:#16a34a,color:#111
    style E3 fill:#fee2e2,stroke:#dc2626,color:#111
```

Key mechanics:

- **Node dispatch** — each workflow node can be an LLM call, a tool, a normal agent, a
  DeepAgent node (resolved by the `use_deepagents` flag, `crud.py:285-334`), or a
  supervisor/swarm pattern.
- **Checkpointing** — every execution step is checkpointed to Postgres, so executions can be
  paused, resumed, and restored (`api/workflows/checkpoints.py`).
- **Event streaming** — the emitter pushes progress + callback events over SSE; the UI
  subscribes via `useWorkflowStream` to update the canvas live.
- **Orchestration & HITL** — `orchestration` routes drive multi-step runs; `hitl` routes
  provide human-approval interrupts mid-run.

---

## 10. Skills & middleware pipeline

**Skills** give agents modular, context-aware capabilities. The pipeline is
**progressive disclosure**: the agent is given a *catalog* (name + description + path) and
reads each `SKILL.md` body on demand with its `read_file` tool — so the context window stays
small until a skill is actually needed.

```mermaid
flowchart LR
    S1["skills router (api/skills)<br/>CRUD + preflight"] --> S2["core/skills/registry.py<br/>+ matcher.py + sync.py"]
    S2 --> S3["Staging:<br/>copy equipped skills to<br/><workspace>/skills/"]
    S3 --> S4["SkillsMiddleware<br/>(deepagents, catalog in prompt)"]
    S4 --> S5["Agent reads SKILL.md on demand<br/>via read_file (FilesystemBackend)"]
```

**Middleware stack inside a DeepAgent** (in assembly order):

| Middleware              | Source                        | Effect                                                                                                      |
| ----------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------- |
| MemoryMiddleware        | deepagents SDK                | Loads project`AGENTS.md` into the system prompt (cache-controlled for Anthropic)                          |
| FilesystemMiddleware    | deepagents SDK                | File read/write scoped to the task workspace                                                                |
| SummarizationMiddleware | deepagents SDK                | Auto-compresses history past a token threshold (langchain ≥1.3.14 renamed kind`"token"` → `"tokens"`) |
| SubAgentMiddleware      | added by assembly             | Provides the`task` tool so the main agent can delegate to subagents                                       |
| Custom middleware       | `core/middleware/deep.py`   | Self-contained TodoListMiddleware + others (guarded imports keep SDK compat)                                |
| Sandbox                 | optional`LocalShellBackend` | `execute` tool for shell/python in the workspace                                                          |

---

## 11. Export subsystem (ship it)

The "develop in the IDE, run anywhere" story. `ExportService` (`services/export_service.py`)
produces two artifact kinds:

### `ExportService.export_standalone()` — a runnable repository

Generates a **zip containing a complete standalone agent project**:

```
deepagent_export/
├── README.md               # what it is + how to run
├── requirements.txt        # pinned deps
├── .env.example            # API keys
├── agent_config.json       # the JSON config snapshot
├── main.py                 # CLI chat interface: python main.py "query"
├── api_server.py           # optional FastAPI server
├── agent/
│   ├── agent.py            # DeepAgent initialization (create_deep_agent / create_agent)
│   ├── prompts/system_prompt.txt
│   └── tools/custom_tools.py
├── tests/test_agent.py
├── Dockerfile / docker-compose.yml   # optional
└── ui/ (index.html, chat.js, styles.css)  # optional chat UI
```

### `ExportService.export_langconfig()` — an interchange bundle

Exports a **langconfig bundle** (JSON + assets) that can be re-imported into another
LangConfig instance — the "package for re-use" format.

### The export path

```mermaid
flowchart LR
    U1["DeepAgentStudio → Export .py"] --> U2["POST /api/deepagents/{id}/export<br/>(or /code)"]
    U2 --> U3["ExportService.export_standalone()"]
    U3 --> U4["Generate standalone project<br/>(langchain create_agent + PostgresSaver)"]
    U4 --> U5["Download zip / backend/outputs/exports/*.py"]
    U5 --> U6["Run by CLI:<br/>uv run python demo2.py \"query\""]

    style U3 fill:#dcfce7,stroke:#16a34a,color:#111
```

The generated `main.py` uses the **same** langchain V1 `create_agent` API as the live
backend runtime — so what you export behaves identically to what you tested in the IDE.

---

## 12. Data layer — PostgreSQL tables

SQLAlchemy models in `backend/models/` map to these tables:

| Model (file)                                                              | Table purpose                                                                                                            |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `deep_agent.py` (`DeepAgentTemplate` / `DeepAgentConfig`)           | **`deep_agent_templates`** — both normal agents *and* deep agents, distinguished by `config.use_deepagents` |
| `custom_tool.py`                                                        | **`custom_tools`** — user tools + built-in seeds (`is_builtin=True`)                                          |
| `skill.py`                                                              | **`skills`** — skill catalog                                                                                    |
| `workflow.py`, `workflow_schedule.py`, `workflow_trigger.py`        | Workflows + cron schedules + event triggers                                                                              |
| `agent_memory.py`                                                       | Long-term agent memories (pgvector)                                                                                      |
| `conversation_archive.py`                                               | Chat session archives                                                                                                    |
| `execution_event.py`                                                    | Streamed execution events                                                                                                |
| `background_task.py`                                                    | Background job queue                                                                                                     |
| `workspace_file.py`, `file_version.py`                                | Workspace files + version history                                                                                        |
| `local_model.py`, `model.py`, `search_provider.py`, `settings.py` | Model/local-model/search-provider/settings config                                                                        |
| `user_profile.py`                                                       | User profile                                                                                                             |
| `audit_log.py`                                                          | Audit trail                                                                                                              |
| `oauth_token.py`, `presentation_job.py`                               | OAuth tokens + presentation jobs                                                                                         |
| `analysis_chat.py`, `custom_schema.py`                                | Analysis chats + structured-output schemas                                                                               |

```mermaid
flowchart TB
    subgraph PG["PostgreSQL 16 + pgvector (:5432)"]
        T1["deep_agent_templates<br/>(normal + deep agents, use_deepagents flag)"]
        T2["custom_tools · skills"]
        T3["workflows + schedules + triggers"]
        T4["agent_memories (pgvector) · conversation_archives"]
        T5["execution_events · background_tasks · audit_logs"]
        T6["workspace_files · file_versions · local_models · settings"]
    end
    T1 --> T2
    T1 --> T3
    T1 --> T4
    T3 --> T5
    T4 --> T5
```

---

## 13. Request lifecycle — sequence diagrams

### DeepAgent chat (SSE)

```mermaid
sequenceDiagram
    participant UI as React ChatPage
    participant API as api/chat/messages.py<br/>POST /api/chat/message/stream
    participant F as DeepAgentFactory
    participant DA as deepagents SDK
    participant LG as LangGraph graph
    participant DB as PostgreSQL

    UI->>API: POST /message/stream (agent_id, message)
    API->>F: create_deep_agent(config, project_id, task_id)
    F->>DA: create_deep_agent(...) with middleware/skills
    DA->>LG: compiled CompiledStateGraph
    API->>LG: astream_events(input)
    loop tool calls / tokens
        LG-->>API: agent events (tool_call, tool_result, tokens)
        API-->>UI: SSE chunk
    end
    LG-->>DB: checkpoint save (state + messages)
    LG-->>API: final answer
    API-->>UI: SSE [done]
```

### Workflow execution

```mermaid
sequenceDiagram
    participant UI as Workflow Canvas
    participant API as api/workflows/execution.py
    participant ENG as core/workflows/executor
    participant CP as checkpointing/manager
    participant DB as PostgreSQL

    UI->>API: POST /workflows/{id}/execute
    API->>ENG: build graph from stored nodes + edges
    ENG->>ENG: dispatch nodes (agent / deepagent / tool / llm)
    ENG->>CP: save checkpoint per step
    CP->>DB: upsert execution state
    ENG-->>API: progress events
    API-->>UI: SSE /workflows/{id}/events
    UI->>API: GET /workflows/{id}/stream (poll/stream results)
```

---

## 14. Development topology

Two long-running processes + one database, all driven by the root `.env` (FastAPI loads it via
`backend/config.py`, so ports and API keys are consistent everywhere).

```mermaid
flowchart LR
    subgraph FRONT["Vite dev server (:1420)"]
        F["React 19 app<br/>npm run dev"]
    end
    subgraph BACK["uvicorn (:8765, reload)"]
        B["FastAPI app<br/>uv run python main.py"]
    end
    subgraph DATA["PostgreSQL 16 (:5432)"]
        P[("pgvector + Alembic migrations")]
    end
    F -->|"HTTP / SSE<br/>localhost:8765"| B
    B -->|"SQLAlchemy<br/>DATABASE_URL (root .env)"| P

    style B fill:#dcfce7,stroke:#16a34a,color:#111
    style P fill:#fee2e2,stroke:#dc2626,color:#111
```

**Gotcha:** a second, stale Postgres container (`langconfig-postgres`) exists on `:5433`.
The app and seeders always load the root `.env` (→ `:5432`, fully migrated). Standalone
scripts must `load_dotenv("../../.env")` *before* importing `db.database`, or they hit the
stale instance and report phantom `UndefinedColumn` errors.

---

## 15. Storage strategy: DB as the permanent store (enterprise-ready)

### The vision

The filesystem is the *personal / local-dev* default. For **enterprise**, the durable home
for all artifacts — skills, workspace files, uploaded documents, outputs, versions — is the
**database**, with **object storage** (S3 / MinIO / Tencent COS / Aliyun OSS / R2) for large
blobs. The filesystem stays only for what is genuinely **ephemeral**: task scratch,
staging dirs, export zips, local sandboxes.

**Rule: DB holds durable artifacts; the filesystem holds transient working files.**

### A single seam: `StorageBackend`

Every writer in the platform talks to one object-addressed interface, so the physical
backend changes per deployment (`local` / `db` / `s3`) without touching any caller.

```mermaid
flowchart LR
    subgraph Callers["Writers"]
        W1["FileStorage<br/>uploaded RAG docs"]
        W2["WorkspaceManager<br/>agent outputs"]
        W3["Skills<br/>SKILL.md content"]
    end
    W1 --> IF["StorageBackend<br/>save(key, content) · read(key)<br/>exists · delete · list · stat"]
    W2 --> IF
    W3 --> IF
    IF --> L1["LocalStorageBackend<br/>disk (personal default)"]
    IF --> L2["DbStorageBackend<br/>Postgres BYTEA · small payloads"]
    IF --> L3["ObjectStorageBackend<br/>S3 / COS / OSS · large blobs"]
    L1 --> T1["STORAGE_MODE=local"]
    L2 --> T2["STORAGE_MODE=db"]
    L3 --> T3["STORAGE_MODE=s3"]
```

### What already exists (foundation)

| Asset | DB foundation today | Gap closed by this design |
|---|---|---|
| Workspace files | `workspace_files` (metadata, tags, agent/workflow/task context) + `file_versions` | content is on disk; only paths in DB → `storage_objects` BYTEA rows / object store |
| Skills | `skills` table already holds the SKILL.md body in `instructions` | the `backend/skills/**/SKILL.md` git mirror becomes optional |
| Uploaded docs | `FileStorage` service | hardwired to `./data/documents/` → route through the backend |
| Agent file tools | deepagents `BackendProtocol` is pluggable (`ls/read/write/glob/grep/download_files`) | a `DbBackend` maps `/skills/<name>/SKILL.md` → DB rows |
| Runtime flag | `config.py` pydantic settings (root `.env`) | new `STORAGE_MODE` env key (`local` \| `db` \| `s3`) |

### Why this composes with deepagents

`SkillsMiddleware` only calls `backend.ls()` + `backend.download_files()` on the
`BackendProtocol` — it never touches the disk itself. So a DB-backed implementation of that
protocol gives **skills 100% in DB** while preserving progressive disclosure (metadata
catalog in the system prompt, SKILL.md body read on demand) and the agent's `read_file`
tool works transparently against the DB.

### Rollout phases

1. **Phase 1 — abstraction** — `storage_objects` table + `services/storage/` (`base` / `local` / `db` backends + factory), default `local`
2. **Phase 2 — wiring** — `FileStorage`, `WorkspaceManager`, skill sync through the interface
3. **Phase 3 — deepagents `DbBackend`** — skills + workspace virtual paths served from DB
4. **Phase 4 — migration tool** — one-shot job to move existing FS artifacts into DB on flip

---

## Quick reference — where things live

| Question                      | Answer                                                                                      |
| ----------------------------- | ------------------------------------------------------------------------------------------- |
| What builds a normal agent?   | `core/agents/factory/assembly.py` → `AgentFactory.create_agent`                        |
| What builds a DeepAgent?      | `services/deepagent_factory/assembly.py` → `DeepAgentFactory.create_deep_agent`        |
| What is`deep_agents.py`?    | The REST controller (CRUD + prompt-preview + export) — not the builder                     |
| Where is export code?         | `services/export_service.py` (`ExportService`)                                          |
| Where do agents persist?      | `deep_agent_templates` table (flag `config.use_deepagents`)                             |
| How does chat stream?         | `POST /api/chat/message/stream` → SSE via `useChatStreaming` / `streamChatEvents.ts` |
| How do workflows run?         | `core/workflows/` executor + Postgres checkpointer, streamed over SSE                     |
| Where do exported files land? | `backend/outputs/exports/*.py` (or download zip from `/export`)                         |
| Where do artifacts persist?   | `services/storage/` `StorageBackend` seam — `local` (disk) \| `db` (Postgres BYTEA) \| `s3` (object store) |

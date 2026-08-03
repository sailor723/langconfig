# LangConfig System Architecture

> Visual overview of the LangConfig platform (Agent IDE). Built with Mermaid — open this
> file in the IDE Markdown preview to render the diagram.

## What is `backend/api/agents/deep_agents.py`?

It is the **REST API router (controller) for DeepAgents** — registered in `main.py` as the
"DeepAgents configuration and export" router. It does **not** build agents and does **not**
export by itself; it:

| Endpoint group | Responsibility | Delegates to |
|---|---|---|
| `POST/GET /api/deepagents/`, `GET /api/deepagents/{id}`, `GET /templates` | DeepAgent CRUD + built-in templates | `models.deep_agent` (DB) |
| `POST /api/deepagents/prompt-preview` | System-prompt assembly preview | deepagents harness profiles |
| `/export`, `/code` | Export `.py` CLI / langconfig bundles | `services/export_service.py` (`ExportService`) |

The actual builders are `core/agents/factory/` (normal agents) and
`services/deepagent_factory/` (deep agents) — `deep_agents.py` only exposes them over HTTP.

```mermaid
flowchart TB
    subgraph UI["Frontend (React 19 + TS + Tailwind 4)"]
        A1["Agent Builder (agents/)"]
        A2["DeepAgent Studio (deepagent-studio-v2/)"]
        A3["Workflow Canvas (workflows/, ReactFlow)"]
        A4["Chat (chat/, SSE streaming)"]
        A5["Knowledge / Memory / Tools / Settings"]
        A6["API client (lib/api/)"]
    end

    subgraph API["Backend API Layer (FastAPI, main.py)"]
        R1["api/agents/deep_agents.py<br/>DeepAgent CRUD + prompt-preview + export/codegen"]
        R2["api/agents/routes.py<br/>Normal Agent CRUD"]
        R3["api/agents/generator.py<br/>Agent codegen"]
        R4["api/chat + api/workflows<br/>Chat / Workflow execution (SSE)"]
        R5["api/knowledge, api/agents/chat<br/>Doc-chat, agent chat"]
    end

    subgraph SVC["Backend Service Layer"]
        F1["core/agents/factory/<br/>AgentFactory (normal)"]
        F2["services/deepagent_factory/<br/>DeepAgentFactory (deep)"]
        E1["services/export_service.py<br/>ExportService (.py / langconfig)"]
        W1["services/workspace_manager.py<br/>Task workspaces"]
        T1["core/agents/tool_loader.py<br/>tools/native_tools.py, tools/registry.py"]
        S1["core/skills/ (registry, sync, matcher)<br/>core/middleware/deep.py"]
    end

    subgraph LIB["Agent Runtime Libraries"]
        L1["deepagents (create_deep_agent,<br/>SkillsMiddleware, harness profiles)"]
        L2["langchain V1 create_agent<br/>+ langgraph (graph, checkpoints)"]
        L3["LLM providers<br/>(DeepSeek / OpenAI-compatible)"]
        L4["Tavily web search"]
    end

    subgraph DB["Data Layer"]
        D1[("PostgreSQL 16 + pgvector")]
        D2[("deep_agent_templates<br/>custom_tools, skills, workflows")]
    end

    A1 --> A6
    A2 --> A6
    A3 --> A6
    A4 --> A6
    A5 --> A6
    A6 -->|"HTTP / SSE :8765"| R1
    A6 --> R2
    A6 --> R3
    A6 --> R4
    A6 --> R5

    R1 --> F1
    R1 --> F2
    R1 --> E1
    R2 --> F1
    R3 --> F1
    R4 --> F1
    R4 --> F2
    R5 --> F1
    R5 --> F2

    F2 --> T1
    F2 --> S1
    F2 --> W1
    F1 --> T1
    F1 --> S1
    E1 --> L2

    F1 --> L2
    F2 --> L1
    L1 --> L2
    F1 --> L3
    F2 --> L3
    T1 --> L4

    F1 --> D1
    F2 --> D1
    R1 --> D2
    R2 --> D2

    classDef api fill:#dbeafe,stroke:#2563eb,color:#111;
    classDef svc fill:#dcfce7,stroke:#16a34a,color:#111;
    classDef lib fill:#fef3c7,stroke:#d97706,color:#111;
    classDef db fill:#fee2e2,stroke:#dc2626,color:#111;
    class R1,R2,R3,R4,R5 api;
    class F1,F2,E1,W1,T1,S1 svc;
    class L1,L2,L3,L4 lib;
    class D1,D2 db;
```

## Runtime build path

```mermaid
flowchart LR
    P1["API call:<br/>POST /api/deepagents/{id}/chat"] --> P2["DeepAgentFactory.create_deep_agent()"]
    P2 --> P3["Load tools (native/custom/middleware)"]
    P3 --> P4["Stage skills into workspace<br/>+ FilesystemBackend"]
    P4 --> P5["deepagents.create_deep_agent<br/>(skills, middleware, subagents)"]
    P5 --> P6["LangGraph CompiledStateGraph"]
    P6 --> P7["SSE stream: tool calls + final answer"]
    P7 --> P8["Checkpointed in PostgreSQL"]
```

*Normal agents follow the same path via `AgentFactory.create_agent()` → langchain V1 `create_agent`.*

## Export path

```mermaid
flowchart LR
    U1["DeepAgentStudio → Export .py"] --> U2["POST /api/deepagents/{id}/export<br/>(or /code)"]
    U2 --> U3["ExportService.export_standalone()"]
    U3 --> U4["Generate standalone Python<br/>(langchain create_agent + PostgresSaver)"]
    U4 --> U5["Download / backend/outputs/exports/*.py"]
    U5 --> U6["Run by CLI:<br/>python demo2.py \"query\""]
```

# Phase 2: Tools — Definition, Registration, Execution

> Core question: How does LangConfig define, register, store, and dynamically bind tools to agents?

---

## Architecture Overview

```
Tool Templates (pre-built)          Custom Tools (user-defined)     Native Tools (built-in)
      |                                      |                            |
      v                                      v                            v
backend/core/tools/templates.py    backend/models/custom_tool.py   backend/tools/native_tools.py
      |                                      |                            |
      +-- ToolFactory.create_tool()  <------------------------------------+
                      |
                      v
            Tool Registry (DB: custom_tools table)
                      |
                      v
            AgentFactory._load_*_tools()   @ factory.py
                      |
                      v
            Tool Constraint Wrapper  @ tools/execution_wrapper.py
                      |
                      v
            Bound to Agent (by create_agent() internally)
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

### 2. Tool Types & Enums
**File**: [`backend/models/custom_tool.py`](../../backend/models/custom_tool.py)

- `ToolType` enum — `API`, `DATABASE`, `CODE_EXECUTION`, `FILE_SYSTEM`, `COMMUNICATION`, `CUSTOM`
- `ToolTemplateType` enum — types for pre-built templates: `slack`, `github`, `jira`, `notion`, `postgres`
- `CustomToolCreate/Update/Response` — Pydantic schemas for CRUD operations

### 2. Tool Templates (Pre-built Integrations)
**File**: [`backend/core/tools/templates.py`](../../backend/core/tools/templates.py)

Defines ready-to-use tool templates. Each template has:
- `name`, `description`, `template_type`
- `config_schema` — JSON Schema for user-provided config
- `create_func` — function that takes config + returns `BaseTool`

Templates available: Slack, GitHub, Jira, Notion, PostgreSQL

### 3. Tool Factory
**File**: [`backend/core/tools/factory.py`](../../backend/core/tools/factory.py)

- `ToolFactory.create_tool()` — takes a template type + config → returns a `BaseTool`
- Handles validation of config against template schema
- Wraps errors with descriptive messages

### 4. Tool Seed / Registry Population
**File**: [`backend/core/tools/seed.py`](../../backend/core/tools/seed.py)

- Seeds the database with initial native tools on first run
- Ensures tool definitions exist before any agent tries to load them

### 5. Tool CRUD API
**File**: [`backend/api/tools/routes.py`](../../backend/api/tools/routes.py)

- `GET /api/tools` — list all tools (native + custom + templates)
- `POST /api/tools` — create a new custom tool
- `PUT /api/tools/{id}` — update a custom tool
- `DELETE /api/tools/{id}` — delete a custom tool

### 6. Tool Loading in Agent Factory
**File**: [`backend/core/agents/factory.py`](../../backend/core/agents/factory.py)

Four loading methods called during `create_agent()` Step 3 (L392):

| Method | Line | Source |
|---|---|---|
| `_load_native_tools()` | L1234 | `native_tools.py` — built-in tools by name |
| `_load_cli_tools()` | L1344 | CLI command definitions (git, docker) |
| `_load_custom_tools()` | L1376 | DB lookups by tool ID |
| `_load_memory_tools()` | L1467 | Vector store + memory tools |
| `_load_rag_tools()` | L1490 | RAG/codebase search tools |

### 7. Execution Constraint Wrapper
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

---

## Suggested Study Order

1. Read [`native_tools.py`](../../backend/tools/native_tools.py) — understand the built-in tools
2. Read [`custom_tool.py`](../../backend/models/custom_tool.py) — understand the tool schema
3. Read [`templates.py`](../../backend/core/tools/templates.py) — understand pre-built integrations
4. Read [`factory.py`](../../backend/core/agents/factory.py#L1234-L1500) — understand tool loading methods
5. Read [`execution_wrapper.py`](../../backend/core/tools/execution_wrapper.py) — understand constraint wrapping
6. Read [`routes.py`](../../backend/api/tools/routes.py) — understand the CRUD API
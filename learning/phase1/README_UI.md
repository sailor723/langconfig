# Phase 1: Model Configuration — UI to Backend Flow

> How a user configures an agent's model, temperature, and settings in the frontend, and how those settings flow through the API to create a compiled LangGraph agent.

---

## End-to-End Flow

```
User fills DeepAgentBuilder form
  │
  ├─ Model selector (ModelSelectorInline)
  ├─ Temperature slider (0.0–2.0)
  ├─ Max tokens input
  ├─ System prompt textarea
  ├─ Tool checkboxes (native, custom)
  └─ Additional settings (HITL, memory, etc.)
        │
        ▼
Form state = AgentConfig object (in React useState)
  │
  ├─ Stored in DeepAgentBuilder as `config` state variable
  └─ Merged from DEFAULT_CONFIG + initialConfig
        │
        ▼
User clicks "Save Agent" → handleSaveNewAgent(config)
  │
  ├─ Sends POST /api/deepagents with { name, description, category, config }
  └─ apiClient.createDeepAgent(requestData)
        │
        ▼
Backend receives config → DeepAgentFactory.create_deep_agent()
  │
  ├─ Validates config (Pydantic DeepAgentConfig)
  ├─ Resolves model provider + API key
  ├─ Loads tools (native + CLI + custom)
  ├─ Wraps with middleware + guardrails
  └─ Calls deepagents.create_deep_agent() → CompiledStateGraph
        │
        ▼
Agent ready for workflow.ainvoke()
```

---

## 1. Frontend: DeepAgentBuilder

**File**: [`src/features/agents/ui/DeepAgentBuilder.tsx`](../../../src/features/agents/ui/DeepAgentBuilder.tsx)

### Config State Structure

The form stores all agent settings in a single `config` object:

```typescript
export interface AgentConfig {
  // Required fields
  name: string;                    // Agent name
  description: string;             // Brief description (used for AI Generate)
  category: string;                // Code Generation, Research, Testing, etc.

  // Model settings
  model: string;                   // Model ID (e.g. "claude-sonnet-4-5", "gpt-4o")
  temperature: number;             // 0.0–2.0
  max_tokens?: number;             // Optional token limit

  // Prompt
  system_prompt: string;           // System instructions

  // Tools
  tools: string[];                 // Generic tool names
  native_tools: string[];          // MCP/native tool IDs (ls, grep, web_search, etc.)
  cli_tools: string[];             // CLI tool categories
  custom_tools?: string[];         // User-created custom tools from DB

  // Execution (Regular Agent only)
  max_iterations?: number;         // Max steps before stopping
  early_stopping_method?: 'force' | 'generate';
  handle_parsing_errors?: boolean;
  verbose?: boolean;
  return_intermediate_steps?: boolean;

  // Memory
  enable_memory?: boolean;         // Short-term conversation memory
  enable_rag?: boolean;            // RAG (long-term memory)

  // DeepAgent
  use_deepagents?: boolean;
  middleware?: any[];              // TodoList, Filesystem, SubAgent
  subagents?: any[];               // Dictionary or Compiled subagents
  backend?: any;                   // State, Store, Filesystem, VectorDB, Composite
  guardrails?: any;                // Token limits, interrupts, eviction

  // Safety
  enforce_tool_constraints?: boolean;  // Action Preset safety controls
  requires_human_approval?: boolean;   // HITL
  timeout_seconds?: number;
  max_retries?: number;
}
```

### Settings Hierarchy

| Section | UI Element | Config Key | Source of Options |
|---|---|---|---|
| **Basic Settings** | Text inputs (name, description) | `name`, `description` | User typed |
| **Category** | Dropdown | `category` | Fixed: Code Generation, Research, Testing, Documentation, Custom |
| **Model** | `<ModelSelectorInline>` dropdown | `model` | `useAvailableModels` hook → API |
| **Temperature** | Range slider (0–2, step 0.1) | `temperature` | User selected |
| **Max Tokens** | Number input | `max_tokens` | User typed (optional) |
| **System Prompt** | Textarea (6 rows) | `system_prompt` | User typed or AI Generate |
| **MCP Tools** | Grid of checkboxes | `native_tools` | `NATIVE_TOOLS` constant |
| **Custom Tools** | Grid of checkboxes | `custom_tools` | `GET /api/custom-tools` |
| **Action Presets** | Toggle switch | `enforce_tool_constraints` | Binary toggle |
| **Execution Control** | Number input + dropdowns | `max_iterations`, etc. | Regular Agent only |
| **Memory** | Toggle | `enable_memory` | Binary toggle |

### ModelSelectorInline

**File**: [`src/components/common/ModelSelector.tsx`](../../../src/components/common/ModelSelector.tsx#L158-L211)

A minimal dropdown showing models organized by type:

```tsx
<select>
  <optgroup label="Cloud Models">
    <option value="gpt-4o">GPT-4o</option>
    <option value="claude-sonnet-4-5">Claude Sonnet 4.5</option>
    <option value="gemini-2.5-flash">Gemini 2.5 Flash</option>
    <!-- ... more cloud models -->
  </optgroup>
  <optgroup label="Local Models">
    <option value="ollama-llama3">llama3.2:latest (Ollama)</option>
    <!-- ... validated local models -->
  </optgroup>
</select>
```

The dropdown is populated by the `useAvailableModels` hook.

### useAvailableModels Hook

**File**: [`src/hooks/useAvailableModels.ts`](../../../src/hooks/useAvailableModels.ts)

```typescript
function useAvailableModels(options): {
  models: ModelOption[];      // Combined cloud + local
  cloudModels: ModelOption[]; // Cloud only
  localModels: ModelOption[]; // Local only
  isLoading: boolean;
  error: string | null;
}
```

**Flow:**
1. Calls `apiClient.listAvailableModels()` → `GET /api/settings/available-models`
2. Backend returns `{ models: string[], local_models: LocalModel[] }`
3. Cloud model IDs mapped to display names via `modelDisplayNames` map (e.g. `"claude-sonnet-4-5"` → `{ name: "Claude Sonnet 4.5", provider: "Anthropic" }`)
4. Local models fetched from `GET /api/local-models`, filtered to validated ones
5. Combined into `ModelOption[]` array for the dropdown

### Tools Section — Native Tool Checkboxes

```typescript
const NATIVE_TOOLS = [
  { id: 'web_search',      name: 'Web Search',     description: 'Search the internet' },
  { id: 'ls',              name: 'List Directory',  description: 'List files in directory' },
  { id: 'read_file',       name: 'Read File',       description: 'Read file contents' },
  { id: 'write_file',      name: 'Write File',      description: 'Create or overwrite files' },
  { id: 'edit_file',       name: 'Edit File',       description: 'Edit existing files' },
  { id: 'glob',            name: 'Glob',            description: 'Find files by pattern' },
  { id: 'grep',            name: 'Grep',            description: 'Search file contents' },
  { id: 'tavily_search',   name: 'Tavily Search',   description: 'Powered by Tavily' },
  // ... more tools
];
```

### Save Flow

When the user clicks "Save Agent" (`#L483-507`):

```typescript
const handleSaveNewAgent = async (config) => {
  const requestData = {
    name: config.name || 'Untitled Agent',
    description: config.description || '',
    category: config.category || 'Custom',
    config  // The full AgentConfig object
  };
  const response = await apiClient.createDeepAgent(requestData);
  // response.data = saved agent with id, timestamps, etc.
};
```

The full `config` object (including model, temperature, tools, etc.) is sent as-is to the backend.

---

## 2. API Client

**File**: [`src/lib/api-client.ts`](../../../src/lib/api-client.ts)

Key endpoints used during agent creation and model configuration:

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/settings/available-models` | GET | Fetch cloud + local model list |
| `/api/settings/model-defaults` | GET/POST | Get/save default model settings |
| `/api/local-models` | GET | Fetch local models (Ollama, LM Studio, etc.) |
| `/api/deepagents` | POST | Create a new agent (receives full config) |
| `/api/deepagents` | GET | List saved agents |
| `/api/agents/templates` | GET | Fetch built-in agent templates |
| `/api/custom-tools` | GET | Fetch user-created custom tools |

---

## 3. Backend: AgentFactory — Config to Agent

**File**: [`backend/core/agents/factory.py`](../../../backend/core/agents/factory.py)

### Create Agent Flow

```
POST /api/deepagents → DeepAgentFactory.create_deep_agent(config)
  │
  ├─ 1. Validate config (Pydantic DeepAgentConfig)
  │     └─ model, temperature, system_prompt, tools, etc.
  │
  ├─ 2. Resolve model → provider + API key
  │     └─ config.py: PROVIDER_API_KEY_MAP
  │         "openai" → OPENAI_API_KEY
  │         "anthropic" → ANTHROPIC_API_KEY
  │         "google" → GOOGLE_API_KEY
  │         "tavily" → TAVILY_API_KEY
  │
  ├─ 3. Initialize model
  │     └─ ChatOpenAI(model=..., temperature=..., api_key=...)
  │      or ChatAnthropic(model=..., temperature=..., api_key=...)
  │
  ├─ 4. Load tools
  │     ├─ native_tools → NativeToolFactory.from_names()
  │     ├─ cli_tools → CLIToolFactory.from_categories()
  │     └─ custom_tools → ToolFactory.create_tool() (DB lookup)
  │
  ├─ 5. Wrap tools with constraints (if enforce_tool_constraints)
  │     └─ wrap_tools_with_constraints()
  │         ├─ Timeout (asyncio.wait_for)
  │         ├─ Retry (exponential backoff)
  │         ├─ Exclusive execution (asyncio.Lock)
  │         └─ HITL approval gate
  │
  ├─ 6. Load memory tools (if enable_memory)
  │     └─ AgentMemorySystem(vector_store, project_id, agent_id)
  │
  ├─ 7. Build middleware stack (if use_deepagents)
  │     ├─ TodoListMiddleware → write_todos/update_todo/complete_todo tools
  │     └─ FilesystemMiddleware → file I/O with workspaces
  │
  ├─ 8. Create agent
  │     └─ create_react_agent(model, tools, state_modifier=system_prompt)
  │      or deepagents.create_deep_agent(model, tools, middleware, subagents, ...)
  │
  └─ 9. Return CompiledStateGraph
```

### Model Resolution (provider + API key)

**File**: [`backend/config.py`](../../../backend/config.py)

```python
# Provider → API key environment variable mapping
PROVIDER_API_KEY_MAP: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "glm": "GLM_API_KEY",
    "minimax": "MINIMAX_API_KEY",
}

# Each model ID is mapped to a provider
# "gpt-4o" → "openai" → os.getenv("OPENAI_API_KEY")
# "claude-sonnet-4-5" → "anthropic" → os.getenv("ANTHROPIC_API_KEY")
```

**Resolution logic** (in `factory.py`):
1. Parse model ID to determine provider (`gpt-*` → openai, `claude-*` → anthropic, etc.)
2. Look up API key from `PROVIDER_API_KEY_MAP`
3. Fallback chain: DB → .env → explicit error if missing

---

## 4. Model Defaults Settings

**File**: [`src/features/settings/ui/ModelDefaultsSettings.tsx`](../../../src/features/settings/ui/ModelDefaultsSettings.tsx)

The Settings page has a "Model Defaults" tab that lets users configure system-wide defaults:

```typescript
interface ModelDefaultsSettings {
  primaryModel: string;         // Default model for new agents
  fallbackModels: string[];     // Fallback models if primary fails
  temperature: number;          // 0.0–2.0 (default: 0.7)
  maxTokens: number;            // Default: 4096
  topP: number;                 // 0.0–1.0 (default: 1.0)
  routingStrategy: string;      // "balanced" | "cost_optimized" | "performance"
  dailyTokenLimit: number;      // 0 = unlimited
  monthlyTokenLimit: number;    // 0 = unlimited
  alertThreshold: number;       // Percentage before hitting limit (default: 80)
}
```

**Settings Hierarchy** (from top of UI to bottom):
1. **Model Defaults** (system-wide defaults for new agents)
2. **Per-Agent Config** (overrides defaults when creating a specific agent)

---

---

## 5. User Walkthrough — Step by Step

This section walks through the agent creation process as a **real user** would experience it, screen by screen.

### Step 1: Click "Create Custom Agent"

Starting from the **Agent Library** page ([`ModernAgentLibrary.tsx`](../../../src/features/agents/ui/ModernAgentLibrary.tsx)):

```
┌─────────────────────────────────────────────────┐
│  Agent Library                          [+ Create Custom Agent] ← Click me
│                                                   │
│  ┌─ Code Generation ────────────────────────┐    │
│  │  Code Researcher     │  Code Reviewer     │    │
│  │  Bug Hunter          │  Code Formatter    │    │
│  └───────────────────────────────────────────┘    │
│  ┌─ Research ───────────────────────────────┐    │
│  │  Web Researcher       │  Academic Search │    │
│  └───────────────────────────────────────────┘    │
│                                         3 Categories │
│                                         12 Total Agents │
└─────────────────────────────────────────────────┘
```

### Step 2: Choose Agent Type

A modal ([`ModernAgentLibrary.tsx#L1148-L1260`](../../../src/features/agents/ui/ModernAgentLibrary.tsx#L1148-L1260)) pops up with two cards:

```
┌─────────────────────────────────────────────────────┐
│  Choose Agent Type                                    │
│  Select the type of agent you want to create          │
│                                                       │
│  ┌─ Regular Agent ───────────┐  ┌─ Deep Agent ────────────┐│
│  │ [terminal icon]            │  │ [psychology icon]        ││
│  │ Standard LangChain agent   │  │ Advanced agent with      ││
│  │ with tool calling          │  │ planning and subagents   ││
│  │                            │  │                          ││
│  │ • Model selection          │  │ • Planning capabilities  ││
│  │ • System prompt            │  │ • Subagent delegation    ││
│  │ • Tool selection           │  │ • Backend storage        ││
│  │ • Execution controls       │  │ • Middleware             ││
│  │ • Simple memory            │  │ • Reflection & critique  ││
│  └────────────────────────────┘  └──────────────────────────┘│
│                                              [Cancel]         │
└─────────────────────────────────────────────────────┘
```

What happens in code: `setAgentType('regular' | 'deep')` → `setShowAgentBuilder(true)`.

### Step 3: The Builder Opens — Basic Settings First

The [`DeepAgentBuilder`](../../../src/features/agents/ui/DeepAgentBuilder.tsx) modal slides in as a full-height panel with sections in order:

```
┌──────────────────────────────────────────────────────┐
│  [< Back]  Create Agent   [AI Generate]  [×]          │
│  ─────────────────────────────────────────────────    │
│                                                        │
│  ⚙ BASIC SETTINGS (expanded) ▼                         │
│  ─────────────────────────────────────────────          │
│  Agent Name *    [Code Researcher            ]          │
│                                                        │
│  Description *   [Analyzes codebases, finds   ]        │
│                  [bugs, suggests improvements ]        │
│                                                        │
│  ┌────────────────────────────────────┐                │
│  │ 💡 Fill out Name & Description,    │                │
│  │ then click "AI Generate" to        │                │
│  │ auto-fill the rest                 │                │
│  └────────────────────────────────────┘                │
│                                                        │
│  Category    [Code Generation ▼]    Model    [select ▼]│
│             ┌──────────────┐          ┌──────────────┐│
│             │ Code Generation│         │ Claude Sonnet││
│             │ Research      │         │  4.5 (Anth)  ││
│             │ Testing       │         │ GPT-4o (OAI) ││
│             │ Documentation │         │ Gemini 2.5   ││
│             │ Custom        │         │ ───────────── ││
│             └──────────────┘          │ Ollama Llama ││
│                                        │  3.2 (Local) ││
│                                       └──────────────┘│
│                                                        │
│  Temperature (0.70)                                    │
│  ───●──────────────────────────────  [range slider]    │
│  0.0                     1.0                    2.0    │
│                                                        │
│  Max Tokens (Optional)   [ 4096                 ]      │
│                                                        │
│  ─────────────────────────────────────────────          │
│  🧠 SYSTEM PROMPT (expanded) ▼                          │
│  ─────────────────────────────────────────────          │
│  [You are an expert code researcher...           ]      │
│  [                                                ]      │
│  [6 rows textarea                                 ]      │
│  └────────────────────────────────────────────────┘    │
```

**What the user does:**
1. Types **Agent Name** and **Description**
2. Selects **Category** from dropdown
3. Picks a **Model** — dropdown populated from `GET /api/settings/available-models`
4. Drags the **Temperature slider**
5. Optionally sets **Max Tokens**
6. Writes a **System Prompt** (or clicks "AI Generate" to auto-fill)

**Under the hood:**
- `config.name`, `config.description`, `config.category` ← text inputs
- `config.model` ← `<ModelSelectorInline>` (<select> populated by `useAvailableModels` hook)
- `config.temperature` ← `<input type="range" min="0" max="2" step="0.1">`
- `config.max_tokens` ← `<input type="number">`
- `config.system_prompt` ← `<textarea rows={6}>`

### Step 4: AI Generate (Optional Shortcut)

If the user clicks **AI Generate** instead of typing everything:

```typescript
const handleAIGenerate = async () => {
  // 1. Requires name + description + category to be filled
  if (!config.name?.trim() || !config.description?.trim() || !config.category?.trim()) {
    showWarning('Please fill out Name, Description, and Category first');
    return;
  }

  // 2. Calls POST /api/agents/generate-config
  const response = await apiClient.generateAgentConfig({
    name: config.name,
    description: config.description,
    agent_type: agentType,
    category: config.category
  });

  // 3. Backend returns: model, temperature, system_prompt, native_tools
  setConfig(prev => ({
    ...prev,
    model: result.config.model,
    temperature: result.config.temperature,
    system_prompt: result.config.system_prompt,
    native_tools: result.config.native_tools || []
  }));
};
```

### Step 5: Select Tools

Scrolling down, the user sees:

```
  ⚡ TOOLS & CAPABILITIES (expanded) ▼
  ─────────────────────────────────────────────
  MCP Tools (Native)
  
  ┌─────────────────┐  ┌─────────────────┐
  │ ☑ List Directory │  │ ☑ Read File     │
  │ List dir contents│  │ Read file with  │
  │ with metadata    │  │ line numbers    │
  ├─────────────────┤  ├─────────────────┤
  │ ☑ Write File     │  │ ☑ Edit File     │
  │ Create new files │  │ String replace  │
  ├─────────────────┤  ├─────────────────┤
  │ ☑ Find Files     │  │ ☑ Search Content│
  │ Glob patterns    │  │ Regex search    │
  ├─────────────────┤  ├─────────────────┤
  │ ☑ Web Search     │  │ ☐ Web Fetch     │
  │ DuckDuckGo (free)│  │ Fetch webpages  │
  ├─────────────────┤  ├─────────────────┤
  │ ☐ Browser        │  │ ☐ Store Memory  │
  │ Playwright web   │  │ Save info for   │
  │ interaction      │  │ later recall    │
  ├─────────────────┤  ├─────────────────┤
  │ ☐ Recall Memory  │  │ ☐ Reasoning     │
  │ Retrieve stored  │  │ Chain           │
  │ information      │  │ Multi-step logic│
  └─────────────────┘  └─────────────────┘

  ┌───────────────────────────────────────────┐
  │ 🛡 Action Preset Safety Controls          │
  │ [☐] Enable tool constraints (timeout,      │
  │      retry, HITL approval)                │
  │                                            │
  │  Disabled: Tools run without safety        │
  │  controls. Enable for production use.      │
  └───────────────────────────────────────────┘
```

**What the user does:**
- Checks/unchecks **native tools** — these become `config.native_tools[]`
- Optionally enables **Action Preset Safety Controls** — sets `config.enforce_tool_constraints`
- If custom tools exist in the database, they appear in a separate **Custom Tools** section

**Note:** The `task` tool is special — it's auto-enabled for Deep Agents for subagent delegation.

### Step 6: Configure Advanced Sections (Collapsed by Default)

The user needs to **click to expand** each section:

**Execution Control** (Regular Agent only):
```
  ⚙ EXECUTION CONTROL ▼
  ─────────────────────────────────────────────
  Max Iterations    [15]
  
  💡 Each tool call = 1 iteration
    • 10-15: Simple tasks
    • 20-30: Multi-step workflows
    • 40+: Complex research
  
  Early Stopping Method  [Force ▼]
  (force = return incomplete, generate = continue)
  
  ☑ Handle Parsing Errors (auto-retry)
  ☐ Verbose Logging
```

**Memory** (Regular Agent only):
```
  🧠 MEMORY ▼
  ─────────────────────────────────────────────
  ☐ Enable Memory (short-term conversation)
  Memory Type  [Buffer ▼]
  
  ☐ Enable RAG (long-term vector memory)
```

### Step 7: Deep Agent Specifics (If "Deep Agent" was selected)

If the user chose **Deep Agent**, four additional sections are available:

**Middleware:**
```
  🔧 MIDDLEWARE ▼
  ─────────────────────────────────────────────
  ☑ Todo List   (Task planning & tracking)
  ☑ Filesystem  (File I/O with workspaces)
  ☑ Subagent    (Auto-configures subagent delegation)
```

**Subagents:**
```
  👥 SUBAGENTS ▼
  ─────────────────────────────────────────────
  [No subagents configured]
  [+ Add Subagent]  ← Click to add
  
  When you click [+ Add Subagent]:
  ┌─ Subagent 1 ───────────────────────────┐
  │ Name          [Code Analyzer       ]    │
  │ Description   [Deep code analysis ]    │
  │ Type          [Dictionary ▼] [Compiled]│
  │              (simple tools)  (workflow) │
  │ Model         claude-sonnet-4-5        │
  │ System Prompt [Analyze the code...]    │
  │ Tools: [☑ read_file] [☑ grep] [☑ ...] │
  │ Workflow ID   [select ▼] (if Compiled) │
  │                                         │
  │ [+ Add Subagent Tool]  [🗑 Delete]      │
  └─────────────────────────────────────────┘
```

**Backend Storage:**
```
  💾 BACKEND ▼
  ─────────────────────────────────────────────
  Toggle storage backends (select one or more):
  
  [☐ State]       [☐ Store]      [☑ Filesystem]
  [☐ Vector DB]   [☐ Composite]
  
  Current: Filesystem (persistent file storage)
  ↳ If multiple selected: Composite backend auto-configured
```

**Guardrails:**
```
  🛡 GUARDRAILS ▼
  ─────────────────────────────────────────────
  Token Limits:
    Max Total Tokens:     [100000]
    Eviction Threshold:   [80000]
    Summarization Mhresh: [60000]
  
  ☑ Auto-eviction (evict large tool results)
  ☑ Auto-summarization (summarize long history)
  
  Compaction Strategy:  [Trim Messages ▼]
  Preserve Recent Msgs: [10]
  
  Context Window Mode:  [Balanced ▼]
  (rapid / balanced / long-term)
  
  ☐ Long-term memory (cross-session via Store)
```

### Step 8: Save the Agent

Once all settings are configured, the user clicks **Save** (top-right of builder panel):

```typescript
const handleSaveNewAgent = async (config) => {
  // 1. POST /api/deepagents
  const response = await apiClient.createDeepAgent({
    name: config.name,
    description: config.description,
    category: config.category,
    config  // Full AgentConfig object
  });

  // 2. Show success notification
  showSuccess('Agent created successfully!');

  // 3. Close builder, show success modal
  setShowAgentBuilder(false);
  setNewlyCreatedAgent(response.data);

  // 4. Success modal: "Would you like to add this agent to your workflow now?"
};
```

The **full config object** is sent to the backend. Example payload:

```json
{
  "name": "Code Researcher",
  "description": "Analyzes codebases, finds bugs, suggests improvements",
  "category": "Code Generation",
  "config": {
    "model": "claude-sonnet-4-5-20250929",
    "temperature": 0.3,
    "max_tokens": 4096,
    "system_prompt": "You are an expert code researcher...",
    "native_tools": ["ls", "read_file", "grep", "web_search", "memory_store"],
    "custom_tools": [],
    "cli_tools": [],
    "use_deepagents": true,
    "middleware": [
      {"type": "todo_list", "enabled": true, "config": {"auto_track": true}},
      {"type": "filesystem", "enabled": true, "config": {"auto_eviction": true}},
      {"type": "subagent", "enabled": true, "config": {"max_depth": 3}}
    ],
    "subagents": [],
    "backend": {"type": "state", "config": {}},
    "guardrails": {
      "token_limits": {"max_total_tokens": 100000, "eviction_threshold": 80000, "summarization_threshold": 60000},
      "enable_auto_eviction": true,
      "enable_summarization": true,
      "compaction_strategy": "trim_messages",
      "preserve_recent_messages": 10,
      "context_window_mode": "balanced",
      "trim_strategy": "oldest"
    },
    "enforce_tool_constraints": false
  }
}
```

### Step 9: Agent Appears in Library

A success modal pops up:

```
┌────────────────────────────────────┐
│  Agent Created!                     │
│                                     │
│  Code Researcher has been saved     │
│  successfully.                      │
│                                     │
│  Would you like to add this agent   │
│  to your workflow now?              │
│                                     │
│          [Skip]  [Add to Workflow]  │
└────────────────────────────────────┘
```

The new agent appears under **Custom Agents** in the library (`ModernAgentLibrary.tsx#L372-408`):

```typescript
const customAgentsList: Agent[] = customAgents.map((ca: any) => ({
  id: `custom_${ca.id}`,
  name: ca.name,
  model: ca.config.model,
  temperature: ca.config.temperature,
  system_prompt: ca.config.system_prompt,
  native_tools: ca.config.native_tools || [],
  use_deepagents: ca.use_deepagents ?? true,
  // ...
}));
```

### AgentConfigView — Editing an Existing Agent

If the user clicks on a saved agent in the library, they get a detailed view ([`AgentLoadouts.tsx#L72+`](../../../src/features/agents/ui/AgentLoadouts.tsx)) that shows:

- **Agent info**: name, description, category, version, usage count
- **Model config**: model, temperature, max tokens
- **System prompt** (preview with expand)
- **Tools**: native tools (checkboxes), custom tools (checkboxes)
- **Middleware**: toggles (timestamp, logging, validation, cost tracking, etc.)
- **Guardrails**: custom guardrails text overrides
- **Subagents**: list with expand/collapse

The user can click **Save** to `POST /api/deepagents/{id}` or **Delete** to remove the agent.

---

## Sidebar Feature: Local Workspace (Settings → API & Providers → Local Workspace)

**UI File**: [`LocalWorkspaceSettings.tsx`](../../../src/features/settings/ui/LocalWorkspaceSettings.tsx)
**Backend Endpoint**: [`backend/api/system/settings.py#L443`](../../../backend/api/system/settings.py#L443) — `GET/POST /api/settings/workspace`
**DB Storage**: `settings` table → columns: `workspace_path`, `workspace_allow_read`, `workspace_allow_write`, etc.

### What It Looks Like

```
┌─ Settings ───────────────────────────────────┐
│                                                │
│  ⚙ Local Workspace                             │
│  ─────────────────────────────────             │
│  Configure workspace access for coding         │
│  agents. Agents can read and write files in    │
│  your workspace to help with development.      │
│                                                │
│  Workspace Directory                           │
│  ┌──────────────────────────────────────┐      │
│  │ /Users/you/projects/myapp       [Browse]│   │
│  └──────────────────────────────────────┘      │
│                                                │
│  Agent File Permissions                        │
│  ☑ Allow agents to read files                 │
│  ☑ Allow agents to create/edit files          │
│  ☐ Require approval before writing            │
│                                                │
│  Version Control                               │
│  ☑ Auto-detect git repository                  │
│  ☑ Backup files before agent edits             │
│                                                │
│  ⚠ Security Warning (shown if writes           │
│    enabled without approval)                   │
│                                                │
│  ─────────────────────────────────             │
│  ℹ How It Works                                │
│  1. Create a workflow with coding agent nodes  │
│  2. Agents get access to "local_files" tool    │
│  3. Agents read your code for context          │
│  4. Proposed changes shown in diff viewer      │
│  5. Review and approve/reject each change      │
│  6. Changes applied to workspace directory     │
│  7. Commit via your IDE or terminal            │
└────────────────────────────────────────────────┘
```

### The Two-Workspace Architecture

There are **two separate workspace concepts** in the backend — they serve different purposes:

|                     | Local Workspace (User's Code)        | Output Workspace (Agent's Results)          |
|---------------------|--------------------------------------|---------------------------------------------|
| **Purpose**         | Agents read user's source code       | Agents write generated files (reports, etc) |
| **Path**            | User-configured (e.g. `~/projects/app`) | `backend/outputs/project_{id}/workflow_{id}/task_{id}/` |
| **Default**         | Not set (user must configure)        | Always available (`backend/outputs/`)       |
| **Manager**         | (stored in `settings` table)         | [`WorkspaceManager`](../../../backend/services/workspace_manager.py) |
| **Tools using it**  | `read_file`, `ls`, `glob`, `grep`    | `write_file`, `list_task_files`             |
| **Security**        | Trust-based (agent instructions)     | `path.relative_to()` boundary check         |
| **DB tracking**     | No                                   | `WorkspaceFile` table (agent, task, meta)   |

### How It Works in Python

**Output workspace** (where agent-generated files go) — [`backend/services/workspace_manager.py`](../../../backend/services/workspace_manager.py):

```python
class WorkspaceManager:
    def __init__(self, base_dir=None):
        # Default: backend/outputs/
        self.base_dir = Path(__file__).parent.parent / "outputs"

    def get_task_workspace(self, project_id, workflow_id, task_id):
        # outputs/project_1/workflow_2/task_3/
        return self.base_dir / f"project_{project_id}" / f"workflow_{workflow_id}" / f"task_{task_id}"
```

**File writing** (in `write_file` native tool) — [`backend/tools/native_tools.py#L573`](../../../backend/tools/native_tools.py#L573):

```python
def _write_file_impl(file_path, content, _workspace_context=None, ...):
    # 1. Get workspace manager
    workspace_mgr = get_workspace_manager()

    # 2. Resolve path: outputs/project_X/workflow_Y/task_Z/filename
    if _workspace_context:
        workspace = workspace_mgr.get_task_workspace_with_override(
            project_id=_workspace_context.get('project_id'),
            workflow_id=_workspace_context.get('workflow_id'),
            task_id=_workspace_context.get('task_id'),
        )
    else:
        workspace = workspace_mgr.base_dir / "default"

    # 3. Security: ensure no path traversal
    path = (workspace / filename).resolve()
    try:
        path.relative_to(workspace.resolve())
    except ValueError:
        return "Error: Cannot write outside workspace directory"

    # 4. Write file
    path.write_text(content)

    # 5. Record metadata in WorkspaceFile DB table
    _record_file_metadata(filename, path, workspace, content,
                          workspace_context, agent_context)
```

**Security boundary check** — path traversal protection:

```python
# Both WorkspaceManager and API routes use this pattern
try:
    path.relative_to(workspace_resolved)
except ValueError:
    raise HTTPException(status_code=403, detail="Invalid path")
```

### Key Takeaways

1. **The sidebar setting stores a path + permissions** — it tells the system where the user's code lives and what agents are allowed to do there
2. **Agent writes always go to `outputs/`** — they never modify the user's source code directly. Generated reports, data files, and code snippets go to the organized output directory
3. **Agent reads go to wherever the path points** — the `read_file` tool has no boundary check; it trusts the agent's instructions. The permission toggles in settings control whether the agent is allowed to call these tools
4. **The `WorkspaceFile` DB table tracks everything** — every file write records the agent label, workflow ID, task ID, project ID, file metadata for full audit trail

## 6. Complete Data Flow Diagram

```
SETTINGS PAGE                     AGENT BUILDER                    BACKEND
─────────────                     ─────────────                    ───────

ModelDefaultsSettings         DeepAgentBuilder               DeepAgentFactory
  │                               │                              │
  ├─ primaryModel                 ├─ config.model                ├─ model → provider → API key
  ├─ temperature                  ├─ config.temperature          ├─ ChatOpenAI( model, temp )
  ├─ maxTokens                    ├─ config.max_tokens           ├─ tools → BaseTool[]
  │                               ├─ config.system_prompt        ├─ middleware → tools[]
  │                               ├─ config.native_tools         └─ create_react_agent()
  │                               ├─ config.custom_tools
  │                               │       │                              │
  │                               │       │                              │
  ▼                               ▼       ▼                              ▼
GET /api/settings/         POST /api/deepagents             CompiledStateGraph
    model-defaults              { name, config }               (ready for invoke)

         ModelSelectorInline ←── GET /api/settings/
                                    available-models

         Custom Tools ←────────── GET /api/custom-tools
```

---

## Key Takeaways

1. **Config is a plain JSON object** — The `AgentConfig` TypeScript interface maps 1:1 to the backend's `DeepAgentConfig` Pydantic model. No transformation needed.
2. **Model list is dynamically fetched** — The `ModelSelectorInline` component fetches available models from `GET /api/settings/available-models`, combining cloud models (hardcoded display names) with local models (from DB).
3. **API keys are resolved server-side** — The frontend never sees API keys. The backend maps model IDs to providers and looks up keys from DB (encrypted) → .env fallback.
4. **Three settings layers** — System defaults → Agent config → Runtime overrides (deepagents library).
5. **AI Generate fills the form** — Users can type just name + description, click "AI Generate", and the backend fills in the model, system prompt, and tools automatically.
6. **Saved agents are reusable** — `POST /api/deepagents` persists the config. Saved agents appear in the "Custom Agents" category of the agent library.
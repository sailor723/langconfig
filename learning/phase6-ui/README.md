# Phase 6: UI — Agents, Workflows, and the Studio

> A guided tour of the LangConfig frontend — how the UI exposes the agent and workflow concepts, where things live, and how to navigate the Studio, Library, and Agent panels.

This phase is more about **mental model + UX** than code paths. It synthesises what the code does with how the user actually interacts with it.

---

## 1. Mental Model: Agent vs Workflow

These two concepts are related but **distinct**.

### Agent — A Single Worker

An **agent** is a self-contained AI unit with:

| Field | What it is |
|---|---|
| `name` | Display name |
| `model` | e.g. `gpt-4o`, `claude-sonnet`, `deepseek-chat` |
| `system_prompt` | Instructions / persona |
| `tools` | MCP tools, CLI tools, custom tools the agent can call |
| `temperature` | Creativity / determinism knob |
| `memory` | Long-term memory flag |
| `RAG` | Knowledge base access flag |

> An agent is a **node** in a graph. It receives input, thinks, optionally calls tools, returns output.

Defined in [`backend/core/agents/factory.py`](../../backend/core/agents/factory.py) and exposed in `AgentLoadouts` (the **Agents** tab).

### Workflow — A Graph of Nodes

A **workflow** is an **orchestration** of multiple nodes. Each node is usually an agent, but you can also have control nodes (Start, End, Conditional, Loop, Approval). The workflow defines:

- Execution order (Start → A → B → … → End)
- Data routing between nodes
- Branching, loops, and human approval points
- State and checkpointing across the graph

Defined in [`backend/core/workflows/graph.py`](../../backend/core/workflows/graph.py) and edited visually in the **Studio** canvas.

### The Relationship

```
Agent     = a single worker (model + tools + prompt)
Workflow  = a factory line (Start → Agent(s) → Conditional → ... → End)
```

**Agents are the building blocks. Workflows are the blueprints that wire them together.**

| Aspect | Agent | Workflow |
|---|---|---|
| Storage | `deep_agent_templates` table | `workflows` table |
| UI tab | **Agents** | **Studio** + **Library** |
| Contains | model, prompt, tools | nodes + edges (a graph) |
| Created by | Form in AgentLoadouts | Drag-and-drop on canvas |
| Run by | `Test Agent` modal | `Run` button on canvas |
| Can contain other agents? | No | Yes — agents are nodes |

**Simple workflow** (one agent):
```
Start ──→ Greeting Agent ──→ End
```

**Complex workflow** (multi-agent):
```
Start ──→ Router Agent ──→ Research Agent ──→ End
                │
                └──→ Code Agent ──→ Review Agent ──→ End
```

---

## 2. The Three Main UI Surfaces

### 2.1 Studio — Visual Canvas

**File**: [`src/features/workflows/canvas/WorkflowCanvas.tsx`](../../src/features/workflows/canvas/WorkflowCanvas.tsx)

- Drag agents from the left **Agent Library** panel onto the canvas
- Connect them with edges (drag from one node's handle to another)
- **Control nodes** (`START_NODE`, `END_NODE`, `CONDITIONAL_NODE`, `LOOP_NODE`, `APPROVAL_NODE`) define the execution flow
- **Run** button (top-left, green `Play` icon) executes the workflow
- **Stop** button cancels a running workflow
- **Save** persists the graph to the database

**Renaming a workflow in Studio** (toolbar): double-click the workflow name in the top toolbar. It becomes an editable input — type the new name and press `Enter`.

### 2.2 Library — Saved Workflow Browser

**File**: [`src/features/workflows/library/WorkflowLibraryView.tsx`](../../src/features/workflows/library/WorkflowLibraryView.tsx)

- Shows all saved workflows grouped by project
- Search bar filters by name
- Click a workflow to open it in Studio
- **Renaming a workflow in Library**: **right-click** the workflow → context menu → **Rename** → modal opens

> Note: the rename option is hidden behind a **right-click context menu** — there's no visible "Rename" button in the default UI. The context menu (`WorkflowContextMenu.tsx`) also offers Duplicate, Change Project, and Delete.

### 2.3 Agents — Build & Configure

**File**: [`src/features/agents/ui/AgentLoadouts.tsx`](../../src/features/agents/ui/AgentLoadouts.tsx)

- Browse existing agents (left list)
- Create a new agent (form on the right)
- Edit an existing agent's config
- **Test Agent** opens the `AgentChatTester` modal — a streaming chat interface to interact with the agent without running a full workflow
- **View Code** shows the generated Python code for the agent

---

## 3. Control Nodes — Why They Exist

Workflows are directed graphs. The engine needs explicit markers to know:

| Node | Purpose |
|---|---|
| **Start** | Where execution begins; receives the initial input |
| **End** | Marks successful completion; returns final output |
| **Conditional** | Branch based on a condition (if/else) |
| **Loop** | Iterate over a list / until a condition |
| **Approval** | Pause and wait for human input (HITL) |

Without Start → End markers, the engine can't determine:
- **Where to start** — which node gets the initial input
- **When to stop** — that the workflow has completed

The runtime explicitly searches for the `START_NODE` to build its execution order:

```typescript
let startNode = nodes.find(n => n.data.agentType === 'START_NODE');
// Then follows edges from START_NODE through connected nodes
```

**Minimum viable workflow**: `Start → Agent → End`

---

## 4. Workflow Lifecycle

```
1. Studio    — Design the graph (drag agents, connect nodes)
2. Save      — Persist to database
3. Library   — Find the saved workflow (or right-click → Rename)
4. Studio    — Reopen, edit, or click Run
5. Run       — Enter prompt, execute
6. Results   — See outputs, token usage, execution log
```

Each **Run** creates a **Task** record. Tasks accumulate under the workflow in the left sidebar's **History** tab.

---

## 5. What I Built This Phase

During this learning session, the following UI-level work was done:

| Change | File | Purpose |
|---|---|---|
| Added `Test Agent` button styling | `src/features/agents/ui/AgentLoadouts.tsx` | Made the button visually active (primary color) instead of a gray outline |
| Added `View Code` button styling | `src/features/agents/ui/AgentLoadouts.tsx` | Same — primary color |
| Fixed `AgentChatTester` crash | `src/components/common/AgentChatTester.tsx` | Backend returns partial metrics object (missing `context_operations`); now we spread defaults first, then override |
| Wrapped `AgentChatTester` in `ErrorBoundary` | `src/components/common/AgentChatTester.tsx` | Shows a fallback message instead of a blank screen on any future error |
| Hardened `fetchMetrics` | `src/components/common/AgentChatTester.tsx` | Try/catch wrap, defaults to safe values |

---

## 6. Key Takeaways

1. **Agent = worker**, **Workflow = factory line**
2. Build agents in the **Agents** tab; compose them into workflows in **Studio**
3. Save → **Library** → right-click → Rename (or double-click in Studio toolbar)
4. Every workflow needs at minimum a **Start** and an **End** node
5. **Test Agent** is for quick interactive testing of a single agent; **Run** is for executing a full workflow

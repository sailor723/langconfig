# LangConfig — Usage Guide

How to use the app: the shell, the thirteen activities, and two end-to-end walkthroughs
(first agent, first workflow). For how it works internally see
[`system-architecture.md`](system-architecture.md); to install it see
[`installation.md`](installation.md).

Open **http://localhost:1421** after starting the stack.

---

## 1. The shell

The UI is a VS Code-style IDE. Five regions:

| Region | What it is |
|---|---|
| **Activity bar** (far left, 48px) | Thirteen activities. Clicking one swaps the sidebar and the main view. |
| **Left sidebar** | Contents of the current activity — a tree, a file list, a catalog, or a search panel. Resizable 200–600px. |
| **Workspace** (centre) | Tabbed editors. Tabs drag to reorder, middle-click to close, show a dirty dot when unsaved. |
| **Right panel** (540px, resizable 240–800) | Three tabs — **Chat** (default), **Doc Chat**, and **Properties** (appears only when a canvas node is selected). |
| **Bottom panel** | **Terminal**, **Execution**, **Results**. Toggle with **Ctrl+`**. |

> **Not yet wired:** the status bar (bottom, `#007acc`) is built but not mounted, and the
> keyboard shortcuts you may expect from VS Code (Ctrl+W, Ctrl+Tab, Cmd+Shift+P,
> Cmd+Shift+F) are not bound. Only Ctrl+` works.

Routing is via URL hash — `#/deepagents`, `#/workflows`, `#/graph`, `#/knowledge`,
`#/settings`, `#/learning`, `#/playground` — but tabs are an independent store, so the URL
selects the *activity* rather than a specific open document.

> The left sidebar is hidden on **Settings** and **Vault**, which open their own surfaces.

---

## 2. Four concepts before you start

| Concept | What it is |
|---|---|
| **LangChain Agent** | A standard `create_agent` graph: system prompt, tools, no sandbox, no skills. Lighter and cheaper. |
| **DeepAgent** | The full `deepagents` runtime: tools **+ skills + filesystem sandbox + middleware + subagents**. Use this for real work. |
| **Workflow** | A graph on a canvas — agent nodes, tool nodes, conditional branches — executed by LangGraph with persistence. |
| **Knowledge base** | A folder of documents that Doc Chat and agents can read. Managed by scope: a whole KB or a subfolder. |

Both agent kinds live in the same `deep_agent_templates` table and are chosen by one flag
(`use_deepagents`). A DeepAgent can also be given **subagents** and **skills**, which is
where most of the power is.

---

## 3. First run

1. Start the stack (`bash start.sh`). The backend seeds itself and reports
   `✅ Backend healthy`.
2. Open http://localhost:1421. If no key is configured yet the **setup wizard** appears.
3. Go to **Settings → API Keys** and paste a provider key. Keys are stored **encrypted in
   PostgreSQL**, not in `.env` — a key placed in `.env` is ignored.
4. **Settings → Models** to pick a default model. The catalog is DB-driven (29 seeded cloud
   models), so nothing needs a code change to add one.

Without a key, every agent and the Playground will fail at the first LLM call.

---

## 4. The thirteen activities

### Vault
Opens a popover (Obsidian-style vault switcher) rather than navigating. It selects the
vault/root that knowledge bases and agent workspaces resolve under. No sidebar.

### DeepAgents
The list of DeepAgent templates. Selecting one opens the **DeepAgent Editor** with seven
sections: **Overview · Prompt · Tools · Subagents · Middleware · Guardrails · JSON**.
The chat panel on the right talks to the agent you are editing — this is the normal way to
iterate on an agent.

**Create** opens a form: name, category, description, model, max tokens, capabilities /
modalities, system prompt, tools, skills, subagents, middleware and safety controls.

### Agents
The same idea for plain LangChain agents — lighter config, no skills or sandbox.

### Workflows
The canvas. Drag nodes from the palette, connect them, select a node to edit it in the
right-hand **Properties** tab, then run. Node types:

| Kind | Types |
|---|---|
| Control | `START_NODE`, `END_NODE`, `CONDITIONAL_NODE`, `LOOP_NODE`, `CHECKPOINT_NODE`, `OUTPUT_NODE`, `APPROVAL_NODE` |
| Work | `AGENT_NODE`, `SUBAGENT_NODE`, `LLM_NODE`, `TOOL_NODE` |

`START_NODE`/`END_NODE` are markers — they map to the graph's entry and exit rather than
becoming nodes. Conditional and loop nodes evaluate an AST-validated expression (not
`eval`). Config is auto-saved with a short debounce; versions are snapshotted, so you can
compare or roll back.

### Graph
**Graph Studio** — for *code-defined* LangGraph apps. It hosts the modules in
`backend/langgraph/*.py` inside the API process (no separate `langgraph dev` server), and
gives you: a structural canvas, thread creation, SSE-streamed test runs, an ER diagram
view, and a Neo4j network view for graph-shaped data.

### Prompt
A prompt library. Browse/search prompts, create a new one, and open one as a
`prompt-detail` tab to edit and reuse it.

### Tools
Tool catalog grouped by category, plus two editors: the standard **Tool Editor** and the
**Custom Tool Builder** for authoring new ones. 64 built-in tools are seeded into
`custom_tools` as self-contained Python functions, so agents compile their tools directly
from the database — there is no hardcoded tool list at runtime.

### Skills
`SKILL.md`-based capabilities with progressive disclosure: the agent is told each skill's
name, description and path up front, and reads the body only when it decides the skill is
relevant. 43 skills are seeded. The `skill-generator` meta-skill can author new ones.

### Knowledge
Knowledge bases and their contents. Two things live here: the **knowledge browser**
(indexing, folders, documents) and **Doc Chat**, which answers questions over a knowledge
base folder — a *folder-based* path with no vector DB or Neo4j required, so it works on a
fresh install. Open Doc Chat from the right panel or the Knowledge sidebar.

### Analysis
Dashboard generation over tabular data (CSV/SQLite) — the KPI/dashboard activity. The
generated HTML dashboards render inside the app with Plotly served locally, so they work
without internet access.

### Studio
A read-only topology view of a DeepAgent — the main agent and its subagents on a canvas.
Visualisation only; **it currently opens a fixed agent**, so treat it as a demo rather than
a per-agent inspector.

### Learning
The in-app curriculum: Jupyter notebooks from `backend/notebooks/` (modules 0–6) rendered
and runnable in place, with matching notes under `learning/`. Best starting point after
this guide.

### Settings
Ten namespaced settings sections — `general`, `models`, `agents`, `knowledge`, `rag`,
`storage`, `workspace`, `runtime`, `onboarding`, `search`. Includes **Model Cards** (with
the ▶ **Play** button that opens the Playground), API keys, default model, local model
endpoints, storage mode and agent token limits. Every write is validated against a schema
and revision-guarded, so two tabs cannot silently clobber each other.

---

## 5. Walkthrough — your first agent

1. **Settings → API Keys**: add a key. **Settings → Models**: choose a default.
2. **Activity bar → DeepAgents → Create.**
3. Fill in the **Overview**: name (`support-triage`), description, model, max tokens.
4. Write a **system prompt**. Be concrete about the job and the output shape — this is the
   single biggest lever on quality.
5. **Tools**: add what the agent actually needs. Fewer is better; every tool costs context.
6. **Skills**: add only skills whose *description* would make the agent pick them.
7. **Subagents** (optional): give the main agent specialists it can delegate to, each with
   its own prompt and model.
8. Save. The agent appears in the sidebar list.
9. Select it and use the **Chat** tab on the right. The first message is slower — the agent
   is being built and the skill catalog staged. Later turns reuse the cached agent until
   you change its config.

Chat behaviour worth knowing:

- Responses stream token by token, and `<think>` blocks are separated from the answer.
- Tool calls appear as their own events, with arguments and results.
- Every turn is written to `chat_sessions.messages` **and** archived as a history row;
  LangGraph state lives under the session's `thread_id`.
- **Message banking** pins important messages so summarisation cannot drop them.
- Long conversations are summarised automatically once they cross the token threshold;
  evicted history is offloaded to a file the agent can still read.

**Playground** (Settings → Model Cards → ▶ Play) is the other end of the spectrum: a raw
`model.invoke()` with no agent, no tools, no memory. It has preset chips for greetings,
math, JSON, tools, search, streaming, vision and reasoning. Use it to check a model or a
key before blaming an agent.

---

## 6. Walkthrough — your first workflow

1. **Activity bar → Workflows → New.**
2. Drag **START_NODE** onto the canvas.
3. Drag an **AGENT_NODE** and point it at an existing agent template; set its model,
   tools and prompt overrides in the **Properties** tab.
4. Drag an **END_NODE**, then wire **START → AGENT → END** by dragging between handles.
5. Run it. The **Execution** tab in the bottom panel streams progress event by event, and
   the **Results** section collects what the run produced.
6. Open the workflow later to see saved runs, tokens and cost per run.

Adding branching: a **CONDITIONAL_NODE** reads `state["conditional_route"]` and the
outgoing edge labels decide where execution continues. Guardrails:

- the run has a wall-clock ceiling and an event cap, so a runaway loop terminates;
- state is checkpointed to PostgreSQL, so a run is durable;
- every node's failure is captured on that node rather than aborting the graph — check the
  node's status, not just the run's.

> **Approval nodes are informational in practice.** An `APPROVAL_NODE` is *meant* to pause
> the run for a human; today the approval endpoint publishes an event but does not resume
> the paused graph. Do not rely on it as a control.

---

## 7. The right panel: Chat vs Doc Chat

| Tab | Talks to | Use for |
|---|---|---|
| **Chat** | The agent you have open (session-based, tool-using, streaming) | Iterating on an agent, running real tasks |
| **Doc Chat** | A knowledge base folder — no agent, no vector store | "What does this folder say about X?" |
| **Properties** | Nothing — it edits the selected canvas node | Node config in a workflow |

Both Chat and Doc Chat are session-scoped. Session cleanup runs on a TTL; a session that
has been idle is reclaimed, and its checkpoints are deleted when you end it.

---

## 8. Where your data goes

| You do this | It lands here |
|---|---|
| Chat with an agent | `chat_sessions` (messages + metrics) and `conversation_archives`; runtime state in LangGraph checkpoints keyed by `thread_id` |
| Run a workflow | `workflow_executions` + `workflow_versions`, checkpoints under `workflow_<id>_task_<id>` |
| Upload to a knowledge base | the KB root on disk (`KB_ROOT`), or PostgreSQL when storage mode is `db` |
| Let an agent write a file | the agent workspace: `upload/`, `generated/`, `skills/`, `other/` |
| Change a setting | the `settings_documents` row for that namespace, revision +1 |

Storage mode is a runtime setting: `local` (disk) or `db` (PostgreSQL BYTEA). See
[`reference/storage-map.md`](reference/storage-map.md) for the full layout.

---

## 9. Known gaps

Honest list of what is built but not reachable, or reachable but not finished:

- **Status bar** — component exists, not mounted in the app shell.
- **Keyboard shortcuts** — only Ctrl+` is bound. Command palette and quick file picker
  components exist but nothing imports them.
- **Studio** — opens a hardcoded agent rather than the one you select.
- **Workflow approvals** — pause happens, resume does not (see §6).
- **Frontend i18n** — the translation file covers chat strings; most shell labels are
  hardcoded English.

---

## 10. Next steps

- **Learning** activity — the guided notebook curriculum, starts at module 0.
- [`system-architecture.md`](system-architecture.md) — why the pieces are shaped this way.
- [`reference/skill-authoring.md`](reference/skill-authoring.md) — turn a working agent
  into a reusable skill.
- [`reference/data-taxonomy.md`](reference/data-taxonomy.md) — registry vs knowledge vs
  workspace, and which one to use when.

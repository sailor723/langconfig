# Layout2 — VS Code-Style Agent IDE Shell

Refactoring the LangConfig UI from a top-nav web app layout to a VS Code-inspired IDE shell.

## Progress

### ✅ Phase 1: Layout Shell (Complete)

| Component | Status | Description |
|-----------|--------|-------------|
| `tokens.ts` | ✅ | Theme system mapping LangConfig → VS Code Dark Modern tokens |
| `useLayout.tsx` | ✅ | Shared context for layout state (activity, sidebar, tabs, panels) |
| `ActivityBar.tsx` | ✅ | 48px left icon strip (#181818 bg), left-edge white accent indicator, hover background |
| `LeftSidebar.tsx` | ✅ | Unified sidebar shell — resizable (200-600px), title bar, status bar with item count |
| `Workspace.tsx` | ✅ | Tab bar (35px, drag-reorder, middle-click close) + content area |
| `NodeSidebar.tsx` | ✅ | Always-visible right panel with Chat tab (default) and Properties tab (on node select) |
| `BottomPanel.tsx` | ✅ | VS Code-style panel with Terminal, Execution, Results tabs |
| `StatusBar.tsx` | ✅ | 22px blue (#007acc) bar with white text, model + token count + task |

### ✅ Phase 2: File Explorer

| Feature | Status | Description |
|---------|--------|-------------|
| TreeView (folders/files) | ✅ | Recursive tree with expand/collapse |
| Right-click context menu | ✅ | Rename, Delete, New File/Folder |
| Inline rename | ✅ | Double-click or F2 |
| Quick file picker (Cmd+P) | ✅ | Fuzzy search across all activity types |

### ✅ Phase 3: Tab Improvements

| Feature | Status | Description |
|---------|--------|-------------|
| Keyboard shortcuts | ✅ | Ctrl+W close, Ctrl+Tab switch, Cmd+Shift+P palette, Cmd+Shift+F search |
| Middle-click to close | ✅ | Middle-click on any tab closes it |
| Tab tooltips | ✅ | Full file path shown on hover |
| Tab drag-reorder | ✅ | HTML5 drag-and-drop tab reordering |
| Open file from API | ✅ | Real content from backend |

### ✅ Phase 4: Quick Actions

| Feature | Status | Description |
|---------|--------|-------------|
| Command palette (Cmd+Shift+P) | ✅ | 10+ commands: toggle panels, switch activities, new file, close tab |
| Search across files (Cmd+Shift+F) | ✅ | Sidebar search panel with results grouped by file, match highlighting |

### ✅ Phase 5: DeepAgents Sidebar + Structured Editor

| Feature | Status | Description |
|---------|--------|-------------|
| DeepAgents activity (Brain icon) | ✅ | New ActivityBar entry — clicks show flat list of deep agents from `GET /api/deepagents/` |
| Backend integration | ✅ | All deep agents loaded from PostgreSQL via Vite proxy (no CORS) |
| Structured DeepAgent editor | ✅ | 7 sections: Overview / Prompt / Tools / Subagents / Middleware / Guardrails / JSON |

### ✅ Phase 6: Resizable Sidebars

| Feature | Status | Description |
|---------|--------|-------------|
| LeftSidebar resize | ✅ | Drag the right edge of the file browser to resize (200–600px, default 260px) |
| NodeSidebar (right) resize | ✅ | Drag the left edge of the right panel to resize (240–800px, default 360px) |

### ✅ Phase 7: Agent Test Runner (Editor Toolbar)

| Feature | Status | Description |
|---------|--------|-------------|
| Run / Stop toolbar | ✅ | Each DeepAgent tab has a top toolbar (35px) with prompt input + ▶ Run + ■ Stop |
| Live API call | ✅ | Run starts a chat session (`POST /api/chat/start`) and sends the test prompt (`POST /api/chat/message`) |
| Session stored | ✅ | Session id saved on `chatStore` so follow-ups in the right chat panel reuse the same session |

### ✅ Phase 8: Right-Sidebar Chat + Thinking + Actions

| Feature | Status | Description |
|---------|--------|-------------|
| Shared chat store | ✅ | [chatStore.ts](file:///Users/weiping/dev/Learn/langchain-ai/langconfig/src/components/layout2/chatStore.ts) — module-level singleton with subscribe pattern |
| Session-aware send | ✅ | Chat input uses the active session id to send follow-ups to the same agent |
| Thinking extraction | ✅ | Strips `<think>...</think>` blocks, displays collapsible reasoning trace in agent bubbles |
| Copy / Save / Re-run | ✅ | Per assistant message: copy to clipboard, download as `.md`, re-run same prompt |
| Multi-message conversation | ✅ | User + assistant bubbles with timestamps and tokens/tools/latency footer |
| Free-form chat | ✅ | Right sidebar input lets you type any prompt without re-running from the toolbar |

### ✅ Phase 9: Studio Activity + Subagent/Skill Data Merge

| Feature | Status | Description |
|---------|--------|-------------|
| Studio activity (Network icon) | ✅ | New ActivityBar entry — embeds the DeepAgent Studio canvas directly in the layout shell (no port-hopping) |
| Subagent/Skill data merge | ✅ | DeepAgentEditor Subagents tab now reads from 4 fallback locations: `agent.subagents`, `agent.subagents_config`, `agent.config.subagents`, `agent.config.skills` |
| String-array normalization | ✅ | When `skills` is a string list (just names), each entry gets wrapped as `{name: ...}` so the UI still renders |
| Tab re-open fix | ✅ | LeftSidebar calls `openTab` twice for deep agents (immediately + on next tick) so the editor re-renders with the populated `agent` data after the async API call |

### ✅ Phase 10: SSE Streaming Chat

| Feature | Status | Description |
|---------|--------|-------------|
| chatStore streaming | ✅ | `sendStreamMessage()` matches `useChatStreaming` pattern — AbortController, thinking/tool phase tracking, SSE parsing |
| DeepAgentEditor streaming | ✅ | Run button uses `/api/chat/message/stream` with incremental token display |
| Stop button cancellation | ✅ | Stop button calls `chatStore.cancelStream()` which aborts the `AbortController` |
| NodeSidebar streaming | ✅ | ChatSidebar prefers streaming when agent+session available, falls back to blocking POST |
| Tool phase tracking | ✅ | Content before first `tool_start` event is tracked as "thinking" (reasoning trace) |

### ✅ Phase 11: Bottom Panel Real Data

| Feature | Status | Description |
|---------|--------|-------------|
| Execution tab | ✅ | Shows real assistant/system messages from chatStore with streaming indicator |
| Results tab | ✅ | Shows completed assistant responses with reasoning trace and latency markers |

### ✅ Phase 12: Save DeepAgent Edits

| Feature | Status | Description |
|---------|--------|-------------|
| JSON editor | ✅ | JSON section is now an editable textarea |
| Save button | ✅ | Green Save button in toolbar calls `PUT /api/deepagents/{id}` |
| Save feedback | ✅ | Success/error messages shown inline next to Save button

### ✅ Phase 13: DeepAgent Creator (New Agent Form)

| Feature | Status | Description |
|---------|--------|-------------|
| Creator form | ✅ | Name, description, category, system prompt, model, temperature |
| Sidebar "New Agent" button | ✅ | Dashed-border button at TOP of tree view for deepagents activity |
| Backend integration | ✅ | Submits via `POST /api/deepagents/`, auto-opens new agent in editor |
| Default config | ✅ | Sanely defaults: memory backend, empty tools/subagents/middleware |

### ✅ Phase 14: Theme Switcher (Dark / Warm / Light)

| Feature | Status | Description |
|---------|--------|-------------|
| Theme selector | ✅ | Three color dots in StatusBar — Dark, Warm (Claude), Light (LangConfig) |
| Persistence | ✅ | Uses existing `ThemeProvider`/`setTheme` from `lib/themes` |
| Obsidian-style | ✅ | Click dots to instantly switch between 3 themes |

### ✅ Phase 15: Models Sidebar (Out of Settings)

| Feature | Status | Description |
|---------|--------|-------------|
| Models activity | ✅ | New ActivityBar icon (Sparkles) — replaces Model Cards section in Settings |
| ModelCardsSidebar | ✅ | Cloud + local models grouped by provider with key/validation indicators |
| Set default | ✅ | Inline "Set default" button on each row; persists to backend + localStorage |
| StatusBar integration | ✅ | StatusBar reads default from localStorage and shows active model |
| Filter input | ✅ | Filter models by display name or id |

## Architecture

```
┌──────┬────────────┬───────────────────────┬──────────────┐
│ Act  │ Side Bar   │ Editor                │ Right Panel  │
│ Bar  │ (explorer/ │ (tabs + content)      │ Chat / Props │
│      │  search)   ├───────────────────────┤              │
│      │            │ Terminal / Exec / Results            │
├──────┴────────────┴───────────────────────┴──────────────┤
│ Status Bar (#007acc blue, full width)                    │
└──────────────────────────────────────────────────────────┘
```

### Activities (ActivityBar icons)

| Icon | Activity | Sidebar Source | Notes |
|------|----------|---------------|-------|
| GitBranch | Workflows | `GET /api/workflows/` | Existing |
| Brain | **DeepAgents** | `GET /api/deepagents/` | **Phase 5 — new** |
| Users | Agents | `GET /api/agents/routes` | Existing |
| Sparkles | **Models** | `GET /api/agents/available-models` | **Phase 15 — new** |
| BookOpen | Library | `GET /api/skills/` + tools | Pending |
| BarChart3 | Analysis | TBD | Pending |
| Settings | Settings | — | Hidden (no sidebar) |

```
App.tsx
└── LayoutProvider (useLayout.tsx)
    ├── ActivityBar (48px left, #181818)
    │   ├── workflows   → /studio
    │   ├── deepagents  → /deepagents       ← Phase 5
    │   ├── agents      → /agents
    │   ├── library     → /library
    │   ├── analysis    → /analysis
    │   └── settings    → /settings
    ├── [LeftSidebar (260px resizable)]
    │   ├── Title bar: uppercase label + actions (search, new, refresh)
    │   ├── SearchPanel (toggle: Cmd+Shift+F)
    │   └── TreeView / ModernAgentLibrary / etc.
    ├── [Center column] (flex 1)
    │   ├── Workspace
    │   │   ├── TabBar (35px, drag-reorder, middle-click close)
    │   │   └── TabContentView → DeepAgentEditor (deepagent viewType) ← Phase 5
    │   │                      → FileEditor     (workflow viewType)
    │   └── BottomPanel (collapsible)
    │       ├── Terminal (terminal emulator)
    │       ├── Execution (execution logs)
    │       └── Results (execution output)
    ├── [NodeSidebar (300px right)]
    │   ├── Chat tab (always visible, default)
    │   └── Properties tab (appears on node selection)
    └── StatusBar (22px, #007acc blue)
```

## Layout Preview

A standalone preview is available at `layout-preview.html`:

```
http://localhost:1421/layout-preview.html
```

The preview now defaults to the **DeepAgents** activity so you see real
deep-agent data from PostgreSQL on load. Backend at `http://localhost:8765`,
frontend at `http://localhost:1421`, Vite proxies `/api/*` to backend.

## Phase 5 — DeepAgents Editor

Clicking a deep agent in the sidebar opens [DeepAgentEditor.tsx](file:///Users/weiping/dev/Learn/langchain-ai/langconfig/src/components/layout2/DeepAgentEditor.tsx),
a structured form-based view with a left-rail section nav:

| Section | Content |
|---------|---------|
| **Overview** | Name, description, category, model, temperature, max_tokens, version, public, usage stats |
| **Prompt** | `system_prompt` rendered as preformatted monospace text |
| **Tools** | Native / CLI / Custom tools as colored chips |
| **Subagents** | Collapsible cards — name, description, model, tools, system_prompt |
| **Middleware** | List with ON/OFF badges + raw config JSON |
| **Guardrails** | Auto-eviction, summarization, long-term memory, token limits, backend type |
| **JSON** | Full raw agent config (power-user fallback) |

The full agent object is fetched from `GET /api/deepagents/{id}` and cached
on `tab.data.agent` so sections can read fields directly without re-fetching.

## Key Decisions

- **VS Code over Obsidian**: proper Agent IDE with dark theme (#181818 activity bar, #252526 sidebars, #1e1e1e editor, #007acc status bar)
- **No Docker**: lightweight SPA + FastAPI, no containers
- **Right sidebar always visible**: Chat by default, Properties tab on node selection
- **Bottom panel inside center column**: only spans editor width, not across sidebars
- **Both sidebars resizable**: VS Code-style drag-to-resize handles
- **Unified sidebar shell**: LeftSidebar/NodeSidebar accept children — old components render inside the same shell
- **Tab content from API**: sidebar loads real workflows from `GET /api/workflows/`, deep agents from `GET /api/deepagents/`, content from `GET /api/workflows/{id}/code` and `GET /api/deepagents/{id}`
- **contentStore**: in-memory Map for session-persistent tab content
- **chatStore**: module-level singleton for shared chat state (subscribe pattern, no Provider)
- **ui-system.tsx**: shared UI primitives (IconButton, ToolbarButton, MenuButton, HeaderLabel, PanelHeader)
- **Vite proxy for /api**: `VITE_API_BASE_URL` empty in dev so requests go through the same-origin proxy (no CORS)
- **Port 1421 for layout shell**: original langconfig UI stays on 1420; layout shell + DeepAgents sidebar runs on 1421
- **Thinking blocks**: optional `<think>...</think>` parsing from the LLM response, collapsible in the bubble. The model decides whether to emit them.

## Phase 7 — DeepAgent Editor Toolbar

Each DeepAgent tab has a 35px top action bar (VS Code run-toolbar style):

```
[ Test: <input prompt>    ] [▶ Run] [■ Stop]      ID: 1 · v1.0.0 · research
```

- Click **▶ Run** → `POST /api/chat/start` + `POST /api/chat/message` flow
- The session id is stored on `chatStore`, so the right-sidebar chat panel
  can send follow-ups without re-starting the session
- The Run response is also pushed to `chatStore` as a user/assistant pair

## Phase 8 — Right Sidebar Chat

The NodeSidebar's Chat tab is the conversation window. It reads from
`chatStore` and renders bubbles:

| Bubble | Style | Actions |
|--------|-------|---------|
| User | blue, right-aligned | — |
| Assistant | grey, left-aligned | Copy / Save / Re-run |
| System | red, left-aligned | — |

Assistant bubbles also expose a collapsible **🧠 Thinking (N chars)** button
when the LLM emitted a `<think>...` block. The Save button downloads the
full conversation as `.md`. Re-run resends the original user prompt and
appends the new assistant reply.

## Next Steps

- Phase 16: Agents / Skills / Tools sidebar categories (real backend integration)
- Phase 17: Monaco editor for the JSON tab
- Phase 18: Workflow canvas integration into Workspace
- Phase 19: Real terminal emulator (xterm.js) for the Terminal tab
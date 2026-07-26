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
| Users | Agents | `GET /api/agents/templates` | Pending |
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
- **Unified sidebar shell**: LeftSidebar/NodeSidebar accept children — old components render inside the same shell
- **Tab content from API**: sidebar loads real workflows from `GET /api/workflows/`, deep agents from `GET /api/deepagents/`, content from `GET /api/workflows/{id}/code` and `GET /api/deepagents/{id}`
- **contentStore**: in-memory Map for session-persistent tab content
- **ui-system.tsx**: shared UI primitives (IconButton, ToolbarButton, MenuButton, HeaderLabel, PanelHeader)
- **Vite proxy for /api**: `VITE_API_BASE_URL` empty in dev so requests go through the same-origin proxy (no CORS)
- **Port 1421 for layout shell**: original langconfig UI stays on 1420; layout shell + DeepAgents sidebar runs on 1421

## Next Steps

- Phase 6: Agents / Skills / Tools sidebar categories (real backend integration)
- Phase 7: Save edits from DeepAgentEditor back to backend via `PUT /api/deepagents/{id}`
- Phase 8: Monaco editor for the JSON tab
- Phase 9: Workflow canvas integration into Workspace
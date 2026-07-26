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

### ⏳ Phase 5: Editor Enhancements

| Feature | Status |
|---------|--------|
| Monaco editor (instead of textarea) | ⏳ |
| Status bar: real token/model info | ✅ (wired from workflow state) |
| File icon themes | ✅ (per view-type icons) |

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

```
App.tsx
└── LayoutProvider (useLayout.tsx)
    ├── ActivityBar (48px left, #181818)
    ├── [LeftSidebar (260px resizable)]
    │   ├── Title bar: uppercase label + actions (search, new, refresh)
    │   ├── SearchPanel (toggle: Cmd+Shift+F)
    │   └── TreeView / ModernAgentLibrary / etc.
    ├── [Center column] (flex 1)
    │   ├── Workspace
    │   │   ├── TabBar (35px, drag-reorder, middle-click close)
    │   │   └── TabContentView → FileEditor / WorkflowCanvas
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

A standalone preview is available at `layout-preview.html` (served on port 1421):

```
http://localhost:1421/
```

Opens with mock tabs, Chat sidebar, and Terminal panel to demonstrate the full VS Code layout.

## Key Decisions

- **VS Code over Obsidian**: proper Agent IDE with dark theme (#181818 activity bar, #252526 sidebars, #1e1e1e editor, #007acc status bar)
- **No Docker**: lightweight SPA + FastAPI, no containers
- **Right sidebar always visible**: Chat by default, Properties tab on node selection
- **Bottom panel inside center column**: only spans editor width, not across sidebars
- **Unified sidebar shell**: LeftSidebar/NodeSidebar accept children — old components render inside the same shell
- **Tab content from API**: sidebar loads real workflows from `GET /api/workflows/`, content from `GET /api/workflows/{id}/code`
- **contentStore**: in-memory Map for session-persistent tab content
- **ui-system.tsx**: shared UI primitives (IconButton, ToolbarButton, MenuButton, HeaderLabel, PanelHeader)

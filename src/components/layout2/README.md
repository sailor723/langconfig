# Layout2 — Obsidian-Style Agent IDE Shell

Refactoring the LangConfig UI from a top-nav web app layout to an Obsidian/VS Code-inspired IDE shell.

## Progress

### ✅ Phase 1: Layout Shell (Complete)

| Component | Status | Description |
|-----------|--------|-------------|
| `tokens.ts` | ✅ | Theme system mapping LangConfig → Obsidian tokens |
| `useLayout.tsx` | ✅ | Shared context for layout state (activity, sidebar, tabs, panels) |
| `ActivityBar.tsx` | ✅ | 48px left icon strip: Workflows, Agents, Library, Analysis, Settings |
| `LeftSidebar.tsx` | ✅ | Contextual file explorer per activity with tree view |
| `Workspace.tsx` | ✅ | Tab bar + content area (central editor) |
| `NodeSidebar.tsx` | ✅ | Right-side config panel (appears on node select) |
| `BottomPanel.tsx` | ✅ | Collapsible chat/logs/output panel |
| `StatusBar.tsx` | ✅ | Thin bottom bar: model, tokens, task status |

### ✅ Phase 2: File Explorer

| Feature | Status | Description |
|---------|--------|-------------|
| TreeView (folders/files) | ✅ | Recursive tree with expand/collapse |
| Right-click context menu | ✅ | Rename, Delete, New File/Folder |
| Inline rename | ✅ | Double-click or F2 |
| Quick file picker (Cmd+P) | ✅ | Fuzzy search across all sidebar items |

### 🔄 Phase 3: Tab Improvements (Next)

| Feature | Status | Expected |
|---------|--------|----------|
| Keyboard shortcuts | ⏳ | Ctrl+W close, Ctrl+Tab switch |
| Tab reorder (drag) | ⏳ | |
| Middle-click to close | ⏳ | |
| Open file from API | ✅ | Real content from backend |

### ⏳ Phase 4: Quick Actions

| Feature | Status |
|---------|--------|
| Command palette (Cmd+Shift+P) | ⏳ |
| Search across files (Cmd+Shift+F) | ⏳ |

### ⏳ Phase 5: Editor Enhancements

| Feature | Status |
|---------|--------|
| Monaco editor (instead of textarea) | ⏳ |
| Status bar: real token/model info | ⏳ |
| File icon themes | ⏳ |

## Architecture

```
App.tsx
└── LayoutProvider (useLayout.tsx)
    ├── ActivityBar (48px left)
    ├── [LeftSidebar (280px)]
    ├── Workspace (flex-1 center)
    │   ├── TabBar
    │   └── TabContentView → FileEditor / WorkflowEditor
    ├── [NodeSidebar (320px right)]
    ├── BottomPanel (collapsible)
    └── StatusBar (22px bottom)
```

## Key Decisions

- **Obsidian over VS Code**: minimal chrome (48px activity bar), ephemeral sidebars, content-first
- **No Docker**: lightweight SPA + FastAPI, no containers
- **Existing pages unchanged**: layout wraps the old Studio/Agents/Skills/etc. views
- **Tab content from API**: sidebar loads real workflows from `GET /api/workflows/`, content from `GET /api/workflows/{id}/code`
- **contentStore**: in-memory Map for session-persistent tab content

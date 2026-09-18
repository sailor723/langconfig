/**
 * useLayout — shared state for the VS Code-style layout shell.
 *
 * Owns the top-level UI state used across ActivityBar, Sidebar,
 * Workspace, BottomPanel, etc. so they all stay in sync.
 */
import { createContext, useContext, useState, useCallback, useMemo, useRef, type ReactNode } from 'react';

// ── Activity definitions ──────────────────────────────────
// Each icon in the ActivityBar represents a "mode" that changes
// what the LeftSidebar and/or Workspace show.

export type ActivityId =
  | 'vault'
  | 'deepagents'
  | 'agents'
  | 'workflows'
  | 'graph'
  | 'prompt'
  | 'tools'
  | 'skills'
  | 'knowledge'
  | 'analysis'
  | 'settings'
  | 'studio'
  | 'learning';

export interface ActivityDef {
  id: ActivityId;
  label: string;
  icon: string; // lucide icon name
  group: 'main' | 'bottom';
}

export const ACTIVITIES: ActivityDef[] = [
  { id: 'vault',      label: 'Vault',      icon: 'Archive',    group: 'main' },
  { id: 'deepagents', label: 'DeepAgents', icon: 'Brain',      group: 'main' },
  { id: 'agents',     label: 'Agents',     icon: 'Users',      group: 'main' },
  { id: 'workflows',  label: 'Workflows',  icon: 'GitBranch',  group: 'main' },
  { id: 'graph',      label: 'Graph',      icon: 'Workflow',   group: 'main' },
  { id: 'prompt',     label: 'Prompt',     icon: 'FileText',   group: 'main' },
  { id: 'tools',      label: 'Tools',      icon: 'Wrench',     group: 'main' },
  { id: 'skills',     label: 'Skills',     icon: 'Award',      group: 'main' },
  { id: 'knowledge',  label: 'Knowledge',  icon: 'Database',   group: 'main' },
  { id: 'analysis',   label: 'Analysis',   icon: 'BarChart3',  group: 'main' },
  { id: 'studio',     label: 'Studio',     icon: 'Network',    group: 'main' },
  { id: 'learning',   label: 'Learning',   icon: 'BookOpen',   group: 'main' },
  { id: 'settings',   label: 'Settings',   icon: 'Settings',   group: 'bottom' },
];

// ── Tab definitions ───────────────────────────────────────
// Workspace tabs represent open "documents".

export interface Tab {
  id: string;
  label: string;
  /** The view type rendered when this tab is active */
  viewType: string;
  /** Optional data passed to the view component */
  data?: any;
  dirty?: boolean;
  /**
   * Activity this tab belongs to. Used by App.tsx to close the previous
   * activity's tabs when the user switches activities in the ActivityBar.
   * Tabs without an `activity` (file/library/notebook/global tabs) are
   * preserved across activity switches.
   */
  activity?: ActivityId | 'global';
}

/**
 * Map a tab's viewType to its owning ActivityId. Tabs whose viewType
 * doesn't belong to any single activity (e.g. workflow editor, file
 * library, notebooks, analysis) return undefined — these are
 * "global" tabs that survive activity switches.
 *
 * Centralized here so the Workspace's VIEWS registry (which knows
 * every viewType) and App.tsx's close-on-switch logic share the same
 * mapping — adding a new activity only requires editing this table.
 */
export function viewTypeToActivity(viewType: string): ActivityId | undefined {
  switch (viewType) {
    // Workflow studio (global — keep across all activity switches)
    case 'workflow':
      return undefined;
    // LangGraph studio
    case 'graph':
      return 'graph';
    // DeepAgents
    case 'deepagent':
    case 'deepagent-create':
    case 'template-picker':
      // The picker is opened in direct mode by DeepAgents AND by Agents /
      // Skills / Prompt. We rely on the explicit `activity` field set by
      // the directModeTabFor helper in App.tsx — fall through here for
      // safety only.
      return 'deepagents';
    // Agents (regular)
    case 'agent':
      return 'agents';
    // Tools
    case 'tool-category':
    case 'tool-editor':
    case 'custom-tool-builder':
      return 'tools';
    // Skills
    case 'skill':
    case 'skill-editor':
      return 'skills';
    // Knowledge
    case 'knowledge-view':
      return 'knowledge';
    // Prompt
    case 'prompt-detail':
      return 'prompt';
    // Search providers (part of settings, not an activity)
    case 'search-provider-detail':
      return undefined;
    // Notebooks (Learning)
    case 'notebook':
    case 'analysis':
      return undefined;
    default:
      return undefined;
  }
}

// ── Layout context ────────────────────────────────────────

export interface LayoutState {
  // Activity
  activeActivity: ActivityId;
  setActiveActivity: (id: ActivityId) => void;

  // Left sidebar (VS Code "Side Bar")
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebarOpen: (v: boolean) => void;
  sidebarView: 'explorer' | 'search';
  setSidebarView: (v: 'explorer' | 'search') => void;
  sidebarWidth: number;
  setSidebarWidth: (w: number) => void;

  // Workspace tabs (VS Code "Editor Tabs")
  tabs: Tab[];
  activeTabId: string | null;
  openTab: (tab: Tab) => void;
  closeTab: (id: string) => void;
  /** Close every tab whose `activity` field is set and is NOT in `keep`.
   *  Tabs without an `activity` (file/library/notebook/global) are never
   *  closed by this call — they're preserved across activity switches.
   *  Used by App.tsx when the user clicks a different activity in the
   *  ActivityBar. */
  closeTabsByActivity: (keep: ActivityId | 'global') => void;
  setActiveTab: (id: string) => void;
  setTabDirty: (id: string, dirty: boolean) => void;
  moveTab: (fromIndex: number, toIndex: number) => void;

  // Right panel (VS Code "Panel" on right side — used for node config)
  rightPanelOpen: boolean;
  rightPanelContent: string | null;
  rightPanelWidth: number;
  rightPanelTab: 'chat' | 'doc-chat' | 'properties';
  setRightPanelWidth: (w: number) => void;
  openRightPanel: (content: string) => void;
  closeRightPanel: () => void;
  toggleRightPanel: () => void;
  setRightPanelTab: (tab: 'chat' | 'doc-chat' | 'properties') => void;

  // Bottom panel (VS Code "Panel" at bottom — terminal, chat, logs)
  bottomPanelOpen: boolean;
  toggleBottomPanel: () => void;
  setBottomPanelOpen: (open: boolean) => void;
}

const LayoutContext = createContext<LayoutState | null>(null);

export function useLayoutState(): LayoutState {
  const ctx = useContext(LayoutContext);
  if (!ctx) throw new Error('useLayoutState must be used inside <LayoutProvider>');
  return ctx;
}

export function LayoutProvider({ children }: { children: ReactNode }) {
  // Default to 'vault' (project anchor, sidebar hidden) — the app boots to the
  // create/select-project launcher, which must not show any browser chrome
  // (e.g. the workflow browser) before a project is opened.
  const [activeActivity, setActiveActivity] = useState<ActivityId>('vault');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [rightPanelContent, setRightPanelContent] = useState<string | null>(null);
  const [rightPanelWidth, setRightPanelWidth] = useState(360);
  const [rightPanelTab, setRightPanelTab] = useState<'chat' | 'doc-chat' | 'properties'>('chat');
  const [bottomPanelOpen, setBottomPanelOpen] = useState(false);

  const toggleSidebar = useCallback(() => setSidebarOpen(v => !v), []);
  const [sidebarView, setSidebarView] = useState<'explorer' | 'search'>('explorer');

  const openTab = useCallback((tab: Tab) => {
    // Auto-tag the tab with its owning activity (if any) so App.tsx's
    // close-on-switch logic works without every caller remembering to
    // pass `activity`. The explicit field wins; the viewType heuristic
    // is a fallback.
    const inferred = tab.activity ?? viewTypeToActivity(tab.viewType) ?? undefined;
    const normalized: Tab = inferred ? { ...tab, activity: inferred } : tab;

    setTabs(prev => {
      const exists = prev.find(t => t.id === normalized.id);
      if (exists) {
        return prev.map(t => t.id === normalized.id ? { ...t, ...normalized } : t);
      }
      return [...prev, normalized];
    });
    setActiveTabId(normalized.id);
  }, []);

  // Use a ref to track activeTabId so closeTab's functional updater always
  // reads the latest value, avoiding stale-closure bugs on rapid tab closes.
  const activeTabIdRef = useRef(activeTabId);
  activeTabIdRef.current = activeTabId;

  const closeTab = useCallback((id: string) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.id === id);
      const next = prev.filter(t => t.id !== id);
      const currentActive = activeTabIdRef.current;
      if (id === currentActive && next.length > 0) {
        const newIdx = Math.min(idx, next.length - 1);
        setActiveTabId(next[newIdx].id);
      } else if (next.length === 0) {
        setActiveTabId(null);
      }
      return next;
    });
  }, []);

  /**
   * Close every tab whose `activity` is set AND not equal to `keep`. Tabs
   * without an `activity` field are preserved (file/library/global tabs).
   * If closing the active tab empties the tab list, `activeTabId` becomes
   * null (Workspace falls back to the route's default content).
   */
  const closeTabsByActivity = useCallback((keep: ActivityId | 'global') => {
    setTabs(prev => {
      const next = prev.filter(t => !t.activity || t.activity === keep);
      if (next.length !== prev.length) {
        const stillActive = next.some(t => t.id === activeTabIdRef.current);
        if (!stillActive) {
          setActiveTabId(next.length > 0 ? next[next.length - 1].id : null);
        }
      }
      return next;
    });
  }, []);

  const setActiveTab = useCallback((id: string) => {
    setActiveTabId(id);
  }, []);

  const setTabDirty = useCallback((id: string, dirty: boolean) => {
    setTabs(prev => prev.map(t => t.id === id ? { ...t, dirty } : t));
  }, []);

  const moveTab = useCallback((fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex) return;
    setTabs(prev => {
      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  }, []);

  const openRightPanel = useCallback((content: string) => {
    setRightPanelContent(content);
    setRightPanelOpen(true);
  }, []);

  const closeRightPanel = useCallback(() => {
    setRightPanelOpen(false);
    setRightPanelContent(null);
  }, []);

  const toggleRightPanel = useCallback(() => {
    setRightPanelOpen(v => !v);
  }, []);

  const toggleBottomPanel = useCallback(() => setBottomPanelOpen(v => !v), []);

  const state = useMemo<LayoutState>(() => ({
    activeActivity,
    setActiveActivity,
    sidebarOpen,
    toggleSidebar,
    setSidebarOpen,
    sidebarView,
    setSidebarView,
    sidebarWidth,
    setSidebarWidth,
    tabs,
    activeTabId,
    openTab,
    closeTab,
    closeTabsByActivity,
    setActiveTab,
    setTabDirty,
    moveTab,
    rightPanelOpen,
    rightPanelContent,
    rightPanelWidth,
    rightPanelTab,
    setRightPanelWidth,
    openRightPanel,
    closeRightPanel,
    toggleRightPanel,
    setRightPanelTab,
    bottomPanelOpen,
    toggleBottomPanel,
    setBottomPanelOpen,
  }), [
    activeActivity, sidebarOpen, sidebarView, sidebarWidth, tabs, activeTabId,
    rightPanelOpen, rightPanelContent, rightPanelWidth, rightPanelTab, bottomPanelOpen,
  ]);

  return (
    <LayoutContext.Provider value={state}>
      {children}
    </LayoutContext.Provider>
  );
}

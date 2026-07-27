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
  | 'workflows'
  | 'agents'
  | 'deepagents'
  | 'library'
  | 'analysis'
  | 'settings'
  | 'studio'
  | 'models'
  | 'search';

export interface ActivityDef {
  id: ActivityId;
  label: string;
  icon: string; // lucide icon name
}

export const ACTIVITIES: ActivityDef[] = [
  { id: 'workflows',  label: 'Workflows',  icon: 'GitBranch' },
  { id: 'deepagents', label: 'DeepAgents', icon: 'Brain' },
  { id: 'agents',     label: 'Agents',     icon: 'Users' },
  { id: 'models',     label: 'Models',     icon: 'Sparkles' },
  { id: 'search',     label: 'Search',     icon: 'Search' },
  { id: 'library',    label: 'Library',    icon: 'BookOpen' },
  { id: 'analysis',   label: 'Analysis',   icon: 'BarChart3' },
  { id: 'studio',     label: 'Studio',     icon: 'Network' },
  { id: 'settings',   label: 'Settings',   icon: 'Settings' },
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
  setActiveTab: (id: string) => void;
  setTabDirty: (id: string, dirty: boolean) => void;
  moveTab: (fromIndex: number, toIndex: number) => void;

  // Right panel (VS Code "Panel" on right side — used for node config)
  rightPanelOpen: boolean;
  rightPanelContent: string | null;
  rightPanelWidth: number;
  setRightPanelWidth: (w: number) => void;
  openRightPanel: (content: string) => void;
  closeRightPanel: () => void;

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
  const [activeActivity, setActiveActivity] = useState<ActivityId>('workflows');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarWidth, setSidebarWidth] = useState(260);
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [rightPanelContent, setRightPanelContent] = useState<string | null>(null);
  const [rightPanelWidth, setRightPanelWidth] = useState(360);
  const [bottomPanelOpen, setBottomPanelOpen] = useState(false);

  const toggleSidebar = useCallback(() => setSidebarOpen(v => !v), []);
  const [sidebarView, setSidebarView] = useState<'explorer' | 'search'>('explorer');

  const openTab = useCallback((tab: Tab) => {
    setTabs(prev => {
      const exists = prev.find(t => t.id === tab.id);
      if (exists) {
        return prev.map(t => t.id === tab.id ? { ...t, ...tab } : t);
      }
      return [...prev, tab];
    });
    setActiveTabId(tab.id);
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
    setActiveTab,
    setTabDirty,
    moveTab,
    rightPanelOpen,
    rightPanelContent,
    rightPanelWidth,
    setRightPanelWidth,
    openRightPanel,
    closeRightPanel,
    bottomPanelOpen,
    toggleBottomPanel,
    setBottomPanelOpen,
  }), [
    activeActivity, sidebarOpen, sidebarView, sidebarWidth, tabs, activeTabId,
    rightPanelOpen, rightPanelContent, rightPanelWidth, bottomPanelOpen,
  ]);

  return (
    <LayoutContext.Provider value={state}>
      {children}
    </LayoutContext.Provider>
  );
}

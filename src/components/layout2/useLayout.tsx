/**
 * useLayout — shared state for the Obsidian-style layout shell.
 *
 * Owns the top-level UI state used across ActivityBar, Sidebar,
 * Workspace, BottomPanel, etc. so they all stay in sync.
 */
import { createContext, useContext, useState, useCallback, useMemo, type ReactNode } from 'react';

// ── Activity definitions ──────────────────────────────────
// Each icon in the ActivityBar represents a "mode" that changes
// what the LeftSidebar and/or Workspace show.

export type ActivityId =
  | 'workflows'
  | 'agents'
  | 'library'
  | 'analysis'
  | 'settings';

export interface ActivityDef {
  id: ActivityId;
  label: string;
  icon: string; // lucide icon name
}

export const ACTIVITIES: ActivityDef[] = [
  { id: 'workflows', label: 'Workflows', icon: 'GitBranch' },
  { id: 'agents',    label: 'Agents',    icon: 'Brain' },
  { id: 'library',   label: 'Library',   icon: 'BookOpen' },
  { id: 'analysis',  label: 'Analysis',  icon: 'BarChart3' },
  { id: 'settings',  label: 'Settings',  icon: 'Settings' },
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

  // Left sidebar
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;

  // Workspace tabs
  tabs: Tab[];
  activeTabId: string | null;
  openTab: (tab: Tab) => void;
  closeTab: (id: string) => void;
  setActiveTab: (id: string) => void;

  // Right panel (node config)
  rightPanelOpen: boolean;
  rightPanelContent: string | null;
  openRightPanel: (content: string) => void;
  closeRightPanel: () => void;

  // Bottom panel
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
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [rightPanelOpen, setRightPanelOpen] = useState(false);
  const [rightPanelContent, setRightPanelContent] = useState<string | null>(null);
  const [bottomPanelOpen, setBottomPanelOpen] = useState(false);

  const toggleSidebar = useCallback(() => setSidebarOpen(v => !v), []);

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

  const closeTab = useCallback((id: string) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.id === id);
      const next = prev.filter(t => t.id !== id);
      if (id === activeTabId && next.length > 0) {
        const newIdx = Math.min(idx, next.length - 1);
        setActiveTabId(next[newIdx].id);
      } else if (next.length === 0) {
        setActiveTabId(null);
      }
      return next;
    });
  }, [activeTabId]);

  const setActiveTab = useCallback((id: string) => {
    setActiveTabId(id);
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
    tabs,
    activeTabId,
    openTab,
    closeTab,
    setActiveTab,
    rightPanelOpen,
    rightPanelContent,
    openRightPanel,
    closeRightPanel,
    bottomPanelOpen,
    toggleBottomPanel,
    setBottomPanelOpen,
  }), [
    activeActivity, sidebarOpen, tabs, activeTabId,
    rightPanelOpen, rightPanelContent, bottomPanelOpen,
  ]);

  return (
    <LayoutContext.Provider value={state}>
      {children}
    </LayoutContext.Provider>
  );
}

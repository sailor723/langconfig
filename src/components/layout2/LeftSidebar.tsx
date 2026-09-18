/**
 * LeftSidebar — VS Code-style side bar (Explorer / Search).
 *
 * VS Code pattern:
 *   - 260px default, resizable
 *   - Title bar: uppercase label with action icons
 *   - Tree view below
 *   - Status bar at bottom showing item count
 */
import { type ReactNode, Children, useCallback, useRef, useState } from 'react';
import { useLayoutState, ACTIVITIES } from './useLayout';
import { useLayoutTokens } from './tokens';
import TreeView, { type TreeNode } from './TreeView';
import { useSidebarData } from './useSidebarData';
import { IconButton } from './ui-system';
import SearchPanel from './SearchPanel';
import apiClient from '../../lib/api-client';
import { Plus, RefreshCw, Search, Loader } from 'lucide-react';
import ToolBrowserSidebar from './ToolBrowserSidebar';
import KnowledgeSidebar from './KnowledgeSidebar';
import SkillBrowserSidebar from './SkillBrowserSidebar';
import NotebookSidebar from './NotebookSidebar';
import PromptBrowserSidebar from './PromptBrowserSidebar';

interface LeftSidebarProps {
  children?: ReactNode;
}

const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 600;
const SIDEBAR_DEFAULT_WIDTH = 260;

export default function LeftSidebar({ children }: LeftSidebarProps) {
  const { activeActivity, sidebarOpen, sidebarView, setSidebarView, openTab, sidebarWidth, setSidebarWidth } = useLayoutState();
  const { nodes, loading, error, getNodeContent, saveNodeContent, reload } = useSidebarData(activeActivity);
  const t = useLayoutTokens();
  const [treeKey, setTreeKey] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');

  const isSearch = sidebarView === 'search';

  // Resize drag — VS Code-style: drag the divider to resize. The drag listeners
  // are attached to `document` so the resize keeps following the cursor even
  // when it briefly leaves the thin handle element. A separate `dragging` state
  // drives the visible "active" color of the handle (matching VS Code's
  // highlighted-divider behavior). Double-click resets to default width.
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = { startX: e.clientX, startWidth: sidebarWidth };
    setIsDragging(true);

    const handleMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = ev.clientX - dragRef.current.startX;
      const next = Math.max(
        SIDEBAR_MIN_WIDTH,
        Math.min(SIDEBAR_MAX_WIDTH, dragRef.current.startWidth + dx),
      );
      setSidebarWidth(next);
    };
    const handleUp = () => {
      dragRef.current = null;
      setIsDragging(false);
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    document.body.style.cursor = 'ew-resize';
    document.body.style.userSelect = 'none';
  }, [sidebarWidth, setSidebarWidth]);

  const handleResizeReset = useCallback(() => {
    setSidebarWidth(SIDEBAR_DEFAULT_WIDTH);
  }, [setSidebarWidth]);

  // ── Callbacks (must be before early return — React hook ordering) ──
  const handleFileOpen = useCallback(async (node: TreeNode) => {
    if (node.children || node.viewType === 'empty') return;
    let content = '';
    try { content = await getNodeContent(node); } catch {}
    openTab({
      id: node.id,
      label: node.label,
      viewType: node.viewType ?? activeActivity,
      // Keep the node reference in the save callback — editors call onSave(id, content)
      data: { ...node.data, content, onSave: (id: string, c: string) => saveNodeContent(node, c) },
    });
  }, [activeActivity, openTab, getNodeContent, saveNodeContent]);

  /** Edit button on agent/deepagent tree rows: open the editor with the FULL
   * agent record fetched fresh from the API, so Save persists every field. */
  const handleNodeEdit = useCallback(async (node: TreeNode) => {
    if (node.children || node.viewType === 'empty') return;
    const agentId = node.data?.agentId ?? node.data?.id;
    if (typeof agentId !== 'number') {
      handleFileOpen(node);
      return;
    }
    try {
      const res: any = await apiClient.getDeepAgent(agentId);
      const full = (res as any)?.data ?? res;
      openTab({
        id: `edit-${node.id}`,
        label: `✏️ ${node.label}`,
        viewType: node.viewType ?? activeActivity,
        data: full,
      });
    } catch (err: any) {
      console.error('Failed to load full agent for editing:', err);
      handleFileOpen(node);
    }
  }, [activeActivity, openTab, handleFileOpen]);

  const handleNewFile = useCallback(() => {
    const id = `new-${Date.now()}`;
    if (activeActivity === 'deepagents') {
      openTab({ id, label: 'New DeepAgent', viewType: 'deepagent-create', data: {} });
    } else if (activeActivity === 'agents') {
      openTab({ id, label: 'New Agent', viewType: 'agent', data: { new: true } });
    } else {
      openTab({ id, label: 'Untitled', viewType: activeActivity, data: { new: true } });
    }
  }, [activeActivity, openTab]);

  const handleNewFolder = useCallback(() => setTreeKey(v => v + 1), []);
  const handleRefresh = useCallback(() => {
    reload();
    setTreeKey(v => v + 1);
  }, [reload]);
  const handleFolderAction = useCallback((node: TreeNode) => {
    if (node.id === 'folder-deepagents') {
      openTab({ id: `new-${Date.now()}`, label: 'New DeepAgent', viewType: 'deepagent-create', data: {} });
    } else if (node.id === 'folder-agents') {
      openTab({ id: `new-${Date.now()}`, label: 'New Agent', viewType: 'agent', data: { new: true } });
    }
  }, [openTab]);

  // ── Computed values ──
  // Client-side filtering for deepagents/agents browser
  const filteredNodes = (activeActivity === 'deepagents' || activeActivity === 'agents') && searchQuery.trim()
    ? nodes.map(n => {
        if (n.id === 'folder-deepagents' && n.children) {
          return { ...n, children: n.children.filter(c =>
            c.label.toLowerCase().includes(searchQuery.toLowerCase())
          )};
        }
        if (n.id === 'folder-agents' && n.children) {
          return { ...n, children: n.children.filter(c =>
            c.label.toLowerCase().includes(searchQuery.toLowerCase())
          )};
        }
        return n;
      })
    : nodes;

  // Count rendered rows (respects the search filter; skips empty-* placeholders
  // so tools/prompt/skills don't show a fake "1 item")
  const countItems = (items: TreeNode[]): number => {
    let count = 0;
    for (const item of items) {
      if (item.id.startsWith('empty-')) continue;
      if (!item.children) count++;
      if (item.children) count += countItems(item.children);
    }
    return count;
  };
  const totalItems = filteredNodes ? countItems(filteredNodes) : 0;

  if (!sidebarOpen || activeActivity === 'settings' || activeActivity === 'vault') return null;

  return (
    <div style={{ display: 'flex', flexShrink: 0 }}>
      <div
        style={{
          width: sidebarWidth,
          minWidth: sidebarWidth,
          background: t.bgSidebar,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          userSelect: 'none',
        }}
      >
        {/* ── Title bar (VS Code "EXPLORER" style) ──────── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            height: 35,
            padding: '0 10px',
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: 0.3,
            textTransform: 'uppercase',
            color: '#bbb',
          }}
        >
          <span>
            {isSearch ? 'Search' : (ACTIVITIES.find(a => a.id === activeActivity)?.label ?? '')}
          </span>

          <div style={{ display: 'flex', gap: 2 }}>
            <IconButton
              onClick={() => setSidebarView(isSearch ? 'explorer' : 'search')}
              title={isSearch ? 'Close search' : 'Search in files'}
              t={t}
              style={isSearch ? { color: t.accent } : undefined}
            >
              <Search size={14} />
            </IconButton>
            {!isSearch && (
              <IconButton onClick={handleRefresh} title="Refresh" t={t}>
                <RefreshCw size={14} />
              </IconButton>
            )}
          </div>
        </div>

        {/* ── Content ──────────────────────────────────── */}
        <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
          {isSearch ? (
            <SearchPanel onClose={() => setSidebarView('explorer')} />
          ) : Children.toArray(children).length > 0 ? (
            <div style={{ height: '100%', overflow: 'auto' }}>{children}</div>
          ) : activeActivity === 'tools' ? (
            /* Tools activity renders the dedicated ToolBrowserSidebar */
            <ToolBrowserSidebar />
          ) : activeActivity === 'prompt' ? (
            /* Prompt activity renders the dedicated PromptBrowserSidebar */
            <PromptBrowserSidebar />
          ) : activeActivity === 'knowledge' ? (
            /* Knowledge activity renders the dedicated KnowledgeSidebar */
            <KnowledgeSidebar />
          ) : activeActivity === 'skills' ? (
            /* Skills activity renders the dedicated SkillBrowserSidebar */
            <SkillBrowserSidebar />
          ) : activeActivity === 'learning' ? (
            /* Learning activity renders the notebook browser sidebar */
            <NotebookSidebar />
          ) : loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
              <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
              Loading...
            </div>
          ) : error ? (
            <div style={{ padding: '16px 20px', fontSize: 13, color: '#e5484d' }}>{error}</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
                 <TreeView
                 key={treeKey}
                 nodes={filteredNodes}
                onFileOpen={handleFileOpen}
                onNewFile={handleNewFile}
                onFolderAction={handleFolderAction}
                onFolderRefresh={handleRefresh}
                onNodeEdit={handleNodeEdit}
                folderSearchValue={activeActivity === 'deepagents' || activeActivity === 'agents' ? searchQuery : undefined}
                onFolderSearchChange={activeActivity === 'deepagents' || activeActivity === 'agents' ? setSearchQuery : undefined}
              />
              </div>
            </div>
          )}
        </div>

        {/* ── Status bar ───────────────────────────────── */}
        {!children && (
          <div
            style={{
              height: 22,
              padding: '0 10px',
              color: '#858585',
              fontSize: 11,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              flexShrink: 0,
            }}
          >
            <span>{totalItems} {totalItems === 1 ? 'item' : 'items'}</span>
          </div>
        )}
      </div>

      {/* Resize handle — VS Code-style: 8px hit area wrapping a 1px visible
          divider line. The line is always subtly visible (so users know
          the divider exists), brightens on hover, and turns accent-blue
          while dragging. Double-click resets to the default width. */}
      <div
        onMouseDown={handleResizeStart}
        onDoubleClick={handleResizeReset}
        title="Drag to resize — double-click to reset"
        style={{
          width: 8,
          cursor: 'ew-resize',
          background: 'transparent',
          flexShrink: 0,
          position: 'relative',
          display: 'flex',
          alignItems: 'stretch',
          justifyContent: 'center',
        }}
        onMouseEnter={(e) => {
          // Brighten the inner line on hover via the data attribute so the
          // CSS transition (defined inline below) animates smoothly.
          const line = e.currentTarget.firstElementChild as HTMLElement | null;
          if (line && !isDragging) line.style.background = t.accent;
        }}
        onMouseLeave={(e) => {
          const line = e.currentTarget.firstElementChild as HTMLElement | null;
          if (line && !isDragging) line.style.background = t.border;
        }}
      >
        <div
          style={{
            width: 1,
            background: isDragging ? t.accent : t.border,
            transition: 'background 120ms ease',
          }}
        />
      </div>
    </div>
  );
}

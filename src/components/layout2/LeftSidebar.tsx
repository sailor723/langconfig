/**
 * LeftSidebar — VS Code-style side bar (Explorer / Search).
 *
 * VS Code pattern:
 *   - 260px default, resizable
 *   - Title bar: uppercase label with action icons
 *   - Tree view below
 *   - Status bar at bottom showing item count
 */
import { type ReactNode, useCallback, useRef, useState } from 'react';
import { useLayoutState, ACTIVITIES, type Tab } from './useLayout';
import { useLayoutTokens } from './tokens';
import TreeView, { type TreeNode } from './TreeView';
import { useSidebarData } from './useSidebarData';
import { IconButton } from './ui-system';
import SearchPanel from './SearchPanel';
import { Plus, FolderPlus, RefreshCw, Search, Loader } from 'lucide-react';

interface LeftSidebarProps {
  children?: ReactNode;
}

const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 600;

export default function LeftSidebar({ children }: LeftSidebarProps) {
  const { activeActivity, sidebarOpen, sidebarView, setSidebarView, openTab, sidebarWidth, setSidebarWidth } = useLayoutState();
  const { nodes, loading, error, getNodeContent, saveNodeContent } = useSidebarData(activeActivity);
  const t = useLayoutTokens();
  const [treeKey, setTreeKey] = useState(0);

  const isSearch = sidebarView === 'search';

  // Resize drag
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = { startX: e.clientX, startWidth: sidebarWidth };
    const handleMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = ev.clientX - dragRef.current.startX;
      const next = Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, dragRef.current.startWidth + dx));
      setSidebarWidth(next);
    };
    const handleUp = () => {
      dragRef.current = null;
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

  if (!sidebarOpen || activeActivity === 'settings') return null;

  const handleFileOpen = useCallback(async (node: TreeNode) => {
    if (node.children || node.viewType === 'empty') return;
    let content = '';
    try { content = await getNodeContent(node); } catch {}
    // For deep agents, node.data.agent should now be populated by getNodeContent.
    // Build the tab and re-open it so React re-renders the editor with fresh data.
    const tab: Tab = {
      id: node.id,
      label: node.label,
      viewType: node.viewType ?? activeActivity,
      data: { ...node.data, content, onSave: saveNodeContent },
    };
    openTab(tab);
    // For deep agent, openTab again on next tick so the editor sees the latest node.data.agent
    if (node.viewType === 'deepagent') {
      setTimeout(() => {
        openTab({
          ...tab,
          data: { ...node.data, content, onSave: saveNodeContent },
        });
      }, 0);
    }
  }, [activeActivity, openTab, getNodeContent, saveNodeContent]);

  const handleNewFile = useCallback(() => {
    const id = `new-${Date.now()}`;
    // For deepagents activity, open the creator form
    if (activeActivity === 'deepagents') {
      openTab({
        id,
        label: 'New DeepAgent',
        viewType: 'deepagent-create',
        data: {},
      });
    } else {
      openTab({ id, label: 'Untitled', viewType: activeActivity, data: { new: true } });
    }
  }, [activeActivity, openTab]);

  const handleNewFolder = useCallback(() => setTreeKey(v => v + 1), []);
  const handleRefresh = useCallback(() => setTreeKey(v => v + 1), []);

  const countItems = (items: TreeNode[]): number => {
    let count = 0;
    for (const item of items) {
      if (!item.children) count++;
      if (item.children) count += countItems(item.children);
    }
    return count;
  };
  const totalItems = nodes ? countItems(nodes) : 0;

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
              <Search size={13} />
            </IconButton>
            {!isSearch && (
              <>
                <IconButton onClick={handleNewFile} title="New file" t={t}>
                  <Plus size={13} />
                </IconButton>
                <IconButton onClick={handleRefresh} title="Refresh" t={t}>
                  <RefreshCw size={13} />
                </IconButton>
              </>
            )}
          </div>
        </div>

        {/* ── Content ──────────────────────────────────── */}
        <div style={{ flex: 1, overflow: 'hidden', minHeight: 0 }}>
          {isSearch ? (
            <SearchPanel onClose={() => setSidebarView('explorer')} />
          ) : children ? (
            <div style={{ height: '100%', overflow: 'auto' }}>{children}</div>
          ) : loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
              <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
              Loading...
            </div>
          ) : error ? (
            <div style={{ padding: '16px 20px', fontSize: 13, color: '#e5484d' }}>{error}</div>
          ) : (
            <div style={{ overflowY: 'auto', height: '100%' }}>
              <TreeView key={treeKey} nodes={nodes} onFileOpen={handleFileOpen} onNewFile={handleNewFile} />
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

      {/* Resize handle */}
      <div
        onMouseDown={handleResizeStart}
        title="Drag to resize"
        style={{
          width: 4,
          cursor: 'ew-resize',
          background: 'transparent',
          flexShrink: 0,
        }}
        onMouseEnter={e => { e.currentTarget.style.background = t.border; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      />
    </div>
  );
}

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
import { useLayoutState, ACTIVITIES } from './useLayout';
import { useLayoutTokens } from './tokens';
import TreeView, { type TreeNode } from './TreeView';
import { useSidebarData } from './useSidebarData';
import { IconButton } from './ui-system';
import SearchPanel from './SearchPanel';
import { Plus, RefreshCw, Search, Loader } from 'lucide-react';
import ModelCardsSidebar from './ModelCardsSidebar';
import SearchProvidersSidebar from './SearchProvidersSidebar';
import ToolBrowserSidebar from './ToolBrowserSidebar';
import KnowledgeSidebar from './KnowledgeSidebar';
import SkillBrowserSidebar from './SkillBrowserSidebar';
import PromptBrowserSidebar from './PromptBrowserSidebar';

interface LeftSidebarProps {
  children?: ReactNode;
}

const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 600;

export default function LeftSidebar({ children }: LeftSidebarProps) {
  const { activeActivity, sidebarOpen, sidebarView, setSidebarView, openTab, sidebarWidth, setSidebarWidth } = useLayoutState();
  const { nodes, loading, error, getNodeContent, saveNodeContent, reload } = useSidebarData(activeActivity);
  const t = useLayoutTokens();
  const [treeKey, setTreeKey] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');

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

  // ── Callbacks (must be before early return — React hook ordering) ──
  const handleFileOpen = useCallback(async (node: TreeNode) => {
    if (node.children || node.viewType === 'empty') return;
    let content = '';
    try { content = await getNodeContent(node); } catch {}
    openTab({
      id: node.id,
      label: node.label,
      viewType: node.viewType ?? activeActivity,
      data: { ...node.data, content, onSave: saveNodeContent },
    });
  }, [activeActivity, openTab, getNodeContent, saveNodeContent]);

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
  const countItems = (items: TreeNode[]): number => {
    let count = 0;
    for (const item of items) {
      if (!item.children) count++;
      if (item.children) count += countItems(item.children);
    }
    return count;
  };
  const totalItems = nodes ? countItems(nodes) : 0;

  // Client-side filtering for deepagents browser
  const filteredNodes = activeActivity === 'deepagents' && searchQuery.trim()
    ? nodes.map(n => n.id === 'folder-deepagents' && n.children
        ? { ...n, children: n.children.filter(c =>
            c.label.toLowerCase().includes(searchQuery.toLowerCase())
          )}
        : n
      )
    : nodes;

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
            {!isSearch && activeActivity !== 'models' && (
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
          ) : children ? (
            <div style={{ height: '100%', overflow: 'auto' }}>{children}</div>
          ) : activeActivity === 'models' ? (
            /* Models activity renders the dedicated ModelCardsSidebar */
            <ModelCardsSidebar />
          ) : activeActivity === 'search' ? (
            /* Search activity renders the dedicated SearchProvidersSidebar */
            <SearchProvidersSidebar />
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
                folderSearchValue={activeActivity === 'deepagents' ? searchQuery : undefined}
                onFolderSearchChange={activeActivity === 'deepagents' ? setSearchQuery : undefined}
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

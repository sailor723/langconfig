/**
 * LeftSidebar — contextual file explorer panel.
 *
 * Obsidian/VS Code-style file tree with:
 * - Real data from backend API (workflows, agents, skills, etc.)
 * - Folder expand/collapse
 * - Click file → opens as tab with real content
 * - Header actions: new file, refresh
 */
import { useCallback, useState } from 'react';
import { useLayoutState, ACTIVITIES, type Tab, type ActivityId } from './useLayout';
import { useLayoutTokens } from './tokens';
import TreeView, { type TreeNode } from './TreeView';
import { useSidebarData } from './useSidebarData';
import { Plus, FolderPlus, RefreshCw, Loader } from 'lucide-react';

export default function LeftSidebar() {
  const { activeActivity, sidebarOpen, openTab } = useLayoutState();
  const { nodes, loading, error, getNodeContent, saveNodeContent } = useSidebarData(activeActivity);
  const t = useLayoutTokens();
  const [treeKey, setTreeKey] = useState(0);

  if (!sidebarOpen || activeActivity === 'settings') return null;

  const handleFileOpen = useCallback(async (node: TreeNode) => {
    // Skip folder nodes and empty placeholders
    if (node.children || node.viewType === 'empty') return;

    // Try to load real content from the API
    let content = '';
    try {
      content = await getNodeContent(node);
    } catch {
      // Content not available — open with empty editor
    }

    const tab: Tab = {
      id: node.id,
      label: node.label,
      viewType: node.viewType ?? activeActivity,
      data: { ...node.data, content, onSave: saveNodeContent },
    };
    openTab(tab);
  }, [activeActivity, openTab, getNodeContent, saveNodeContent]);

  const handleNewFile = useCallback(() => {
    const id = `new-${Date.now()}`;
    const tab: Tab = {
      id,
      label: 'Untitled',
      viewType: activeActivity,
      data: { new: true },
    };
    openTab(tab);
  }, [activeActivity, openTab]);

  const handleRefresh = useCallback(() => {
    setTreeKey(v => v + 1);
  }, []);

  return (
    <div
      style={{
        width: 280,
        minWidth: 280,
        background: t.bgBase,
        borderRight: `1px solid ${t.border}`,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        userSelect: 'none',
      }}
    >
      {/* ── Header ─────────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: `1px solid ${t.border}`,
          minHeight: 36,
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: t.textMuted }}>
          {ACTIVITIES.find(a => a.id === activeActivity)?.label}
        </span>

        <div style={{ display: 'flex', gap: 2 }}>
          <HeaderButton title="New file" onClick={handleNewFile} t={t}>
            <Plus size={14} />
          </HeaderButton>
          <HeaderButton title="New folder" onClick={handleRefresh} t={t}>
            <FolderPlus size={14} />
          </HeaderButton>
          <HeaderButton title="Refresh" onClick={handleRefresh} t={t}>
            <RefreshCw size={14} />
          </HeaderButton>
        </div>
      </div>

      {/* ── Tree or loading ─────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', paddingTop: 4 }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading...
          </div>
        ) : error ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: '#e5484d' }}>
            {error}
          </div>
        ) : (
          <TreeView key={treeKey} nodes={nodes} onFileOpen={handleFileOpen} onNewFile={handleNewFile} />
        )}
      </div>
    </div>
  );
}

function HeaderButton({ title, onClick, children, t }: {
  title: string; onClick: () => void; children: React.ReactNode;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{ width: 26, height: 26, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: 4, color: t.textMuted, cursor: 'pointer' }}
      onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
    >
      {children}
    </button>
  );
}

/**
 * LeftSidebar — contextual file explorer panel.
 *
 * Acts like Obsidian's file explorer / VS Code's explorer:
 * - Tree view with folders (expand/collapse) and files
 * - Click file → opens as tab in central Workspace
 * - Header actions: new folder, new file, refresh
 */
import { useState, useCallback } from 'react';
import { useLayoutState, ACTIVITIES, type ActivityId, type Tab } from './useLayout';
import { useLayoutTokens } from './tokens';
import TreeView, { type TreeNode } from './TreeView';
import { Plus, FolderPlus, RefreshCw } from 'lucide-react';

// ── Tree data per activity ───────────────────────────────

function buildTreeData(activity: ActivityId): TreeNode[] {
  switch (activity) {
    case 'workflows':
      return [
        {
          id: 'folder-workflows', label: 'My Workflows', children: [
            { id: 'wf-1', label: 'Sales Bot', viewType: 'workflow' },
            { id: 'wf-2', label: 'Support Agent', viewType: 'workflow' },
            { id: 'wf-3', label: 'Data Pipeline', viewType: 'workflow' },
          ],
        },
        {
          id: 'folder-templates', label: 'Templates', children: [
            { id: 'tpl-1', label: 'Blank Workflow', viewType: 'workflow' },
            { id: 'tpl-2', label: 'Chat Agent', viewType: 'workflow' },
            { id: 'tpl-3', label: 'RAG Pipeline', viewType: 'workflow' },
          ],
        },
      ];

    case 'agents':
      return [
        {
          id: 'folder-agents', label: 'My Agents', children: [
            { id: 'ag-1', label: 'SQL Analyst', viewType: 'agent' },
            { id: 'ag-2', label: 'Deep Researcher', viewType: 'agent' },
            { id: 'ag-3', label: 'Code Assistant', viewType: 'agent' },
          ],
        },
        {
          id: 'folder-loadouts', label: 'Loadouts', children: [
            { id: 'lo-1', label: 'Default', viewType: 'agent', badge: 'active' },
            { id: 'lo-2', label: 'Fast Mode', viewType: 'agent' },
            { id: 'lo-3', label: 'Full Analysis', viewType: 'agent' },
          ],
        },
      ];

    case 'library':
      return [
        {
          id: 'folder-skills', label: 'Skills', children: [
            { id: 'sk-1', label: 'sql-analyst', viewType: 'library' },
            { id: 'sk-2', label: 'data-visualizer', viewType: 'library' },
            { id: 'sk-3', label: 'web-scraper', viewType: 'library' },
          ],
        },
        {
          id: 'folder-tools', label: 'Tools', children: [
            { id: 'tl-1', label: 'sqlite-execute', viewType: 'library' },
            { id: 'tl-2', label: 'python-execute', viewType: 'library' },
            { id: 'tl-3', label: 'web-fetch', viewType: 'library' },
          ],
        },
        {
          id: 'folder-prompts', label: 'Prompts', children: [
            { id: 'pr-1', label: 'System Prompt Base', viewType: 'library' },
          ],
        },
      ];

    case 'analysis':
      return [
        {
          id: 'folder-dashboards', label: 'Dashboards', children: [
            { id: 'db-1', label: 'Sunhing KPI Dashboard', viewType: 'analysis' },
            { id: 'db-2', label: 'Sales Overview', viewType: 'analysis' },
          ],
        },
        {
          id: 'folder-datasources', label: 'Data Sources', children: [
            { id: 'ds-1', label: 'sunhing_kpi.db', viewType: 'analysis' },
            { id: 'ds-2', label: 'erp_data.db', viewType: 'analysis' },
          ],
        },
      ];

    case 'settings':
      return [];
  }
}

// ── Component ────────────────────────────────────────────

export default function LeftSidebar() {
  const { activeActivity, sidebarOpen, openTab } = useLayoutState();
  const t = useLayoutTokens();
  const [treeKey, setTreeKey] = useState(0); // for refresh

  if (!sidebarOpen || activeActivity === 'settings') return null;

  const treeData = buildTreeData(activeActivity);

  const handleFileOpen = useCallback((node: TreeNode) => {
    const tab: Tab = {
      id: node.id,
      label: node.label,
      viewType: node.viewType ?? activeActivity,
      data: { id: node.id },
    };
    openTab(tab);
  }, [activeActivity, openTab]);

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

  const handleNewFolder = useCallback(() => {
    // For now, just trigger a refresh to show placeholder
    // Real implementation would prompt for folder name and persist
    setTreeKey(v => v + 1);
  }, []);

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
          {/* New file */}
          <HeaderButton
            title="New file"
            onClick={handleNewFile}
            t={t}
          >
            <Plus size={14} />
          </HeaderButton>

          {/* New folder */}
          <HeaderButton
            title="New folder"
            onClick={handleNewFolder}
            t={t}
          >
            <FolderPlus size={14} />
          </HeaderButton>

          {/* Refresh */}
          <HeaderButton
            title="Refresh"
            onClick={handleRefresh}
            t={t}
          >
            <RefreshCw size={14} />
          </HeaderButton>
        </div>
      </div>

      {/* ── Tree ──────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', paddingTop: 4 }}>
        <TreeView
          key={treeKey}
          nodes={treeData}
          onFileOpen={handleFileOpen}
        />
      </div>
    </div>
  );
}

// Small icon button in the header
function HeaderButton({ title, onClick, children, t }: { title: string; onClick: () => void; children: React.ReactNode; t: ReturnType<typeof useLayoutTokens> }) {
  return (
    <button
      title={title}
      onClick={onClick}
      style={{
        width: 26,
        height: 26,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'transparent',
        border: 'none',
        borderRadius: 4,
        color: t.textMuted,
        cursor: 'pointer',
      }}
      onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
    >
      {children}
    </button>
  );
}

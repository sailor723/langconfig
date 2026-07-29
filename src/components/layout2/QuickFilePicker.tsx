/**
 * QuickFilePicker — VS Code-style Cmd+P file picker.
 *
 * Opens on Cmd+P / Ctrl+P. Fuzzy-searches across all sidebar items.
 * Arrow keys to navigate, Enter to open selected file, Escape to close.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab, ACTIVITIES, type ActivityId } from './useLayout';
import { useSidebarData } from './useSidebarData';
import { type TreeNode } from './TreeView';
import { File, Search, ArrowUpDown } from 'lucide-react';

interface FlatItem {
  node: TreeNode;
  activity: ActivityId;
  activityLabel: string;
}

export default function QuickFilePicker({ onClose }: { onClose: () => void }) {
  const t = useLayoutTokens();
  const { openTab, setActiveActivity } = useLayoutState();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [allItems, setAllItems] = useState<FlatItem[]>([]);

  // Load sidebar data for all activities to build the search index
  useEffect(() => {
    const loadAll = async () => {
      const items: FlatItem[] = [];
      for (const act of ACTIVITIES) {
        if (act.id === 'settings') continue;
        try {
          // We load the data by calling the API through a hidden component approach
          // For simplicity, collect from what's available in the tree
          const { nodes } = await fetchSidebarNodes(act.id);
          const flatten = (nds: TreeNode[], activity: ActivityId): FlatItem[] => {
            const result: FlatItem[] = [];
            for (const n of nds) {
              if (n.children) {
                result.push(...flatten(n.children, activity));
              } else if (n.viewType && n.viewType !== 'empty') {
                result.push({ node: n, activity, activityLabel: act.label });
              }
            }
            return result;
          };
          items.push(...flatten(nodes, act.id));
        } catch {}
      }
      setAllItems(items);
    };
    loadAll();
  }, []);

  // Filter items based on query (simple substring match)
  const filtered = useMemo(() => {
    if (!query.trim()) return allItems;
    const q = query.toLowerCase();
    return allItems.filter(item =>
      item.node.label.toLowerCase().includes(q)
    );
  }, [allItems, query]);

  // Reset selection when results change
  useEffect(() => setSelectedIndex(0), [filtered.length]);

  // Focus input
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Scroll selected item into view
  useEffect(() => {
    const el = listRef.current?.children[selectedIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  const handleOpen = useCallback((item: FlatItem) => {
    const tab: Tab = {
      id: item.node.id,
      label: item.node.label,
      viewType: item.node.viewType ?? item.activity,
      data: item.node.data,
    };
    setActiveActivity(item.activity);
    openTab(tab);
    onClose();
  }, [openTab, setActiveActivity, onClose]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(i => Math.min(i + 1, filtered.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(i => Math.max(i - 1, 0));
        break;
      case 'Enter':
        e.preventDefault();
        if (filtered[selectedIndex]) handleOpen(filtered[selectedIndex]);
        break;
      case 'Escape':
        e.preventDefault();
        onClose();
        break;
    }
  }, [filtered, selectedIndex, handleOpen, onClose]);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'flex-start',
        paddingTop: '15vh',
      }}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      {/* Backdrop */}
      <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)' }} />

      {/* Dialog */}
      <div
        style={{
          position: 'relative',
          width: 500,
          maxWidth: '90vw',
          background: t.bgBase,
          border: `1px solid ${t.border}`,
          borderRadius: 12,
          boxShadow: '0 16px 48px rgba(0,0,0,0.4)',
          overflow: 'hidden',
        }}
      >
        {/* Search input */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px', borderBottom: `1px solid ${t.border}` }}>
          <Search size={16} style={{ color: t.textMuted, flexShrink: 0 }} />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search files by name..."
            spellCheck={false}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              color: t.textPrimary,
              fontSize: 15,
              outline: 'none',
            }}
          />
        </div>

        {/* Results */}
        <div
          ref={listRef}
          style={{
            maxHeight: 300,
            overflowY: 'auto',
            padding: 4,
          }}
        >
          {filtered.length === 0 && (
            <div style={{ padding: '16px 20px', color: t.textMuted, fontSize: 13, textAlign: 'center' }}>
              {query ? 'No matches found' : 'No files available'}
            </div>
          )}
          {filtered.map((item, i) => (
            <div
              key={`${item.activity}-${item.node.id}`}
              onClick={() => handleOpen(item)}
              onMouseEnter={() => setSelectedIndex(i)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                borderRadius: 6,
                cursor: 'pointer',
                background: i === selectedIndex ? t.bgHover : 'transparent',
                color: t.textPrimary,
                fontSize: 13,
              }}
            >
              <File size={14} style={{ opacity: 0.6, flexShrink: 0 }} />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.node.label}
              </span>
              <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
                {item.activityLabel}
              </span>
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div style={{ padding: '6px 12px', borderTop: `1px solid ${t.border}`, display: 'flex', gap: 12, fontSize: 11, color: t.textDim }}>
          <span>↑↓ Navigate</span>
          <span>↵ Open</span>
          <span>Esc Close</span>
        </div>
      </div>
    </div>
  );
}

// ── Helper: fetch sidebar nodes for a given activity ────
async function fetchSidebarNodes(activity: ActivityId): Promise<{ nodes: TreeNode[] }> {
  const apiClient = (await import('../../lib/api-client')).default;
  const nodes: TreeNode[] = [];

  try {
    if (activity === 'workflows') {
      const res = await apiClient.listWorkflows();
      const workflows = Array.isArray(res.data) ? res.data : (res.data?.items || res.data?.workflows || []);
      nodes.push({
        id: 'folder-quick-workflows',
        label: 'My Workflows',
        children: workflows.map((wf: any) => ({
          id: `wf-${wf.id}`,
          label: wf.name || `Workflow #${wf.id}`,
          viewType: 'workflow',
          data: { workflowId: wf.id },
        })),
      });
    } else if (activity === 'agents') {
      const res = await apiClient.get('/api/agents/routes');
      const agents = Array.isArray(res.data) ? res.data : [];
      if (agents.length > 0) {
        nodes.push({
          id: 'folder-quick-agents',
          label: 'Agents',
          children: agents.map((ag: any) => ({
            id: `ag-${ag.id || ag.name}`,
            label: ag.name || ag.id || 'Unnamed Agent',
            viewType: 'agent',
            data: ag,
          })),
        });
      }
    } else if (activity === 'analysis') {
      nodes.push({
        id: 'folder-quick-analysis',
        label: 'Dashboards',
        children: [
          { id: 'db-sunhing', label: 'Sunhing KPI', viewType: 'analysis' },
          { id: 'db-sales', label: 'Sales Overview', viewType: 'analysis' },
        ],
      });
    }
  } catch {
    // Silently ignore fetch errors; the picker will show partial results
  }

  return { nodes };
}

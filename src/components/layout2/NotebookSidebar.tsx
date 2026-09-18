/**
 * NotebookSidebar — left-sidebar browser for educational Jupyter notebooks.
 *
 * Lists notebooks grouped by module from the /api/notebooks endpoint.
 * Clicking a notebook opens it in the workspace as a tab with 'notebook' view type.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import apiClient from '../../lib/api-client';
import {
  Folder, ChevronRight, ChevronDown, Loader, RefreshCw, BookOpen,
} from 'lucide-react';

interface NotebookSummary {
  module: string;
  name: string;
  display_name: string;
  cell_count: number;
  path: string;
}

export default function NotebookSidebar() {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();

  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());

  const loadNotebooks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get('/api/notebooks');
      const list: NotebookSummary[] = Array.isArray(res.data) ? res.data : [];
      setNotebooks(list);
      // Auto-expand first module
      if (list.length > 0) {
        const modules = new Set<string>();
        list.forEach(n => modules.add(n.module));
        setExpandedModules(modules);
      }
    } catch (err: any) {
      const msg = err?.response?.status === 0 || err?.code === 'ERR_NETWORK'
        ? 'Backend not reachable. Is the server running?'
        : err?.message || 'Failed to load notebooks';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadNotebooks(); }, [loadNotebooks]);

  const handleNotebookClick = useCallback((nb: NotebookSummary) => {
    const tab: Tab = {
      id: `notebook-${nb.module}-${nb.name}`,
      label: nb.display_name,
      viewType: 'notebook',
      data: { module: nb.module, name: nb.name, notebook: nb },
    };
    openTab(tab);
  }, [openTab]);

  const toggleModule = (mod: string) => {
    setExpandedModules(prev => {
      const next = new Set(prev);
      if (next.has(mod)) next.delete(mod); else next.add(mod);
      return next;
    });
  };

  // Group notebooks by module
  const grouped = notebooks.reduce<Record<string, NotebookSummary[]>>((acc, nb) => {
    const key = nb.module;
    if (!acc[key]) acc[key] = [];
    acc[key].push(nb);
    return acc;
  }, {});

  const moduleNames = Object.keys(grouped).sort();

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 12px', borderBottom: `1px solid ${t.border}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600, color: t.textPrimary }}>
          <BookOpen size={14} />
          <span>Notebooks</span>
          {!loading && <span style={{ fontSize: 11, color: t.textMuted }}>({notebooks.length})</span>}
        </div>
        <button
          onClick={loadNotebooks}
          title="Refresh"
          style={{
            background: 'none', border: 'none', color: t.textMuted, cursor: 'pointer',
            padding: 4, display: 'flex', borderRadius: 4,
          }}
          onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          <RefreshCw size={14} className={loading ? 'spin' : ''} />
        </button>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
        {loading && notebooks.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading...
          </div>
        ) : error ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: '#e5484d' }}>{error}</div>
        ) : moduleNames.length === 0 ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: t.textMuted }}>No notebooks found</div>
        ) : (
          moduleNames.map(mod => {
            const items = grouped[mod];
            const isExpanded = expandedModules.has(mod);
            return (
              <div key={mod}>
                {/* Module folder header */}
                <div
                  onClick={() => toggleModule(mod)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    padding: '6px 12px', cursor: 'pointer', fontSize: 12,
                    color: t.textPrimary, fontWeight: 600,
                    userSelect: 'none',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                >
                  {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  <Folder size={14} style={{ color: '#dcb67a' }} />
                  <span style={{ marginLeft: 2 }}>{mod}</span>
                  <span style={{ fontSize: 11, color: t.textMuted, marginLeft: 4 }}>({items.length})</span>
                </div>

                {/* Notebook items */}
                {isExpanded && items.map(nb => (
                  <div
                    key={nb.path}
                    onClick={() => handleNotebookClick(nb)}
                    title={nb.path}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '4px 12px 4px 36px', cursor: 'pointer', fontSize: 13,
                      color: t.textPrimary,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    <BookOpen size={13} style={{ color: t.textMuted, flexShrink: 0 }} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                      {nb.display_name}
                    </span>
                    <span style={{ fontSize: 10, color: t.textMuted, flexShrink: 0 }}>
                      {nb.cell_count} cells
                    </span>
                  </div>
                ))}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

/**
 * ToolBrowserSidebar — left-sidebar browser for native AND custom tools.
 *
 * Native tools: categories → click opens card grid in workspace.
 * Custom tools: list of user-created tools → click opens full builder.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import { Wrench, Loader, Plus, File } from 'lucide-react';

interface ToolItem {
  id: string;
  name: string;
  description: string;
  category: string;
  requires_api_key: string | null;
}

interface CustomToolSummary {
  tool_id: string;
  name: string;
  tool_type: string;
  category: string;
}

export default function ToolBrowserSidebar() {
  const t = useLayoutTokens();
  const { openTab, tabs } = useLayoutState();
  const [categories, setCategories] = useState<Array<{ category: string; count: number; tools: ToolItem[] }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Custom tools state
  const [customTools, setCustomTools] = useState<CustomToolSummary[]>([]);
  const [customLoading, setCustomLoading] = useState(false);

  /** Open a category's tool grid */
  const handleOpen = useCallback((category: string, tools: ToolItem[]) => {
    openTab({
      id: `tool-cat-${category}`,
      label: category.charAt(0).toUpperCase() + category.slice(1),
      viewType: 'tool-category',
      data: { category, tools },
    });
  }, [openTab]);

  /** Open the full custom tool builder (create or edit) */
  const handleOpenCustomTool = useCallback((existingToolId?: string) => {
    openTab({
      id: `custom-tool-${existingToolId || 'new'}-${Date.now()}`,
      label: existingToolId ? 'Edit Tool' : 'New Custom Tool',
      viewType: 'custom-tool-builder',
      data: { existingToolId: existingToolId || undefined },
    });
  }, [openTab]);

  /** Load native tool registry */
  const loadTools = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.listToolRegistry();
      const tools: ToolItem[] = Array.isArray(res) ? res : (res.data || []);
      const byCat: Record<string, ToolItem[]> = {};
      for (const tool of tools) {
        const cat = tool.category || 'other';
        if (!byCat[cat]) byCat[cat] = [];
        byCat[cat].push(tool);
      }
      setCategories(
        Object.entries(byCat)
          .map(([category, items]) => ({ category, count: items.length, tools: items }))
          .sort((a, b) => a.category.localeCompare(b.category))
      );
    } catch (err: any) {
      setError(err?.message || 'Failed to load tools');
    } finally {
      setLoading(false);
    }
  }, []);

  /** Load custom tools list */
  const loadCustomTools = useCallback(async () => {
    setCustomLoading(true);
    try {
      const res = await apiClient.listCustomTools();
      const data: CustomToolSummary[] = Array.isArray(res) ? res : (res.data || []);
      setCustomTools(data);
    } catch {
      // Silently fail for custom tools
    } finally {
      setCustomLoading(false);
    }
  }, []);

  // Track number of custom-tool-builder tabs to refresh on close
  const customBuilderTabCount = tabs.filter(tab => tab.viewType === 'custom-tool-builder').length;
  useEffect(() => { loadTools(); }, [loadTools]);
  useEffect(() => { loadCustomTools(); }, [loadCustomTools, customBuilderTabCount]);

  /** Matches TreeView child item: tight line spacing, 22px left indent, font 13 */
  const indentRowStyle = (): React.CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '2px 8px 2px 22px',
    cursor: 'pointer',
    color: t.textPrimary,
    fontSize: 13,
    userSelect: 'none',
  });

  const sectionHeaderStyle: React.CSSProperties = {
    padding: '8px 8px 4px',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: 0.3,
    textTransform: 'uppercase',
    color: '#bbb',
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  };

  const badgeStyle: React.CSSProperties = {
    fontSize: 11,
    padding: '1px 6px',
    borderRadius: 4,
    background: t.bgHover,
    color: t.textDim,
    flexShrink: 0,
  };

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ flex: 1, overflowY: 'auto' }}>

        {/* ── Native Tool Categories ── */}
        <div style={sectionHeaderStyle}>
          <Wrench size={14} />
          Tool Categories
        </div>

        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading...
          </div>
        ) : error ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: '#e5484d' }}>{error}</div>
        ) : categories.length === 0 ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: t.textMuted, fontStyle: 'italic' }}>
            (no tools available)
          </div>
        ) : (
          categories.map(({ category, count, tools }) => (
            <div
              key={category}
              onClick={() => handleOpen(category, tools)}
              style={indentRowStyle()}
              onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              {/* 16px spacer + File icon — matches TreeView file icon gutter */}
              <span style={{ width: 16, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <File size={15} style={{ opacity: 0.7 }} />
              </span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {category.charAt(0).toUpperCase() + category.slice(1)}
              </span>
              <span style={badgeStyle}>{count}</span>
            </div>
          ))
        )}

        {/* ── Separator ── */}
        <div style={{ height: 1, background: t.border, margin: '6px 8px' }} />

        {/* ── Custom Tools ── */}
        <div style={{ ...sectionHeaderStyle, textTransform: 'none' }}>
          <span style={{ flex: 1 }}>Custom Tools</span>
          <button
            onClick={() => handleOpenCustomTool()}
            title="New Custom Tool"
            style={{
              background: 'none',
              border: 'none',
              color: t.textMuted,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              padding: 2,
            }}
          >
            <Plus size={14} />
          </button>
        </div>

        {customLoading ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '16px 20px', fontSize: 13, color: t.textMuted }}>
            <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
            Loading...
          </div>
        ) : customTools.length === 0 ? (
          <div style={{ padding: '8px 20px', fontSize: 13, color: t.textMuted, fontStyle: 'italic' }}>
            (no custom tools yet)
          </div>
        ) : (
          customTools.map(tool => (
            <div
              key={tool.tool_id}
              onClick={() => handleOpenCustomTool(tool.tool_id)}
              style={indentRowStyle()}
              onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            >
              {/* 16px spacer + File icon — matches TreeView file icon gutter */}
              <span style={{ width: 16, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <File size={15} style={{ opacity: 0.7 }} />
              </span>
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {tool.name}
              </span>
              <span style={{ fontSize: 11, color: t.textDim }}>{tool.tool_type}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/**
 * ToolCategoryTab — workspace tab showing all tools in a category as cards.
 *
 * Follows the ModelCardsGridTab pattern: grid of cards with tool info.
 * Opens when the user clicks a category in ToolBrowserSidebar.
 */
import { useLayoutTokens } from './tokens';
import { useLayoutState, type Tab } from './useLayout';
import { Wrench, Globe, FolderOpen, Brain, Share2, HardDrive, Eye } from 'lucide-react';
import { useState } from 'react';
import apiClient from '../../lib/api-client';

interface ToolItem {
  id: string;
  name: string;
  description: string;
  category: string;
  requires_api_key: string | null;
}

interface Props { tab: Tab }

/** Map category to a small icon element */
const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  web:        <Globe size={18} />,
  filesystem: <FolderOpen size={18} />,
  memory:     <HardDrive size={18} />,
  reasoning:  <Brain size={18} />,
  delegation: <Share2 size={18} />,
};

export default function ToolCategoryTab({ tab }: Props) {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();
  const { category, tools } = (tab.data ?? {}) as { category: string; tools: ToolItem[] };
  const [detailsToolId, setDetailsToolId] = useState<string | null>(null);
  const [details, setDetails] = useState<any | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);

  /** Click a tool card → open its detailed editor tab */
  const handleOpenTool = (tool: ToolItem) => {
    openTab({
      id: `tool-${tool.id}`,
      label: tool.name,
      viewType: 'tool-editor',
      data: { toolId: tool.id },
    });
  };

  const handleViewPrompt = async (toolId: string) => {
    setDetailsToolId(toolId);
    setDetails(null);
    setDetailsLoading(true);
    try {
      const res = await apiClient.getToolDetails(toolId);
      setDetails(res.data);
    } catch (err: any) {
      setDetails({ error: err?.message || 'Failed to load' });
    } finally {
      setDetailsLoading(false);
    }
  };

  const headerIcon = CATEGORY_ICONS[category] || <Wrench size={18} />;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: t.bgContent, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '16px 20px',
        borderBottom: `1px solid ${t.border}`,
        flexShrink: 0,
      }}>
        <span style={{ color: t.accent }}>{headerIcon}</span>
        <div>
          <h2 style={{ fontSize: 18, fontWeight: 600, color: t.textPrimary, margin: 0 }}>
            {category.charAt(0).toUpperCase() + category.slice(1)}
          </h2>
          <p style={{ fontSize: 12, color: t.textMuted, margin: '2px 0 0 0' }}>
            {tools.length} tool{tools.length !== 1 ? 's' : ''} available
          </p>
        </div>
      </div>

      {/* Tool cards grid */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 12,
        }}>
          {tools.map(tool => {
            const needsKey = !!tool.requires_api_key;
            return (
              <div
                key={tool.id}
                onClick={() => handleOpenTool(tool)}
                style={{
                  background: t.bgContent,
                  border: `1px solid ${t.border}`,
                  borderRadius: 6,
                  padding: 14,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                  cursor: 'pointer',
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = t.accent; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; }}
              >
                {/* Header row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    width: 32,
                    height: 32,
                    borderRadius: 6,
                    background: t.bgHover,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: t.accent,
                    flexShrink: 0,
                  }}>
                    {CATEGORY_ICONS[tool.category] || <Wrench size={16} />}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {tool.name}
                    </div>
                    <code style={{ fontSize: 10, color: t.textDim, fontFamily: 'monospace' }}>
                      {tool.id}
                    </code>
                  </div>
                  {needsKey && (
                    <span style={{
                      fontSize: 10,
                      padding: '2px 6px',
                      borderRadius: 3,
                      background: '#f59e0b20',
                      color: '#f59e0b',
                      fontWeight: 600,
                      flexShrink: 0,
                    }}>
                      API
                    </span>
                  )}
                </div>

                {/* Description */}
                <p style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.4, margin: 0, flex: 1 }}>
                  {tool.description}
                </p>

                {/* Key info + action */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  {needsKey ? (
                    <span style={{ fontSize: 10, color: '#f59e0b', fontFamily: 'monospace' }}>
                      {tool.requires_api_key}
                    </span>
                  ) : (
                    <span style={{ fontSize: 10, color: '#4caf50' }}>
                      No API key needed
                    </span>
                  )}
                  <button
                    onClick={() => handleViewPrompt(tool.id)}
                    title="View LLM-facing prompt"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                      height: 24,
                      padding: '0 8px',
                      background: 'transparent',
                      border: `1px solid ${t.border}`,
                      borderRadius: 3,
                      color: t.textMuted,
                      fontSize: 11,
                      cursor: 'pointer',
                      flexShrink: 0,
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; e.currentTarget.style.color = t.textPrimary; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = t.textMuted; }}
                  >
                    <Eye size={11} />
                    Prompt
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {tools.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', fontSize: 13, color: t.textMuted, fontStyle: 'italic' }}>
            (no tools in this category)
          </div>
        )}
      </div>

      {/* View-Prompt modal */}
      {detailsToolId && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 100,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(0,0,0,0.5)',
          }}
          onClick={() => { setDetailsToolId(null); setDetails(null); }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: t.bgSidebar,
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              width: '90%',
              maxWidth: 640,
              maxHeight: '80vh',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
            }}
          >
            {/* Modal header */}
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 16px',
              borderBottom: `1px solid ${t.border}`,
            }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: t.textPrimary }}>
                {details?.name || detailsToolId} — Prompt
              </span>
              <button
                onClick={() => { setDetailsToolId(null); setDetails(null); }}
                style={{ background: 'none', border: 'none', color: t.textMuted, cursor: 'pointer', fontSize: 16 }}
              >
                ✕
              </button>
            </div>
            {/* Modal body */}
            <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
              {detailsLoading && (
                <div style={{ color: t.textMuted, fontSize: 13 }}>Loading...</div>
              )}
              {details?.error && (
                <div style={{ color: '#e5484d', fontSize: 13 }}>{details.error}</div>
              )}
              {details && !details.error && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, color: t.textMuted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
                      UI Description
                    </div>
                    <p style={{ fontSize: 13, color: t.textPrimary, margin: 0 }}>{details.ui_description}</p>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: t.textMuted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
                      LLM Description ({details.llm_description?.length || 0} chars)
                    </div>
                    <pre style={{
                      fontSize: 12, color: t.textPrimary, fontFamily: '"SF Mono", monospace',
                      whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5,
                      background: t.bgContent, border: `1px solid ${t.border}`, borderRadius: 4,
                      padding: 10, margin: 0, maxHeight: 200, overflow: 'auto',
                    }}>
                      {details.llm_description || '(none)'}
                    </pre>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: t.textMuted, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 4 }}>
                      Argument Schema
                    </div>
                    {details.args_schema && Object.keys(details.args_schema).length > 0 ? (
                      <pre style={{
                        fontSize: 12, color: t.textPrimary, fontFamily: '"SF Mono", monospace',
                        whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.5,
                        background: t.bgContent, border: `1px solid ${t.border}`, borderRadius: 4,
                        padding: 10, margin: 0, maxHeight: 200, overflow: 'auto',
                      }}>
                        {JSON.stringify(details.args_schema, null, 2)}
                      </pre>
                    ) : (
                      <p style={{ fontSize: 12, color: t.textMuted, fontStyle: 'italic', margin: 0 }}>
                        (no arguments — tool is called without a payload)
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

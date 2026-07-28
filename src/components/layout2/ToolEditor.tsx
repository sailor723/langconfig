/**
 * ToolEditor — detailed editor for an individual tool.
 *
 * Opens when clicking a tool card in ToolCategoryTab.
 * Fetches full details from /api/tools/registry/{id}/details.
 * Sections: Overview, Prompt, Schema, JSON
 */
import { useEffect, useState } from 'react';
import { useLayoutTokens } from './tokens';
import { Info, FileText, Database, Code, Loader } from 'lucide-react';
import type { Tab } from './useLayout';
import apiClient from '../../lib/api-client';

interface ToolEditorProps {
  tab: Tab;
}

type SectionId = 'overview' | 'prompt' | 'schema' | 'json';

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <Info size={13} /> },
  { id: 'prompt',   label: 'Prompt',   icon: <FileText size={13} /> },
  { id: 'schema',   label: 'Schema',   icon: <Database size={13} /> },
  { id: 'json',     label: 'JSON',     icon: <Code size={13} /> },
];

export default function ToolEditor({ tab }: ToolEditorProps) {
  const t = useLayoutTokens();
  const { toolId } = tab.data ?? {};
  const [tool, setTool] = useState<any>(tab.data?.details ?? null);
  const [loading, setLoading] = useState(!tool);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionId>('overview');

  // Fetch tool details if not already loaded
  useEffect(() => {
    if (tool) return;
    if (!toolId) { setError('No tool ID provided'); setLoading(false); return; }
    setLoading(true);
    setError(null);
    apiClient.getToolDetails(toolId)
      .then((res: any) => setTool(res.data))
      .catch((err: any) => setError(err?.message || 'Failed to load tool details'))
      .finally(() => setLoading(false));
  }, [toolId, tool]);

  // Reusable styles (white bg card style)
  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 6,
    padding: 14,
    marginBottom: 10,
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    color: t.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 4,
  };
  const valueStyle: React.CSSProperties = {
    fontSize: 13,
    color: t.textPrimary,
  };

  // ── Loading state ──
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 8, color: t.textMuted, fontSize: 13 }}>
        <Loader size={14} style={{ animation: 'spin 1s linear infinite' }} />
        Loading tool details...
      </div>
    );
  }

  // ── Error state ──
  if (error || !tool) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#e5484d', fontSize: 13 }}>
        {error || 'Tool not found'}
      </div>
    );
  }

  // ── Overview section ──
  const renderOverview = () => (
    <div style={{ padding: 4 }}>
      <div style={cardStyle}>
        <div style={labelStyle}>Name</div>
        <div style={{ ...valueStyle, fontSize: 18, fontWeight: 600 }}>{tool.name || tool.id || '—'}</div>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Tool ID</div>
        <code style={{ ...valueStyle, fontFamily: 'monospace' }}>{tool.id || '—'}</code>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>UI Description</div>
        <div style={valueStyle}>{tool.ui_description || tool.description || '—'}</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Category</div>
          <div style={valueStyle}>{tool.category || '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Requires API Key</div>
          {tool.requires_api_key ? (
            <div style={{ ...valueStyle, fontFamily: 'monospace', color: '#f59e0b' }}>{tool.requires_api_key}</div>
          ) : (
            <div style={{ ...valueStyle, color: '#4caf50' }}>None</div>
          )}
        </div>
      </div>
    </div>
  );

  // ── LLM-facing description section ──
  const renderPrompt = () => {
    const llmDesc = tool.llm_description || '';
    return (
      <div style={{ padding: 4 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>LLM-Facing Description ({llmDesc.length} chars)</div>
          <pre style={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            fontFamily: '"SF Mono", "Fira Code", monospace',
            fontSize: 12,
            color: t.textPrimary,
            lineHeight: 1.5,
            margin: 0,
            maxHeight: 400,
            overflow: 'auto',
          }}>
            {llmDesc || '(no LLM description)'}
          </pre>
        </div>
      </div>
    );
  };

  // ── Args schema section ──
  const renderSchema = () => {
    const schema = tool.args_schema || {};
    const hasSchema = Object.keys(schema).length > 0;
    return (
      <div style={{ padding: 4 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Argument Schema (JSON Schema)</div>
          {hasSchema ? (
            <pre style={{
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: '"SF Mono", "Fira Code", monospace',
              fontSize: 12,
              color: t.textPrimary,
              lineHeight: 1.5,
              margin: 0,
              maxHeight: 400,
              overflow: 'auto',
            }}>
              {JSON.stringify(schema, null, 2)}
            </pre>
          ) : (
            <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>
              (no arguments — tool is called without a payload)
            </div>
          )}
        </div>
      </div>
    );
  };

  // ── JSON section ──
  const renderJson = () => (
    <div style={{ padding: 4 }}>
      <pre style={{
        background: t.bgContent,
        border: `1px solid ${t.border}`,
        borderRadius: 6,
        padding: 14,
        fontFamily: '"SF Mono", "Fira Code", monospace',
        fontSize: 12,
        color: t.textPrimary,
        overflow: 'auto',
        minHeight: 300,
        lineHeight: 1.5,
        margin: 0,
      }}>
        {JSON.stringify(tool, null, 2)}
      </pre>
    </div>
  );

  const sections: Record<SectionId, () => React.ReactNode> = {
    overview: renderOverview,
    prompt:   renderPrompt,
    schema:   renderSchema,
    json:     renderJson,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: t.bgContent }}>
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Section nav */}
        <div style={{
          width: 130,
          minWidth: 130,
          background: t.bgSidebar,
          borderRight: `1px solid ${t.border}`,
          padding: '8px 0',
          overflowY: 'auto',
          flexShrink: 0,
        }}>
          {SECTIONS.map(s => {
            const isActive = s.id === activeSection;
            return (
              <button
                key={s.id}
                onClick={() => setActiveSection(s.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  width: '100%',
                  padding: '8px 14px',
                  fontSize: 12,
                  color: isActive ? t.textPrimary : t.textMuted,
                  background: isActive ? t.bgHover : 'transparent',
                  border: 'none',
                  borderLeft: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                {s.icon}
                {s.label}
              </button>
            );
          })}
        </div>

        {/* Section content */}
        <div style={{ flex: 1, padding: 16, overflowY: 'auto', minHeight: 0 }}>
          <h2 style={{ fontSize: 16, fontWeight: 600, color: t.textPrimary, margin: '0 0 12px 0' }}>
            {tool.name || tool.id || 'Tool'}
          </h2>
          {sections[activeSection]()}
        </div>
      </div>
    </div>
  );
}

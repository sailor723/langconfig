/**
 * DeepAgentEditor — structured editor for a DeepAgent template.
 *
 * Sections (left-to-right tab nav):
 *   - Overview     name, description, category, model, version, stats
 *   - Prompt       system_prompt (large textarea)
 *   - Tools        native_tools / cli_tools / custom_tools
 *   - Subagents    list of subagent cards
 *   - Middleware   list with enabled toggles
 *   - Guardrails   token limits, eviction
 *   - JSON         raw config
 */
import { useState } from 'react';
import { useLayoutTokens } from './tokens';
import {
  Info, FileText, Wrench, Users, Layers, Shield, Code, ChevronDown, ChevronRight,
} from 'lucide-react';
import type { Tab } from './useLayout';

interface DeepAgentEditorProps {
  tab: Tab;
}

type SectionId = 'overview' | 'prompt' | 'tools' | 'subagents' | 'middleware' | 'guardrails' | 'json';

const SECTIONS: { id: SectionId; label: string; icon: React.ReactNode }[] = [
  { id: 'overview',   label: 'Overview',   icon: <Info size={13} /> },
  { id: 'prompt',     label: 'Prompt',     icon: <FileText size={13} /> },
  { id: 'tools',      label: 'Tools',      icon: <Wrench size={13} /> },
  { id: 'subagents',  label: 'Subagents',  icon: <Users size={13} /> },
  { id: 'middleware', label: 'Middleware', icon: <Layers size={13} /> },
  { id: 'guardrails', label: 'Guardrails', icon: <Shield size={13} /> },
  { id: 'json',       label: 'JSON',       icon: <Code size={13} /> },
];

export default function DeepAgentEditor({ tab }: DeepAgentEditorProps) {
  const t = useLayoutTokens();
  const agent = tab.data?.agent ?? tab.data ?? {};
  const config = agent.config || {};
  const [activeSection, setActiveSection] = useState<SectionId>('overview');
  const [expandedSubs, setExpandedSubs] = useState<Record<number, boolean>>({});

  // ── Reusable styles ──
  const cardStyle: React.CSSProperties = {
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    padding: 12,
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

  // ── Overview section ──
  const renderOverview = () => (
    <div style={{ padding: 4 }}>
      <div style={cardStyle}>
        <div style={labelStyle}>Name</div>
        <div style={{ ...valueStyle, fontSize: 18, fontWeight: 600 }}>{agent.name || '—'}</div>
      </div>
      <div style={cardStyle}>
        <div style={labelStyle}>Description</div>
        <div style={valueStyle}>{agent.description || '—'}</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Category</div>
          <div style={valueStyle}>{agent.category || '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Model</div>
          <div style={{ ...valueStyle, fontFamily: 'monospace' }}>{config.model || '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Temperature</div>
          <div style={valueStyle}>{config.temperature ?? '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Max Tokens</div>
          <div style={valueStyle}>{config.max_tokens ?? '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Version</div>
          <div style={valueStyle}>{agent.version || '—'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Public</div>
          <div style={valueStyle}>{agent.is_public ? 'Yes' : 'No'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Usage Count</div>
          <div style={valueStyle}>{agent.usage_count ?? 0}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Chat Sessions</div>
          <div style={valueStyle}>{agent.chat_sessions_count ?? 0}</div>
        </div>
      </div>
    </div>
  );

  // ── System prompt section ──
  const renderPrompt = () => (
    <div style={{ padding: 4 }}>
      <div style={cardStyle}>
        <div style={labelStyle}>System Prompt ({config.system_prompt?.length ?? 0} chars)</div>
        <pre style={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          fontFamily: '"SF Mono", "Fira Code", monospace',
          fontSize: 12,
          color: t.textPrimary,
          lineHeight: 1.5,
          margin: 0,
        }}>
          {config.system_prompt || '(empty)'}
        </pre>
      </div>
    </div>
  );

  // ── Tools section ──
  const renderTools = () => {
    const native = config.native_tools || [];
    const cli = config.cli_tools || [];
    const custom = config.custom_tools || [];
    const groups = [
      { label: 'Native Tools', items: native },
      { label: 'CLI Tools', items: cli },
      { label: 'Custom Tools', items: custom },
    ];
    return (
      <div style={{ padding: 4 }}>
        {groups.map(g => (
          <div key={g.label} style={cardStyle}>
            <div style={labelStyle}>{g.label} ({g.items.length})</div>
            {g.items.length === 0 ? (
              <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(none)</div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {g.items.map((tool: string, i: number) => (
                  <span key={i} style={{
                    fontSize: 11,
                    padding: '3px 8px',
                    background: t.bgHover,
                    border: `1px solid ${t.border}`,
                    borderRadius: 3,
                    color: t.textPrimary,
                    fontFamily: 'monospace',
                  }}>
                    {tool}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  // ── Subagents section ──
  const renderSubagents = () => {
    const subs = agent.subagents || agent.subagents_config || [];
    if (subs.length === 0) {
      return (
        <div style={{ padding: 4 }}>
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(no subagents)</div>
        </div>
      );
    }
    return (
      <div style={{ padding: 4 }}>
        {subs.map((sa: any, i: number) => {
          const open = expandedSubs[i];
          return (
            <div key={i} style={cardStyle}>
              <div
                onClick={() => setExpandedSubs(prev => ({ ...prev, [i]: !prev[i] }))}
                style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}
              >
                {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <div style={{ ...valueStyle, fontWeight: 600 }}>{sa.name || `Subagent #${i + 1}`}</div>
                <div style={{ ...valueStyle, color: t.textMuted, fontSize: 11, marginLeft: 8 }}>
                  {sa.description?.slice(0, 60)}
                </div>
              </div>
              {open && (
                <div style={{ marginTop: 10, paddingLeft: 20 }}>
                  <div style={labelStyle}>Description</div>
                  <div style={{ ...valueStyle, marginBottom: 8 }}>{sa.description || '—'}</div>
                  {sa.model && (
                    <>
                      <div style={labelStyle}>Model</div>
                      <div style={{ ...valueStyle, fontFamily: 'monospace', marginBottom: 8 }}>{sa.model}</div>
                    </>
                  )}
                  {sa.tools && sa.tools.length > 0 && (
                    <>
                      <div style={labelStyle}>Tools ({sa.tools.length})</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 8 }}>
                        {sa.tools.map((tool: string, j: number) => (
                          <span key={j} style={{
                            fontSize: 11, padding: '2px 6px',
                            background: t.bgHover, borderRadius: 3,
                            color: t.textPrimary, fontFamily: 'monospace',
                          }}>{tool}</span>
                        ))}
                      </div>
                    </>
                  )}
                  {sa.system_prompt && (
                    <>
                      <div style={labelStyle}>System Prompt</div>
                      <pre style={{
                        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                        fontFamily: '"SF Mono", monospace', fontSize: 11,
                        color: t.textMuted, lineHeight: 1.5, margin: 0,
                        maxHeight: 200, overflow: 'auto',
                      }}>{sa.system_prompt}</pre>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  // ── Middleware section ──
  const renderMiddleware = () => {
    const mw = agent.middleware_config || config.middleware || [];
    if (mw.length === 0) {
      return (
        <div style={{ padding: 4 }}>
          <div style={{ ...valueStyle, color: t.textMuted, fontStyle: 'italic' }}>(no middleware)</div>
        </div>
      );
    }
    return (
      <div style={{ padding: 4 }}>
        {mw.map((m: any, i: number) => (
          <div key={i} style={cardStyle}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                fontSize: 11, padding: '2px 6px',
                background: m.enabled ? t.accent : t.bgHover,
                color: m.enabled ? '#fff' : t.textMuted,
                borderRadius: 3, fontWeight: 600,
              }}>{m.enabled ? 'ON' : 'OFF'}</span>
              <span style={{ ...valueStyle, fontWeight: 600 }}>{m.type}</span>
            </div>
            {m.config && Object.keys(m.config).length > 0 && (
              <div style={{ marginTop: 8, fontFamily: 'monospace', fontSize: 11, color: t.textMuted }}>
                {JSON.stringify(m.config, null, 2)}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  // ── Guardrails section ──
  const renderGuardrails = () => {
    const g = agent.guardrails_config || config.guardrails || {};
    const tl = g.token_limits || {};
    return (
      <div style={{ padding: 4 }}>
        <div style={cardStyle}>
          <div style={labelStyle}>Auto Eviction</div>
          <div style={valueStyle}>{g.enable_auto_eviction ? 'Enabled' : 'Disabled'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Summarization</div>
          <div style={valueStyle}>{g.enable_summarization ? 'Enabled' : 'Disabled'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Long-Term Memory</div>
          <div style={valueStyle}>{g.long_term_memory ? 'Enabled' : 'Disabled'}</div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Token Limits</div>
          <div style={{ fontFamily: 'monospace', fontSize: 12, color: t.textPrimary }}>
            <div>max_total: {tl.max_total_tokens?.toLocaleString() ?? '—'}</div>
            <div>eviction_threshold: {tl.eviction_threshold?.toLocaleString() ?? '—'}</div>
            <div>summarization_threshold: {tl.summarization_threshold?.toLocaleString() ?? '—'}</div>
          </div>
        </div>
        <div style={cardStyle}>
          <div style={labelStyle}>Backend</div>
          <div style={valueStyle}>{agent.backend_config?.type ?? '—'}</div>
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
        borderRadius: 4,
        padding: 12,
        fontFamily: '"SF Mono", "Fira Code", monospace',
        fontSize: 12,
        color: t.textPrimary,
        overflow: 'auto',
        maxHeight: 'calc(100vh - 200px)',
        margin: 0,
      }}>
        {JSON.stringify(agent, null, 2)}
      </pre>
    </div>
  );

  const sections: Record<SectionId, () => React.ReactNode> = {
    overview:   renderOverview,
    prompt:     renderPrompt,
    tools:      renderTools,
    subagents:  renderSubagents,
    middleware: renderMiddleware,
    guardrails: renderGuardrails,
    json:       renderJson,
  };

  return (
    <div style={{ display: 'flex', height: '100%', background: t.bgContent }}>
      {/* ── Section nav (left rail) ── */}
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

      {/* ── Section content ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
        <h2 style={{
          fontSize: 16,
          fontWeight: 600,
          color: t.textPrimary,
          margin: '0 0 12px 0',
        }}>
          {agent.name || 'DeepAgent'}
        </h2>
        {sections[activeSection]()}
      </div>
    </div>
  );
}
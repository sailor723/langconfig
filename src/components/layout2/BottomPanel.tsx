/**
 * BottomPanel — VS Code-style bottom panel for Terminal / Execution / Results / Chat.
 */
import { useState } from 'react';
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import { Terminal, Play, FileText, ChevronDown } from 'lucide-react';
import { useChatMessages } from './chatStore';

type PanelTab = 'terminal' | 'execution' | 'results';

const PANEL_TABS: { id: PanelTab; label: string; icon: React.ReactNode }[] = [
  { id: 'terminal',   label: 'Terminal',   icon: <Terminal size={13} /> },
  { id: 'execution',  label: 'Execution',  icon: <Play size={13} /> },
  { id: 'results',    label: 'Results',    icon: <FileText size={13} /> },
];

export default function BottomPanel() {
  const { bottomPanelOpen, toggleBottomPanel } = useLayoutState();
  const t = useLayoutTokens();
  const [activeTab, setActiveTab] = useState<PanelTab>('terminal');

  return (
    <div
      style={{
        borderTop: `1px solid ${t.border}`,
        background: t.bgTabBar,
        display: 'flex',
        flexDirection: 'column',
        userSelect: 'none',
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          height: 35,
          minHeight: 35,
          padding: '0 8px',
          gap: 0,
        }}
      >
        {PANEL_TABS.map(p => {
          const isActive = p.id === activeTab;
          return (
            <button
              key={p.id}
              onClick={() => {
                setActiveTab(p.id);
                if (!bottomPanelOpen) toggleBottomPanel();
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                height: 35,
                padding: '0 12px',
                fontSize: 12,
                color: isActive ? t.textPrimary : t.textMuted,
                background: 'transparent',
                border: 'none',
                borderBottom: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                cursor: 'pointer',
              }}
            >
              {p.icon}
              {p.label}
            </button>
          );
        })}

        <div style={{ flex: 1 }} />

        {/* Collapse/expand toggle */}
        <button
          onClick={toggleBottomPanel}
          title={bottomPanelOpen ? 'Close panel' : 'Open panel'}
          style={{
            width: 24,
            height: 24,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent',
            border: 'none',
            color: t.textMuted,
            cursor: 'pointer',
          }}
        >
          <ChevronDown size={14} style={{ transform: bottomPanelOpen ? 'rotate(180deg)' : 'none' }} />
        </button>
      </div>

      {/* Content */}
      {bottomPanelOpen && (
        <div
          style={{
            height: 200,
            minHeight: 200,
            background: t.bgContent,
            borderTop: `1px solid ${t.border}`,
            overflow: 'auto',
            padding: 12,
            fontFamily: '"SF Mono", "Fira Code", monospace',
            fontSize: 12,
          }}
        >
          {activeTab === 'terminal' && <TerminalContent t={t} />}
          {activeTab === 'execution' && <ExecutionContent t={t} />}
          {activeTab === 'results' && <ResultsContent t={t} />}
        </div>
      )}
    </div>
  );
}

// ── Terminal content ────────────────────────────────────

function TerminalContent({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const [lines, setLines] = useState<string[]>([
    '$ npm run dev',
    '> agent-studio@1.0.0 dev',
    '> vite',
    '',
    '  VITE v7.3.2  ready in 94ms',
    '  ➜  Local:   http://localhost:1420/',
    '',
  ]);

  return (
    <div style={{ color: '#cccccc' }}>
      {lines.map((line, i) => (
        <div key={i} style={{ whiteSpace: 'pre' }}>
          {line || '\u00A0'}
        </div>
      ))}
      <div style={{ display: 'flex' }}>
        <span style={{ color: '#6a9955' }}>$ </span>
        <input
          autoFocus
          placeholder="type a command..."
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            color: '#cccccc',
            outline: 'none',
            fontFamily: 'inherit',
            fontSize: 12,
          }}
          onKeyDown={e => {
            if (e.key === 'Enter' && e.currentTarget.value.trim()) {
              setLines(prev => [...prev, `$ ${e.currentTarget.value}`]);
              e.currentTarget.value = '';
            }
          }}
        />
      </div>
    </div>
  );
}

// ── Execution logs (from chat store) ────────────────────

function ExecutionContent({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const messages = useChatMessages();
  const entries = messages
    .filter(m => m.role === 'assistant' || m.role === 'system')
    .slice(-50)
    .reverse();

  return (
    <div>
      {entries.length === 0 ? (
        <p style={{ color: t.textMuted, fontStyle: 'italic', fontFamily: 'inherit', fontSize: 13 }}>
          No execution logs yet. Run a DeepAgent test to see results here.
        </p>
      ) : (
        entries.map((msg, i) => (
          <div key={msg.id} style={{ padding: '3px 0', borderBottom: i < entries.length - 1 ? `1px solid ${t.border}` : 'none' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <span style={{ color: t.textDim, flexShrink: 0, fontSize: 11 }}>
                {new Date(msg.ts).toLocaleTimeString()}
              </span>
              <span style={{
                color: msg.role === 'system' ? '#f59e0b' : '#4fc3f7',
                flexShrink: 0,
                fontSize: 11,
                fontWeight: 600,
                width: 60,
              }}>
                {msg.role === 'system' ? '[system]' : msg.streaming ? '[stream]' : '[agent]'}
              </span>
              <span style={{
                color: t.textPrimary,
                fontSize: 12,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                flex: 1,
              }}>
                {msg.text.slice(0, 200)}{msg.text.length > 200 ? '…' : ''}
              </span>
            </div>
            {msg.streaming && (
              <div style={{ marginTop: 2, fontSize: 11, color: '#4fc3f7' }}>
                [streaming] In progress…
              </div>
            )}
            {msg.meta && (
              <div style={{ display: 'flex', gap: 12, marginTop: 2, fontSize: 11, color: t.textMuted }}>
                {msg.meta.latencyMs != null && <span>latency: {msg.meta.latencyMs}ms</span>}
                {msg.meta.tokens != null && <span>tokens: {msg.meta.tokens}</span>}
                {msg.meta.toolCalls != null && <span>tools: {msg.meta.toolCalls}</span>}
              </div>
            )}
            {msg.toolCalls && msg.toolCalls.length > 0 && (
              <div style={{ marginTop: 6, marginLeft: 68, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {msg.toolCalls.map((tc, j) => (
                  <div key={`${msg.id}-tc-${j}`} style={{
                    border: `1px solid ${
                      tc.status === 'running' ? '#3b82f6'
                      : tc.status === 'error' ? '#ef4444'
                      : t.border
                    }`,
                    background: t.bgSidebar,
                    borderRadius: 4,
                    padding: '4px 8px',
                    fontSize: 11,
                    display: 'flex', flexDirection: 'column', gap: 3,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{
                        color: tc.status === 'running' ? '#3b82f6'
                          : tc.status === 'error' ? '#ef4444'
                          : '#10b981',
                        flexShrink: 0, fontSize: 13,
                      }}>
                        {tc.status === 'running' ? '⟳' : tc.status === 'error' ? '✗' : '✓'}
                      </span>
                      <span style={{ fontFamily: 'monospace', color: t.textPrimary, fontWeight: 600 }}>
                        {tc.name}
                      </span>
                      {tc.endedAt && tc.startedAt && (
                        <span style={{ marginLeft: 'auto', color: t.textMuted, fontSize: 10 }}>
                          {tc.endedAt - tc.startedAt}ms
                        </span>
                      )}
                      {tc.status === 'running' && (
                        <span style={{ marginLeft: 'auto', color: '#3b82f6', fontSize: 10 }}>
                          running…
                        </span>
                      )}
                    </div>
                    {tc.args && Object.keys(tc.args).length > 0 && (
                      <div style={{
                        fontFamily: '"SF Mono", "Fira Code", monospace',
                        color: t.textMuted,
                        paddingLeft: 18,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        overflow: 'hidden',
                        maxHeight: 60,
                      }}>
                        {JSON.stringify(tc.args)}
                      </div>
                    )}
                    {tc.result && (
                      <div style={{
                        fontFamily: '"SF Mono", "Fira Code", monospace',
                        color: tc.status === 'error' ? '#fca5a5' : t.textPrimary,
                        paddingLeft: 18,
                        paddingTop: 2,
                        borderTop: `1px dashed ${t.border}`,
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        overflow: 'hidden',
                        maxHeight: 80,
                      }}>
                        {tc.result}
                      </div>
                    )}
                    {tc.error && tc.status === 'error' && !tc.result && (
                      <div style={{
                        fontFamily: '"SF Mono", "Fira Code", monospace',
                        color: '#fca5a5',
                        paddingLeft: 18,
                      }}>
                        {tc.error}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}

// ── Results output (completed assistant messages) ─────────

function ResultsContent({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const messages = useChatMessages();
  const completed = messages.filter(m => m.role === 'assistant' && !m.streaming).slice(-10);

  return (
    <div>
      {completed.length === 0 ? (
        <p style={{ color: t.textMuted, fontStyle: 'italic', fontFamily: 'inherit', fontSize: 13 }}>
          No completed results yet. Run a DeepAgent to see output here.
        </p>
      ) : (
        completed.map(msg => (
          <div key={msg.id} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: t.textDim }}>
                {new Date(msg.ts).toLocaleTimeString()}
              </span>
              {msg.thinking && (
                <span style={{ fontSize: 11, color: '#f59e0b' }}>
                  [has reasoning trace]
                </span>
              )}
              {msg.meta?.latencyMs != null && (
                <span style={{ fontSize: 11, color: t.textMuted }}>
                  {msg.meta.latencyMs}ms
                </span>
              )}
            </div>
            <div style={{
              background: t.bgHover,
              border: `1px solid ${t.border}`,
              borderRadius: 4,
              padding: 10,
              fontSize: 13,
              color: t.textPrimary,
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              maxHeight: 200,
              overflowY: 'auto',
            }}>
              {msg.text || '(empty response)'}
            </div>
          </div>
        ))
      )}
    </div>
  );
}

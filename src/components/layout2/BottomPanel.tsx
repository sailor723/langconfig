/**
 * BottomPanel — VS Code-style bottom panel for Terminal / Execution / Results.
 *
 * VS Code pattern:
 *   - Header: #252526 bg, tabs with accent bottom border on active
 *   - Content: #1e1e1e bg when open
 *   - Tabs: Terminal, Execution, Results
 */
import { useState } from 'react';
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import { Terminal, Play, FileText, ChevronDown } from 'lucide-react';

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

// ── Execution logs ──────────────────────────────────────

function ExecutionContent({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const logs = [
    { level: 'info', msg: 'Workflow "Chat Agent" loaded', ts: '10:23:01' },
    { level: 'info', msg: 'Node "greeter" initialized', ts: '10:23:02' },
    { level: 'warn', msg: 'Rate limit approaching (85%)', ts: '10:23:15' },
    { level: 'info', msg: 'Execution completed in 2.3s', ts: '10:23:18' },
  ];

  return (
    <div>
      {logs.length === 0 ? (
        <p style={{ color: t.textMuted, fontStyle: 'italic', fontFamily: 'inherit', fontSize: 13 }}>
          No execution logs yet.
        </p>
      ) : (
        logs.map((log, i) => (
          <div key={i} style={{ display: 'flex', gap: 12, padding: '2px 0', color: t.textMuted }}>
            <span style={{ color: t.textDim, flexShrink: 0 }}>{log.ts}</span>
            <span style={{ color: log.level === 'warn' ? '#f59e0b' : t.textPrimary, flexShrink: 0, width: 40 }}>
              [{log.level}]
            </span>
            <span style={{ color: t.textPrimary }}>{log.msg}</span>
          </div>
        ))
      )}
    </div>
  );
}

// ── Results output ──────────────────────────────────────

function ResultsContent({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  return (
    <div>
      <p style={{ color: t.textMuted, fontStyle: 'italic', fontFamily: 'inherit', fontSize: 13 }}>
        Execution results and rendered output will appear here.
      </p>
    </div>
  );
}

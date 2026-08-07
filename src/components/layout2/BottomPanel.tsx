/**
 * BottomPanel — VS Code-style bottom panel.
 *
 * The terminal area is a tab strip like VS Code: "System Log" (backend logs,
 * pinned) plus any number of interactive shell terminals added with the "+"
 * button. Each shell tab can be closed; the chevron on the right opens a
 * terminal list with add/kill actions. Execution and Results are separate
 * panel sections.
 */
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import { ScrollText, Terminal, Play, FileText, Plus, Trash2, ChevronDown, X, Check } from 'lucide-react';
import { useChatMessages } from './chatStore';
import TerminalTab from './TerminalTab';

type PanelSection = 'terminal' | 'execution' | 'results';

interface ShellTerminal {
  id: string;
  n: number;
  /** Display label — "Terminal N" until the shell announces itself, then "zsh N". */
  name: string;
}

export default function BottomPanel() {
  const { bottomPanelOpen, toggleBottomPanel } = useLayoutState();
  const t = useLayoutTokens();
  const [activeSection, setActiveSection] = useState<PanelSection>('terminal');
  const [shells, setShells] = useState<ShellTerminal[]>([]);
  const [activeShellId, setActiveShellId] = useState<string | null>(null);
  const [showList, setShowList] = useState(false);
  const nextTerminalN = useRef(1);

  // Inside the terminal section, "system-log" is the default tab
  const activeTerminalId = activeShellId ?? 'system-log';

  // Panel height — resizable via the top drag handle (VS Code style),
  // persisted across sessions.
  const [panelHeight, setPanelHeight] = useState(() => {
    const saved = parseInt(localStorage.getItem('panel.height') || '', 10);
    return Number.isFinite(saved) ? saved : 200;
  });
  const dragStart = useRef<{ y: number; height: number } | null>(null);

  const addShell = useCallback(() => {
    const n = nextTerminalN.current++;
    const id = `term-${Date.now()}-${n}`;
    setShells(prev => [...prev, { id, n, name: `Terminal ${n}` }]);
    setActiveSection('terminal');
    setActiveShellId(id);
    setShowList(false);
  }, []);

  const closeShell = (id: string) => {
    setShells(prev => prev.filter(s => s.id !== id));
    if (activeShellId === id) setActiveShellId(null); // fall back to System Log
    setShowList(false);
  };

  const handleShellReady = (id: string, shellName: string) => {
    setShells(prev =>
      prev.map(s => (s.id === id ? { ...s, name: `${shellName} ${s.n}` } : s)),
    );
  };

  const focusSection = (section: PanelSection, shellId: string | null) => {
    setActiveSection(section);
    setActiveShellId(shellId);
    setShowList(false);
    if (!bottomPanelOpen) toggleBottomPanel();
  };

  // Ctrl + ` toggles the panel; Ctrl + Shift + ` opens a new terminal
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.code !== 'Backquote') return;
      e.preventDefault();
      if (e.shiftKey) {
        addShell();
        if (!bottomPanelOpen) toggleBottomPanel();
      } else {
        toggleBottomPanel();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [toggleBottomPanel, bottomPanelOpen, addShell]);

  const startResize = (e: React.MouseEvent) => {
    e.preventDefault();
    dragStart.current = { y: e.clientY, height: panelHeight };
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
  };

  // Drag handler: growing the panel while the mouse moves up (top edge drag)
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const start = dragStart.current;
      if (!start) return;
      const next = Math.min(
        Math.max(start.height + (start.y - e.clientY), 100),
        Math.round(window.innerHeight * 0.75),
      );
      setPanelHeight(next);
    };
    const onUp = () => {
      dragStart.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  // Persist panel height across sessions
  useEffect(() => {
    localStorage.setItem('panel.height', String(panelHeight));
  }, [panelHeight]);

  const tabStyle = (active: boolean): CSSProperties => ({
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    height: 35,
    padding: '0 10px',
    fontSize: 12,
    color: active ? t.textPrimary : t.textMuted,
    background: 'transparent',
    border: 'none',
    borderBottom: active ? `2px solid ${t.accent}` : '2px solid transparent',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    flexShrink: 0,
  });

  const iconBtnStyle: CSSProperties = {
    width: 26,
    height: 24,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'transparent',
    border: 'none',
    color: t.textMuted,
    cursor: 'pointer',
    borderRadius: 3,
    flexShrink: 0,
  };

  return (
    <div
      style={{
        borderTop: `1px solid ${t.border}`,
        background: t.bgTabBar,
        display: 'flex',
        flexDirection: 'column',
        userSelect: 'none',
        position: 'relative',
      }}
    >
      {/* Drag handle at the top edge: pull up to see more messages */}
      <div
        onMouseDown={startResize}
        title="Drag to resize"
        style={{
          height: 4,
          flexShrink: 0,
          cursor: 'row-resize',
          transition: 'background 0.1s',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = t.accent; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
      />

      {/* Header row — tab strip */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          height: 35,
          minHeight: 35,
          padding: '0 8px 0 4px',
          overflow: 'hidden',
        }}
      >
        {/* ── Terminal group ── */}
        <button
          onClick={() => focusSection('terminal', null)}
          style={tabStyle(activeSection === 'terminal' && activeTerminalId === 'system-log')}
          title="Backend system logs"
        >
          <ScrollText size={13} />
          System Log
        </button>

        {shells.map(shell => (
          <div key={shell.id} style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
            <button
              onClick={() => focusSection('terminal', shell.id)}
              style={tabStyle(activeSection === 'terminal' && activeShellId === shell.id)}
              title={`${shell.name} — shell session`}
            >
              <Terminal size={13} />
              {shell.name}
            </button>
            <button
              onClick={() => closeShell(shell.id)}
              title={`Close ${shell.name}`}
              style={{
                ...iconBtnStyle,
                width: 20,
                height: 35,
                marginRight: 2,
                color: t.textDim,
              }}
            >
              <X size={11} />
            </button>
          </div>
        ))}

        <button
          onClick={addShell}
          title="New terminal (Ctrl+Shift+`)"
          style={{
            ...iconBtnStyle,
            width: 26,
            height: 35,
            color: t.textMuted,
          }}
        >
          <Plus size={14} />
        </button>

        {/* Separator before the other sections */}
        <div style={{ width: 1, height: 18, background: t.border, margin: '0 6px', flexShrink: 0 }} />

        {/* ── Other sections ── */}
        <button
          onClick={() => focusSection('execution', null)}
          style={tabStyle(activeSection === 'execution')}
        >
          <Play size={13} />
          Execution
        </button>
        <button
          onClick={() => focusSection('results', null)}
          style={tabStyle(activeSection === 'results')}
        >
          <FileText size={13} />
          Results
        </button>

        <div style={{ flex: 1 }} />

        {/* ── Terminal actions ── */}
        {activeSection === 'terminal' && (
          <>
            <button
              onClick={() => setShowList(v => !v)}
              title="Terminal list"
              style={iconBtnStyle}
            >
              <ChevronDown size={14} />
            </button>
            <button
              onClick={() => activeShellId && closeShell(activeShellId)}
              disabled={!activeShellId}
              title={activeShellId ? 'Kill active terminal' : 'No terminal to kill'}
              style={{ ...iconBtnStyle, opacity: activeShellId ? 1 : 0.35, cursor: activeShellId ? 'pointer' : 'not-allowed' }}
            >
              <Trash2 size={13} />
            </button>
          </>
        )}

        {/* Collapse/expand toggle */}
        <button
          onClick={toggleBottomPanel}
          title={bottomPanelOpen ? 'Close panel' : 'Open panel'}
          style={iconBtnStyle}
        >
          <ChevronDown size={14} style={{ transform: bottomPanelOpen ? 'rotate(180deg)' : 'none' }} />
        </button>
      </div>

      {/* Terminal list dropdown (VS Code-style) */}
      {showList && (
        <>
          <div style={{ position: 'fixed', inset: 0, zIndex: 40 }} onClick={() => setShowList(false)} />
          <div
            style={{
              position: 'absolute',
              right: 70,
              top: 36,
              zIndex: 41,
              minWidth: 200,
              background: t.bgDropdown,
              border: `1px solid ${t.border}`,
              borderRadius: 4,
              boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
              padding: '4px 0',
            }}
          >
            <div style={{ padding: '4px 12px', fontSize: 10, color: t.textDim, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Terminals
            </div>
            {([
              { id: 'system-log', label: 'System Log' },
              ...shells.map(s => ({ id: s.id, label: s.name })),
            ] as { id: string; label: string }[]).map(item => {
              const active = activeSection === 'terminal' && activeTerminalId === item.id;
              return (
                <div
                  key={item.id}
                  onClick={() => focusSection('terminal', item.id === 'system-log' ? null : item.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '4px 12px',
                    fontSize: 12,
                    cursor: 'pointer',
                    color: active ? t.textPrimary : t.textMuted,
                    background: active ? t.bgHover : 'transparent',
                  }}
                >
                  <span style={{ width: 12, display: 'inline-flex' }}>{active && <Check size={12} />}</span>
                  {item.label}
                </div>
              );
            })}
            <div style={{ borderTop: `1px solid ${t.border}`, marginTop: 4, paddingTop: 4 }}>
              <DropdownAction label="Add Terminal" onClick={addShell} t={t} />
              <DropdownAction
                label="Kill Terminal"
                disabled={!activeShellId}
                onClick={() => activeShellId && closeShell(activeShellId)}
                t={t}
              />
            </div>
          </div>
        </>
      )}

      {/* Content */}
      {bottomPanelOpen && (
        <div
          style={{
            height: panelHeight,
            minHeight: 100,
            background: t.bgContent,
            borderTop: `1px solid ${t.border}`,
            overflow: 'hidden',
          }}
        >
          {/* Terminal section: System Log + shell tabs (kept mounted so
              processes keep running while hidden, like VS Code) */}
          {activeSection === 'terminal' && (
            <>
              <div
                style={{
                  display: activeTerminalId === 'system-log' ? 'block' : 'none',
                  height: '100%',
                  overflow: 'auto',
                  padding: 12,
                  fontFamily: '"SF Mono", "Fira Code", monospace',
                  fontSize: 12,
                }}
              >
                <SystemLogContent t={t} />
              </div>
              {shells.map(shell => (
                <div
                  key={shell.id}
                  style={{
                    display: shell.id === activeTerminalId ? 'block' : 'none',
                    height: '100%',
                  }}
                >
                  <TerminalTab
                    terminalId={shell.id}
                    isActive={shell.id === activeTerminalId}
                    onReady={name => handleShellReady(shell.id, name)}
                  />
                </div>
              ))}
            </>
          )}

          {activeSection === 'execution' && (
            <div style={{ height: '100%', overflow: 'auto', padding: 12, fontFamily: '"SF Mono", "Fira Code", monospace', fontSize: 12 }}>
              <ExecutionContent t={t} />
            </div>
          )}

          {activeSection === 'results' && (
            <div style={{ height: '100%', overflow: 'auto', padding: 12 }}>
              <ResultsContent t={t} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DropdownAction({
  label,
  onClick,
  disabled,
  t,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  return (
    <div
      onClick={disabled ? undefined : onClick}
      style={{
        padding: '5px 12px',
        fontSize: 12,
        cursor: disabled ? 'not-allowed' : 'pointer',
        color: disabled ? t.textDim : t.textPrimary,
      }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = t.bgHover; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
    >
      {label}
    </div>
  );
}

// ── System Log content (live backend logs over SSE) ──────────

interface LogEntry {
  id: number;
  line: string;
}

function SystemLogContent({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const [lines, setLines] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);

  // Stream backend system logs (GET /api/debug/logs/stream). EventSource
  // auto-reconnects, and the server replays buffered history on connect.
  useEffect(() => {
    const es = new EventSource('/api/debug/logs/stream');
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        if (payload && payload.type === 'log') {
          setLines(prev => {
            const next = [...prev, { id: nextId.current++, line: String(payload.line) }];
            return next.length > 1000 ? next.slice(next.length - 1000) : next;
          });
        }
      } catch {
        // Ignore malformed frames
      }
    };
    return () => es.close();
  }, []);

  // Stick to the latest line whenever a new log arrives — unless the user
  // has scrolled up to read history. Scrolling back to the bottom re-engages
  // auto-scroll; the "Latest" button jumps there in one click.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && autoScroll) el.scrollTop = el.scrollHeight;
  }, [lines, autoScroll]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  const jumpToLatest = () => {
    setAutoScroll(true);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };

  // Rough level coloring on the formatted log line
  const colorFor = (line: string) => {
    if (line.includes(' - ERROR - ') || line.includes(' - CRITICAL - ')) return '#f48771';
    if (line.includes(' - WARNING - ')) return '#d9b75b';
    if (line.includes('uvicorn.access') || line.includes(' "GET ') || line.includes(' "POST ')) return '#8b949e';
    return '#d4d4d4';
  };

  return (
    <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Status + toolbar row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6, flexShrink: 0 }}>
        <span
          style={{
            display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
            background: connected ? '#22c55e' : '#f59e0b', flexShrink: 0,
          }}
        />
        <span style={{ fontSize: 11, color: connected ? '#22c55e' : '#f59e0b' }}>
          {connected ? 'backend connected' : 'connecting…'}
        </span>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => setLines([])}
          title="Clear logs"
          style={{
            display: 'flex', alignItems: 'center', gap: 4,
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: t.textMuted, fontSize: 11,
          }}
        >
          <X size={12} />
          Clear
        </button>
      </div>

      {/* Log lines */}
      <div ref={scrollRef} onScroll={handleScroll} style={{ flex: 1, overflow: 'auto' }}>
        {lines.length === 0 ? (
          <div style={{ color: t.textMuted, fontStyle: 'italic' }}>
            Waiting for backend logs… run a chat or any API call and the output appears here.
          </div>
        ) : (
          lines.map(entry => (
            <div key={entry.id} style={{ whiteSpace: 'pre', color: colorFor(entry.line) }}>
              {entry.line || '\u00A0'}
            </div>
          ))
        )}
      </div>

      {/* Shown only while scrolled up: jump back to the latest output */}
      {!autoScroll && (
        <button
          onClick={jumpToLatest}
          title="Jump to latest"
          style={{
            position: 'absolute', right: 14, bottom: 8,
            display: 'flex', alignItems: 'center', gap: 4,
            padding: '3px 9px', borderRadius: 4,
            background: t.bgHover, border: `1px solid ${t.border}`,
            color: t.textPrimary, fontSize: 11, cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
          }}
        >
          <ChevronDown size={12} />
          Latest
        </button>
      )}
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

// ── Results output (current process's result only) ────────

function ResultsContent({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const messages = useChatMessages();

  // Show only the latest assistant run: while it is streaming, display an
  // in-progress state (i.e. the previous result is cleared when a new run
  // starts); once it completes, show that run's final result.
  const assistants = messages.filter(m => m.role === 'assistant');
  const latest = assistants[assistants.length - 1];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {!latest ? (
        <p style={{ color: t.textMuted, fontStyle: 'italic', fontFamily: 'inherit', fontSize: 13 }}>
          No run yet. Trigger a chat or run a DeepAgent to see its result here.
        </p>
      ) : latest.streaming ? (
        <p style={{ color: '#4fc3f7', fontStyle: 'italic', fontFamily: 'inherit', fontSize: 13 }}>
          Run in progress… the result will appear here when it completes.
        </p>
      ) : (
        <div key={latest.id} style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6, flexShrink: 0 }}>
            <span style={{ fontSize: 11, color: t.textDim }}>
              {new Date(latest.ts).toLocaleTimeString()}
            </span>
            {latest.thinking && (
              <span style={{ fontSize: 11, color: '#f59e0b' }}>
                [has reasoning trace]
              </span>
            )}
            {latest.meta?.latencyMs != null && (
              <span style={{ fontSize: 11, color: t.textMuted }}>
                {latest.meta.latencyMs}ms
              </span>
            )}
            {latest.meta?.tokens != null && (
              <span style={{ fontSize: 11, color: t.textMuted }}>
                {latest.meta.tokens} tokens
              </span>
            )}
            {latest.toolCalls && latest.toolCalls.length > 0 && (
              <span style={{ fontSize: 11, color: t.textMuted }}>
                {latest.toolCalls.length} tool call{latest.toolCalls.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
          {/* Result box fills the panel; no leftover padding below */}
          <div style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            background: t.bgHover,
            border: `1px solid ${t.border}`,
            borderRadius: 4,
            padding: 10,
            fontSize: 13,
            color: t.textPrimary,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}>
            {latest.text || '(empty response)'}
          </div>
        </div>
      )}
    </div>
  );
}

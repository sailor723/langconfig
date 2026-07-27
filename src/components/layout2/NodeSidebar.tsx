/**
 * NodeSidebar — VS Code-style right panel.
 *
 * Always visible. Shows Chat by default.
 * When a canvas node is selected, a Properties tab appears.
 */
import { useState, useRef, useCallback, type ReactNode } from 'react';
import { useLayoutState } from './useLayout';
import { useLayoutTokens } from './tokens';
import { MessageSquare, Settings, X, Send, Trash2, Copy, Download, RotateCw, Brain, ChevronDown, ChevronRight } from 'lucide-react';
import { chatStore, useChatMessages } from './chatStore';
import apiClient from '../../lib/api-client';

/**
 * Strip <think>...</think> blocks from an LLM response.
 */
function extractThinking(text: string): { visible: string; thinking: string } {
  const re = /<think>([\s\S]*?)<\/think>/g;
  const parts: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) parts.push(m[1].trim());
  const visible = text.replace(re, '').trim();
  return { visible, thinking: parts.join('\n\n') };
}

interface NodeSidebarProps {
  children?: ReactNode;
}

const SIDEBAR_MIN_WIDTH = 240;
const SIDEBAR_MAX_WIDTH = 800;

export default function NodeSidebar({ children }: NodeSidebarProps) {
  const { rightPanelOpen, rightPanelContent, closeRightPanel, rightPanelWidth, setRightPanelWidth } = useLayoutState();
  const t = useLayoutTokens();
  const [localTab, setLocalTab] = useState<'chat' | 'properties'>('chat');

  // Resize drag (drag from the LEFT edge of the sidebar to resize wider/narrower)
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragRef.current = { startX: e.clientX, startWidth: rightPanelWidth };
    const handleMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      // Moving LEFT (negative dx) makes it wider
      const dx = dragRef.current.startX - ev.clientX;
      const next = Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, dragRef.current.startWidth + dx));
      setRightPanelWidth(next);
    };
    const handleUp = () => {
      dragRef.current = null;
      document.removeEventListener('mousemove', handleMove);
      document.removeEventListener('mouseup', handleUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', handleMove);
    document.addEventListener('mouseup', handleUp);
    document.body.style.cursor = 'ew-resize';
    document.body.style.userSelect = 'none';
  }, [rightPanelWidth, setRightPanelWidth]);

  // When a node is selected (rightPanelContent set), switch to Properties tab
  const activeTab = rightPanelContent ? 'properties' : localTab;

  const tabs: { id: 'chat' | 'properties'; label: string; icon: React.ReactNode }[] = [
    { id: 'chat', label: 'Chat', icon: <MessageSquare size={13} /> },
    ...(rightPanelContent ? [{ id: 'properties' as const, label: 'Properties', icon: <Settings size={13} /> }] : []),
  ];

  return (
    <div style={{ display: 'flex', flexShrink: 0 }}>
      {/* Resize handle (left edge of the right sidebar) */}
      <div
        onMouseDown={handleResizeStart}
        title="Drag to resize"
        style={{
          width: 4,
          cursor: 'ew-resize',
          background: 'transparent',
          flexShrink: 0,
        }}
        onMouseEnter={e => { e.currentTarget.style.background = t.border; }}
        onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
      />
      <div
        style={{
          width: rightPanelWidth,
          minWidth: rightPanelWidth,
          background: t.bgSidebar,
          borderLeft: `1px solid ${t.border}`,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          userSelect: 'none',
        }}
      >
      {/* ── Tab bar ────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          height: 35,
          padding: '0 8px',
          borderBottom: `1px solid ${t.border}`,
          gap: 0,
        }}
      >
        {tabs.map(tab => {
          const isActive = tab.id === activeTab;
          return (
            <button
              key={tab.id}
              onClick={() => {
                setLocalTab(tab.id);
                if (tab.id === 'properties' && !rightPanelOpen) {
                  // Already handled by rightPanelContent
                }
              }}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                height: 35,
                padding: '0 10px',
                fontSize: 12,
                color: isActive ? t.textPrimary : t.textMuted,
                background: 'transparent',
                border: 'none',
                borderBottom: isActive ? `2px solid ${t.accent}` : '2px solid transparent',
                cursor: 'pointer',
              }}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}

        <div style={{ flex: 1 }} />

        {/* Close button (only when properties/child content shown) */}
        {rightPanelContent && (
          <button
            onClick={closeRightPanel}
            title="Close"
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
            <X size={14} />
          </button>
        )}
      </div>

      {/* ── Content ─────────────────────────────────── */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {activeTab === 'properties' && (children ?? <DefaultNodePanel />)}
        {activeTab === 'chat' && <ChatSidebar t={t} />}
      </div>
      </div>
    </div>
  );
}

// ── Chat sidebar content ────────────────────────────────

function ChatSidebar({ t }: { t: ReturnType<typeof useLayoutTokens> }) {
  const messages = useChatMessages();
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setSending(true);
    const sessionId = chatStore.getSessionId();
    const agentId = chatStore.getAgentId();
    if (sessionId && agentId) {
      // Use SSE streaming when agent + session are available
      await chatStore.sendStreamMessage(agentId, text);
    } else if (sessionId) {
      // Fallback to blocking POST for sessions without agent context
      try {
        const startedAt = Date.now();
        const res = await apiClient.post('/api/chat/message', {
          session_id: sessionId,
          message: text,
        });
        const data = res.data || {};
        const rawText = data.message ?? data.response ?? JSON.stringify(data, null, 2);
        const { visible, thinking } = extractThinking(rawText);
        const metrics = data.metrics;
        chatStore.add({
          role: 'assistant',
          text: visible,
          thinking: thinking || undefined,
          activity: data.subagent_activity ?? undefined,
          meta: {
            tokens: metrics?.total_tokens,
            toolCalls: metrics?.tool_calls,
            latencyMs: Date.now() - startedAt,
          },
        });
      } catch (err: any) {
        const detail = err?.response?.data?.detail ?? err?.response?.data ?? {};
        chatStore.add({
          role: 'system',
          text: `// Error: ${err?.message ?? 'unknown'}\n${typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2)}`,
        });
      }
    } else {
      // No active session — warn user
      chatStore.add({
        role: 'system',
        text: '⚠️ No active session. Click ▶ Run on a DeepAgent first.',
      });
    }
    setSending(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* ── Toolbar ── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        height: 28,
        padding: '0 10px',
        borderBottom: `1px solid ${t.border}`,
        fontSize: 11,
        color: t.textMuted,
        flexShrink: 0,
      }}>
        <span>{messages.length} {messages.length === 1 ? 'message' : 'messages'}</span>
        {messages.length > 0 && (
          <button
            onClick={() => chatStore.clear()}
            title="Clear chat"
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '2px 6px', fontSize: 11,
              background: 'transparent', border: 'none',
              color: t.textMuted, cursor: 'pointer',
            }}
          >
            <Trash2 size={11} /> clear
          </button>
        )}
      </div>

      {/* ── Messages ── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
        {messages.length === 0 && (
          <p style={{ color: t.textMuted, fontSize: 12, fontStyle: 'italic', padding: 8 }}>
            Open a DeepAgent and click <strong style={{ color: t.textPrimary }}>▶ Run</strong> to start chatting.
          </p>
        )}
        {messages.map((msg) => (
          <ChatBubble key={msg.id} msg={msg} />
        ))}
      </div>

      {/* ── Input ── */}
      <div style={{ display: 'flex', gap: 6, padding: 8, borderTop: `1px solid ${t.border}`, flexShrink: 0 }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSend(); }}
          placeholder="Type a message..."
          style={{
            flex: 1,
            padding: '5px 8px',
            fontSize: 12,
            background: t.bgInput,
            border: `1px solid ${t.border}`,
            color: t.textPrimary,
            outline: 'none',
            borderRadius: 3,
          }}
        />
        <button
          onClick={handleSend}
          disabled={sending}
          title={sending ? 'Sending…' : 'Send'}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '0 10px',
            fontSize: 12,
            background: t.accent,
            color: '#fff',
            border: 'none',
            cursor: sending ? 'not-allowed' : 'pointer',
            opacity: sending ? 0.6 : 1,
            borderRadius: 3,
          }}
        >
          <Send size={12} />
        </button>
      </div>
    </div>
  );
}

// ── Chat bubble (message + thinking + actions) ──────────

interface ChatBubbleProps {
  msg: import('./chatStore').ChatMessage;
}

function ChatBubble({ msg }: ChatBubbleProps) {
  const t = useLayoutTokens();
  const isUser = msg.role === 'user';
  const isAssistant = msg.role === 'assistant';
  const isSystem = msg.role === 'system';
  const [showThinking, setShowThinking] = useState(false);
  const [copied, setCopied] = useState(false);

  const fullText = (msg.thinking ? `[thinking]\n${msg.thinking}\n\n[/thinking]\n` : '') + msg.text;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(msg.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // fallback
      const ta = document.createElement('textarea');
      ta.value = msg.text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };

  const handleDownload = () => {
    const blob = new Blob([fullText], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `chat-${new Date(msg.ts).toISOString().replace(/[:.]/g, '-')}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleRerun = () => {
    if (!msg.text) return;
    const sessionId = chatStore.getSessionId();
    if (!sessionId) {
      chatStore.add({ role: 'system', text: '⚠️ No active session. Click ▶ Run on a DeepAgent first.' });
      return;
    }
    // Find the preceding user message
    const all = chatStore.getMessages();
    const idx = all.findIndex(m => m.id === msg.id);
    let userPrompt = msg.text;
    for (let i = idx - 1; i >= 0; i--) {
      if (all[i].role === 'user') { userPrompt = all[i].text; break; }
    }
    // Strip the "[AgentName]" prefix added by DeepAgentEditor
    const cleanPrompt = userPrompt.replace(/^\[[^\]]+\]\s*/, '');
    chatStore.add({ role: 'user', text: cleanPrompt });
    chatStore.add({ role: 'system', text: '🔄 Re-running…' });
    apiClient.post('/api/chat/message', { session_id: sessionId, message: cleanPrompt })
      .then(res => {
        const data = res.data || {};
        const rawText = data.message ?? data.response ?? JSON.stringify(data, null, 2);
        const { visible, thinking } = extractThinking(rawText);
        chatStore.add({
          role: 'assistant',
          text: visible,
          thinking: thinking || undefined,
          activity: data.subagent_activity ?? undefined,
          meta: {
            tokens: data.metrics?.total_tokens,
            toolCalls: data.metrics?.tool_calls,
            latencyMs: 0,
          },
        });
      })
      .catch(err => {
        chatStore.add({ role: 'system', text: `// Re-run failed: ${err?.message ?? 'unknown'}` });
      });
  };

  return (
    <div style={{
      alignSelf: isUser ? 'flex-end' : 'flex-start',
      maxWidth: '95%',
      display: 'flex',
      flexDirection: 'column',
      gap: 4,
    }}>
      <div style={{
        padding: '8px 10px',
        background: isUser ? t.accent : isSystem ? '#5a1d1d' : t.bgHover,
        color: isUser || isSystem ? '#fff' : t.textPrimary,
        fontSize: 12,
        borderRadius: 4,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}>
        <div style={{ fontSize: 10, opacity: 0.7, marginBottom: 4 }}>
          {isUser ? 'You' : isSystem ? 'System' : 'Agent'} · {new Date(msg.ts).toLocaleTimeString()}
        </div>

        {/* Thinking block (collapsible) */}
        {isAssistant && msg.thinking && (
          <div style={{ marginBottom: 8 }}>
            <button
              onClick={() => setShowThinking(v => !v)}
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '3px 8px',
                fontSize: 10,
                background: 'rgba(255,255,255,0.05)',
                color: '#a78bfa',
                border: '1px solid rgba(167,139,250,0.3)',
                borderRadius: 3,
                cursor: 'pointer',
                fontWeight: 500,
              }}
            >
              <Brain size={10} />
              {showThinking ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
              Thinking ({msg.thinking.length} chars)
            </button>
            {showThinking && (
              <pre style={{
                marginTop: 6,
                padding: 8,
                background: 'rgba(167,139,250,0.08)',
                border: '1px solid rgba(167,139,250,0.2)',
                borderRadius: 3,
                color: '#c4b5fd',
                fontFamily: '"SF Mono", "Fira Code", monospace',
                fontSize: 11,
                lineHeight: 1.5,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                maxHeight: 240,
                overflow: 'auto',
              }}>
                {msg.thinking}
              </pre>
            )}
          </div>
        )}

        <div>{msg.text}</div>

        {msg.meta && (
          <div style={{ fontSize: 10, opacity: 0.6, marginTop: 4 }}>
            {msg.meta.tokens != null && `${msg.meta.tokens} tokens`}
            {msg.meta.toolCalls != null && ` · ${msg.meta.toolCalls} tools`}
            {msg.meta.latencyMs != null && ` · ${(msg.meta.latencyMs / 1000).toFixed(1)}s`}
          </div>
        )}
      </div>

      {/* Action row (only for assistant messages) */}
      {isAssistant && (
        <div style={{ display: 'flex', gap: 4, paddingLeft: 4 }}>
          <ActionBtn onClick={handleCopy} title={copied ? 'Copied!' : 'Copy'} t={t}>
            <Copy size={10} /> {copied ? 'Copied' : 'Copy'}
          </ActionBtn>
          <ActionBtn onClick={handleDownload} title="Download as Markdown" t={t}>
            <Download size={10} /> Save
          </ActionBtn>
          <ActionBtn onClick={handleRerun} title="Re-run with same prompt" t={t}>
            <RotateCw size={10} /> Re-run
          </ActionBtn>
        </div>
      )}
    </div>
  );
}

function ActionBtn({
  onClick, title, children, t,
}: { onClick: () => void; title: string; children: React.ReactNode; t: ReturnType<typeof useLayoutTokens> }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      title={title}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 3,
        padding: '2px 6px',
        fontSize: 10,
        background: hover ? t.bgHover : 'transparent',
        color: t.textMuted,
        border: `1px solid ${hover ? t.border : 'transparent'}`,
        borderRadius: 3,
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  );
}

// ── Default node properties panel ───────────────────────

function DefaultNodePanel() {
  const t = useLayoutTokens();
  return (
    <div style={{ padding: 10 }}>
      <div style={{ marginBottom: 12 }}>
        <label style={{ display: 'block', fontSize: 11, color: t.textMuted, marginBottom: 4 }}>
          Model
        </label>
        <select
          style={{
            width: '100%',
            padding: '5px 8px',
            border: `1px solid ${t.border}`,
            background: t.bgInput,
            color: t.textPrimary,
            fontSize: 12,
          }}
        >
          <option>GPT-4o</option>
          <option>GPT-4o-mini</option>
          <option>Claude 3.5 Sonnet</option>
        </select>
      </div>
    </div>
  );
}

/**
 * ModelPlaygroundTab — single-model chat tester rendered as a workspace tab.
 *
 * Reuses the existing apiClient.modelInvoke endpoint (POST /api/models/invoke).
 * Tab variant of the Settings ModelPlaygroundModal — same calls, no modal chrome.
 */
import { useState, useRef, useEffect } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import type { Tab } from './useLayout';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  error?: string;
}

interface Props {
  tab: Tab;
}

export default function ModelPlaygroundTab({ tab }: Props) {
  const t = useLayoutTokens();
  const { modelId, modelName, provider } = tab.data ?? {};
  const [message, setMessage] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [stream, setStream] = useState(true);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  const handleSend = async () => {
    const msg = message.trim();
    if (!msg || isLoading) return;
    setChatHistory(h => [...h, { role: 'user', content: msg }]);
    setMessage('');
    setIsLoading(true);
    try {
      const res = await apiClient.modelInvoke({
        model: modelId,
        message: msg,
        system_prompt: systemPrompt || undefined,
        temperature,
        max_tokens: maxTokens,
        stream,
      });
      const data = res?.data || {};
      const reply = data.response ?? data.message ?? data.content ?? JSON.stringify(data, null, 2);
      setChatHistory(h => [...h, {
        role: 'assistant',
        content: reply,
        usage: data.usage ?? null,
      }]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'unknown';
      setChatHistory(h => [...h, { role: 'assistant', content: `(error) ${detail}`, error: detail }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClear = () => setChatHistory([]);

  // ── Styles ──
  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '6px 8px',
    background: t.bgContent,
    border: `1px solid ${t.border}`,
    borderRadius: 4,
    color: t.textPrimary,
    fontSize: 12,
    outline: 'none',
    boxSizing: 'border-box',
  };
  const labelStyle: React.CSSProperties = {
    fontSize: 10,
    color: t.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    display: 'block',
    marginBottom: 3,
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: t.bgContent,
      color: t.textPrimary,
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 16px',
        borderBottom: `1px solid ${t.border}`,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}>
        <span style={{
          width: 24, height: 24, borderRadius: 4,
          background: '#10b981',
          color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 12, textTransform: 'uppercase',
        }}>
          {provider?.[0]?.toUpperCase() || '?'}
        </span>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{modelName}</div>
          <div style={{ fontSize: 11, color: t.textMuted }}>{modelId} · {provider}</div>
        </div>
        <div style={{ flex: 1 }} />
        <button
          onClick={handleClear}
          style={{
            background: 'transparent',
            border: `1px solid ${t.border}`,
            color: t.textMuted,
            fontSize: 11,
            padding: '4px 10px',
            borderRadius: 3,
            cursor: 'pointer',
          }}
        >
          Clear
        </button>
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Left: settings panel */}
        <div style={{
          width: 240,
          padding: 12,
          borderRight: `1px solid ${t.border}`,
          overflowY: 'auto',
          flexShrink: 0,
        }}>
          <label style={labelStyle}>System prompt</label>
          <textarea
            value={systemPrompt}
            onChange={e => setSystemPrompt(e.target.value)}
            rows={4}
            style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', minHeight: 60 }}
          />
          <div style={{ marginTop: 10 }}>
            <label style={labelStyle}>
              Temperature: {temperature.toFixed(2)}
            </label>
            <input
              type="range" min={0} max={2} step={0.05}
              value={temperature}
              onChange={e => setTemperature(parseFloat(e.target.value))}
              style={{ width: '100%', accentColor: '#10b981' }}
            />
          </div>
          <div style={{ marginTop: 10 }}>
            <label style={labelStyle}>Max tokens</label>
            <input
              type="number" min={64} max={32000}
              value={maxTokens}
              onChange={e => setMaxTokens(parseInt(e.target.value) || 2048)}
              style={inputStyle}
            />
          </div>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginTop: 10,
            fontSize: 12,
            color: t.textPrimary,
            cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={stream}
              onChange={e => setStream(e.target.checked)}
              style={{ accentColor: '#10b981' }}
            />
            Stream response
          </label>
        </div>

        {/* Right: chat */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
            {chatHistory.length === 0 && (
              <div style={{ color: t.textMuted, fontStyle: 'italic', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                Send a message to test {modelName}.
              </div>
            )}
            {chatHistory.map((m, i) => (
              <div
                key={i}
                style={{
                  marginBottom: 12,
                  padding: '8px 12px',
                  borderRadius: 6,
                  background: m.role === 'user' ? 'rgba(16,185,129,0.12)' : t.bgHover,
                  borderLeft: `3px solid ${m.error ? '#ef5350' : m.role === 'user' ? '#10b981' : t.accent}`,
                  fontSize: 13,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                <div style={{
                  fontSize: 10,
                  color: t.textMuted,
                  textTransform: 'uppercase',
                  marginBottom: 4,
                  display: 'flex',
                  justifyContent: 'space-between',
                }}>
                  <span>{m.role === 'user' ? 'You' : modelName}</span>
                  {m.usage && (
                    <span>
                      {m.usage.total_tokens} tok
                      ({m.usage.input_tokens}↑ / {m.usage.output_tokens}↓)
                    </span>
                  )}
                </div>
                {m.content}
              </div>
            ))}
            {isLoading && (
              <div style={{ color: t.textMuted, fontSize: 12, fontStyle: 'italic' }}>
                {stream ? 'streaming...' : 'thinking...'}
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
          {/* Composer */}
          <div style={{
            padding: 12,
            borderTop: `1px solid ${t.border}`,
            display: 'flex',
            gap: 8,
          }}>
            <textarea
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={`Message ${modelName}... (Cmd/Ctrl+Enter to send)`}
              rows={3}
              style={{
                ...inputStyle,
                resize: 'vertical',
                fontFamily: 'inherit',
                flex: 1,
              }}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !message.trim()}
              style={{
                alignSelf: 'flex-end',
                background: '#10b981',
                color: '#fff',
                border: 'none',
                borderRadius: 4,
                padding: '6px 16px',
                fontSize: 12,
                fontWeight: 600,
                cursor: isLoading || !message.trim() ? 'not-allowed' : 'pointer',
                opacity: isLoading || !message.trim() ? 0.5 : 1,
                height: 32,
              }}
            >
              {isLoading ? '...' : 'Send'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
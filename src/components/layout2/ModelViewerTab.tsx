/**
 * ModelViewerTab — single-model chat playground as a workspace tab.
 *
 * Mirrors the existing ModelPlaygroundModal UX 1:1:
 * - Preset chips at the bottom (auto-fill prompt + apply per-chip settings)
 * - Collapsible left-rail with system prompt, temperature, max tokens,
 *   top P, freq/presence penalty, stop sequences, JSON/Tools/Stream toggles,
 *   Image URL with live preview, last-usage readout
 * - User bubbles right-aligned, assistant left-aligned, error red bubble
 * - Enter (no shift) sends, Shift+Enter newline
 * - Animated typing dots while loading
 * - Auto-focus input on open
 * - Auto-clear stale image when not on Vision preset
 *
 * Reuses existing backend: POST /api/models/invoke
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import type { Tab } from './useLayout';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  model?: string;
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  error?: string;
}

interface Props { tab: Tab }

/** Provider → color map (matches existing Modal) */
const PROVIDER_COLOR: Record<string, string> = {
  openai: '#10b981', anthropic: '#f97316', deepseek: '#3b82f6',
  google: '#a78bfa', agnes: '#ec4899', minimax: '#0ea5e9',
  glm: '#facc15', qwen: '#6366f1', kimi: '#64748b',
  ollama: '#94a3b8',
};

/** Mini-logo chip (first-letter colored badge) */
function MiniLogo({ provider, size = 18 }: { provider: string; size?: number }) {
  const p = (provider || '').toLowerCase();
  const color = PROVIDER_COLOR[p] || '#94a3b8';
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: 4,
      fontWeight: 700,
      width: size, height: size,
      background: color,
      color: '#fff',
      fontSize: size * 0.55,
    }}>
      {p[0]?.toUpperCase() || '?'}
    </span>
  );
}

/** Preset chip definitions — match the previous Modal's behaviour exactly.
 *  When `image` is set, the modal set imageUrl and sent the request;
 *  when no image is passed, imageUrl was cleared (avoiding stale URL poisoning). */
const PRESET_CHIPS: Array<{
  label: string;
  text: string;
  jsonMode?: boolean;
  tools?: boolean;
  stream?: boolean;
  image?: string;
}> = [
  { label: '👋 Greet',  text: 'Hi! Please introduce yourself in one sentence.' },
  { label: '🧮 Math',   text: 'What is 17 × 23 + √144? Please show your calculation.' },
  { label: '{} JSON',   text: 'Return Shanghai city info as JSON with fields: city, country, population.',
    jsonMode: true },
  { label: '🔧 Tools',  text: 'Look up the weather in Beijing and the current UTC time.',
    tools: true },
  { label: '🌐 Search', text: 'Search for the latest release date of DeepSeek V4.',
    tools: true },
  { label: '📡 Stream', text: 'Write a three-line poem about artificial intelligence.',
    stream: true },
  { label: '🖼 Vision', text: 'Please describe what you see in this image in detail.',
    image: 'https://raw.githubusercontent.com/gradio-app/gradio/main/test/test_files/bus.png' },
  { label: '🧠 Reasoning', text: 'All roses are flowers. Some flowers wilt quickly. Can we conclude that "some roses wilt quickly"? Walk through the logic step by step.' },
];

export default function ModelViewerTab({ tab }: Props) {
  const t = useLayoutTokens();
  const { modelId, modelName, provider } = tab.data ?? {};

  // ── Chat state ──
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [message, setMessage] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('You are a helpful assistant.');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(4096);
  const [topP, setTopP] = useState(1.0);
  const [frequencyPenalty, setFrequencyPenalty] = useState(0);
  const [presencePenalty, setPresencePenalty] = useState(0);
  const [stopSeq, setStopSeq] = useState('');
  const [jsonMode, setJsonMode] = useState(false);
  const [toolsEnabled, setToolsEnabled] = useState(false);
  const [streamEnabled, setStreamEnabled] = useState(false);
  const [imageUrl, setImageUrl] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(true);

  const chatScrollRef = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Reset on model change
  useEffect(() => {
    setChatHistory([]);
    setMessage('');
    setIsLoading(false);
    setJsonMode(false);
    setToolsEnabled(false);
    setStreamEnabled(false);
    setImageUrl('');
  }, [modelId]);

  // Auto-scroll to the latest message — scoped to the chat container only.
  // Use scrollIntoView with block:'end' on the chat-end sentinel; this
  // scrolls the nearest scrollable ancestor (the chat container), NOT
  // the page — preventing the page from scrolling down.
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      const end = chatEndRef.current;
      if (end) {
        end.scrollIntoView({ block: 'end' });
      }
    });
    const t = window.setTimeout(() => {
      const end = chatEndRef.current;
      if (end) end.scrollIntoView({ block: 'end' });
    }, 80);
    return () => { cancelAnimationFrame(id); clearTimeout(t); };
  }, [chatHistory, isLoading]);
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 100);
  }, [modelId]);

  const provColor = PROVIDER_COLOR[(provider || '').toLowerCase()] || '#94a3b8';
  // provColor is kept for header chip rendering — used via t.accent for buttons

  /** Send a chat message — central handler */
  const handleSend = useCallback(async () => {
    const msg = message.trim();
    if (!modelId?.trim() || !msg || isLoading) return;

    setIsLoading(true);
    const newUserMsg: ChatMessage = { role: 'user', content: msg };
    setChatHistory(prev => [...prev, newUserMsg]);
    setMessage('');

    try {
      // Build single-message call with conversation history concatenated
      const historyText = chatHistory.length === 0
        ? msg
        : chatHistory.map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`).join('\n') + `\nUser: ${msg}`;

      const stopArr = stopSeq.trim() ? stopSeq.split(',').map(s => s.trim()).filter(Boolean) : undefined;

      const res = await apiClient.modelInvoke({
        model: modelId,
        message: historyText,
        system_prompt: systemPrompt || undefined,
        temperature,
        max_tokens: maxTokens,
        top_p: topP < 1 ? topP : undefined,
        frequency_penalty: frequencyPenalty !== 0 ? frequencyPenalty : undefined,
        presence_penalty: presencePenalty !== 0 ? presencePenalty : undefined,
        image_url: imageUrl.trim() || undefined,
        tool_names: toolsEnabled ? ['get_weather', 'get_current_time', 'search_web', 'calculate'] : undefined,
        stop: stopArr,
        json_mode: jsonMode,
        tools: toolsEnabled,
        stream: streamEnabled,
      });

      const data = (res as any).data ?? res;
      setChatHistory(prev => [...prev, {
        role: 'assistant',
        content: data.content ?? data.message ?? '',
        model: data.model ?? modelId,
        usage: data.usage ?? null,
      }]);
    } catch (err: any) {
      setChatHistory(prev => [...prev, {
        role: 'assistant',
        content: '',
        error: err?.response?.data?.detail || err?.message || 'Request failed',
      }]);
    } finally {
      setIsLoading(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [modelId, message, isLoading, chatHistory, systemPrompt, temperature, maxTokens,
      topP, frequencyPenalty, presencePenalty, stopSeq, jsonMode, toolsEnabled, streamEnabled, imageUrl]);

  const handleClear = () => {
    setChatHistory([]);
    setMessage('');
  };

  /** Apply a preset — fills the input and runs it */
  const runPreset = (preset: typeof PRESET_CHIPS[number]) => {
    if (isLoading) return;
    // Apply preset-specific settings
    setJsonMode(!!preset.jsonMode);
    setToolsEnabled(!!preset.tools);
    setStreamEnabled(!!preset.stream);
    setImageUrl(preset.image || '');  // CLEAR if no image, otherwise set the URL
    setMessage(preset.text);
    setTimeout(() => handleSend(), 50);
  };

  const lastUsage = chatHistory.filter(m => m.usage).slice(-1)[0]?.usage;

  // ── Styles ──
  const inputBase: React.CSSProperties = {
    width: '100%',
    padding: '5px 8px',
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
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    color: t.textMuted,
    display: 'block',
    marginBottom: 3,
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', background: t.bgContent, color: t.textPrimary,
      overflow: 'hidden',
    }}>
      {/* ── Header ── */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 16px',
        borderBottom: `1px solid ${t.border}`,
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 6,
            background: 'linear-gradient(135deg, #3b82f6, #06b6d4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <MiniLogo provider={provider || ''} size={20} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h2 style={{
                margin: 0, fontSize: 15, fontWeight: 600,
                color: t.textPrimary,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                Playground
              </h2>
              <span style={{
                fontSize: 10, padding: '2px 8px', borderRadius: 999,
                fontWeight: 500,
                background: t.bgHover,
                color: t.textMuted,
              }}>
                {provider}
              </span>
            </div>
            <p style={{
              margin: '2px 0 0', fontSize: 11,
              fontFamily: 'monospace',
              color: t.textMuted,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {modelName} ({modelId})
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button
            onClick={handleClear}
            style={{
              fontSize: 11, padding: '4px 10px',
              border: `1px solid ${t.border}`,
              borderRadius: 4,
              color: t.textMuted,
              background: 'transparent',
              cursor: 'pointer',
            }}
          >
            Clear
          </button>
        </div>
      </div>

      {/* ── Body: split into advanced params (left) + chat (right) ── */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Advanced params — collapsible */}
        <div style={{
          width: showAdvanced ? 280 : 40,
          borderRight: `1px solid ${t.border}`,
          display: 'flex',
          flexDirection: 'column',
          transition: 'width 0.2s ease',
          flexShrink: 0,
          overflowY: showAdvanced ? 'auto' : 'hidden',
        }}>
          <button
            onClick={() => setShowAdvanced(v => !v)}
            style={{
              padding: '10px 0',
              background: 'transparent',
              border: 'none',
              color: t.textMuted,
              fontSize: 12,
              cursor: 'pointer',
              flexShrink: 0,
            }}
            title={showAdvanced ? 'Hide params' : 'Show params'}
          >
            {showAdvanced ? '◀' : '▶'}
            {showAdvanced && <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>Params</span>}
          </button>

          {showAdvanced && (
            <div style={{ padding: '0 12px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={labelStyle}>System prompt</label>
              <textarea
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                rows={5}
                style={{ ...inputBase, resize: 'vertical', fontFamily: 'inherit', minHeight: 60 }}
              />

              <Slider label="Temperature" value={temperature.toFixed(1)}
                min={0} max={2} step={0.1}
                onChange={v => setTemperature(parseFloat(v))} t={t} />
              <Slider label="Max tokens" value={maxTokens.toLocaleString()}
                min={256} max={131072} step={256}
                onChange={v => setMaxTokens(parseInt(v))} t={t} />
              <Slider label="Top P" value={topP.toFixed(2)}
                min={0} max={1} step={0.05}
                onChange={v => setTopP(parseFloat(v))} t={t} />
              <Slider label="Frequency penalty" value={frequencyPenalty.toFixed(1)}
                min={-2} max={2} step={0.1}
                onChange={v => setFrequencyPenalty(parseFloat(v))} t={t} />
              <Slider label="Presence penalty" value={presencePenalty.toFixed(1)}
                min={-2} max={2} step={0.1}
                onChange={v => setPresencePenalty(parseFloat(v))} t={t} />

              <label style={labelStyle}>Stop sequences</label>
              <input
                value={stopSeq}
                onChange={e => setStopSeq(e.target.value)}
                placeholder="e.g. END, STOP, ###"
                style={inputBase}
              />

              {/* Toggles */}
              <div style={{
                display: 'flex', flexDirection: 'column', gap: 6,
                paddingTop: 8,
                borderTop: `1px solid ${t.border}`,
              }}>
                <Toggle label="JSON mode" checked={jsonMode} onChange={setJsonMode}
                  hint="Force valid JSON output" t={t} />
                <Toggle label="Tool calling" checked={toolsEnabled} onChange={setToolsEnabled}
                  hint="Enable function tools" t={t} />
                <Toggle label="Streaming" checked={streamEnabled} onChange={setStreamEnabled}
                  hint="Stream response chunks" t={t} />
              </div>

              {/* Image URL with preview */}
              <label style={labelStyle}>Image URL (vision)</label>
              <input
                value={imageUrl}
                onChange={e => setImageUrl(e.target.value)}
                placeholder="https://...png/jpg/webp"
                style={inputBase}
              />
              {imageUrl.trim() && (
                <img
                  src={imageUrl}
                  alt="preview"
                  style={{
                    marginTop: 4, maxHeight: 96, borderRadius: 4,
                    border: `1px solid ${t.border}`,
                  }}
                  onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                />
              )}

              {/* Last usage panel */}
              {lastUsage && (
                <div style={{
                  fontSize: 10, padding: 8,
                  borderRadius: 4,
                  background: t.bgHover,
                  color: t.textMuted,
                  marginTop: 8,
                }}>
                  <div style={{
                    fontWeight: 700, marginBottom: 4,
                    color: t.textPrimary, textTransform: 'uppercase', letterSpacing: 0.5,
                  }}>
                    Last usage
                  </div>
                  <div>in: {lastUsage.input_tokens?.toLocaleString()}</div>
                  <div>out: {lastUsage.output_tokens?.toLocaleString()}</div>
                  <div>total: {lastUsage.total_tokens?.toLocaleString()}</div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Chat area ── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, minHeight: 0, overflow: 'hidden' }}>
          <div ref={chatScrollRef} style={{ flex: 1, overflowY: 'auto', padding: 14, minHeight: 0, maxHeight: '100%' }}>
            {chatHistory.length === 0 && (
              <div style={{
                color: t.textMuted, fontStyle: 'italic',
                fontSize: 13, textAlign: 'center', marginTop: 40,
              }}>
                Send a message or click a preset to test {modelName}.
              </div>
            )}

            {chatHistory.map((m, i) => (
              <div
                key={i}
                style={{
                  display: 'flex',
                  justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start',
                  marginBottom: 10,
                }}
              >
                <div style={{
                  maxWidth: '80%',
                  padding: '8px 14px',
                  borderRadius: 14,
                  fontSize: 13,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  background: m.role === 'user'
                    ? t.accent
                    : m.error
                      ? 'rgba(239,68,68,0.1)'
                      : t.bgHover,
                  color: m.role === 'user' ? '#fff' : m.error ? '#ef4444' : t.textPrimary,
                  border: m.role === 'assistant' && !m.error ? `1px solid ${t.border}` : 'none',
                }}>
                  {m.error ? `⚠ ${m.error}` : m.content}
                  {m.usage && (
                    <div style={{ fontSize: 10, marginTop: 4, opacity: 0.7 }}>
                      in {m.usage.input_tokens} · out {m.usage.output_tokens} · {m.usage.total_tokens}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {isLoading && (
              <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                <div style={{
                  padding: '10px 14px', borderRadius: 14,
                  background: t.bgHover,
                  color: t.textMuted,
                  fontSize: 13,
                  display: 'inline-flex', gap: 4,
                }}>
                  <span style={{ animation: 'bounce 1s infinite' }}>●</span>
                  <span style={{ animation: 'bounce 1s infinite', animationDelay: '0.15s' }}>●</span>
                  <span style={{ animation: 'bounce 1s infinite', animationDelay: '0.3s' }}>●</span>
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* ── Preset chips row ── */}
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: 6,
            padding: '8px 12px',
            borderTop: `1px solid ${t.border}`,
            background: t.bgSidebar,
          }}>
            <span style={{
              fontSize: 10, fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: 0.5,
              color: t.textMuted,
              marginRight: 4,
              alignSelf: 'center',
            }}>
              Try:
            </span>
            {PRESET_CHIPS.map(p => (
              <button
                key={p.label}
                onClick={() => runPreset(p)}
                disabled={isLoading}
                style={{
                  fontSize: 10,
                  padding: '3px 9px',
                  borderRadius: 999,
                  fontWeight: 500,
                  border: `1px solid ${t.accent}`,
                  color: t.textPrimary,
                  background: 'transparent',
                  cursor: isLoading ? 'not-allowed' : 'pointer',
                  opacity: isLoading ? 0.5 : 1,
                }}
                onMouseEnter={e => { e.currentTarget.style.background = `${t.accent}20`; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* ── Input ── */}
          <div style={{
            padding: 10,
            borderTop: `1px solid ${t.border}`,
            display: 'flex', gap: 8,
          }}>
            <textarea
              ref={inputRef}
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Type a message…"
              rows={2}
              disabled={isLoading}
              style={{
                ...inputBase,
                flex: 1,
                resize: 'none',
                fontFamily: 'inherit',
                fontSize: 13,
                padding: '8px 12px',
              }}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !message.trim() || !modelId?.trim()}
              style={{
                padding: '0 16px',
                borderRadius: 6,
                fontSize: 13,
                fontWeight: 600,
                border: 'none',
                background: t.accent,
                color: '#fff',
                cursor: isLoading || !message.trim() || !modelId?.trim() ? 'not-allowed' : 'pointer',
                opacity: isLoading || !message.trim() || !modelId?.trim() ? 0.5 : 1,
              }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Sub-components ── */
function Slider({ label, value, min, max, step, onChange, t }: {
  label: string; value: string; min: number; max: number; step: number;
  onChange: (v: string) => void;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 3,
      }}>
        <label style={{
          fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: 0.5, color: t.textMuted,
        }}>
          {label}
        </label>
        <span style={{ fontSize: 11, fontFamily: 'monospace', color: t.textMuted }}>
          {value}
        </span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={Number(value)}
        onChange={e => onChange(e.target.value)}
        style={{ width: '100%', accentColor: t.accent }}
      />
    </div>
  );
}

function Toggle({ label, hint, checked, onChange, t }: {
  label: string; hint: string; checked: boolean;
  onChange: (v: boolean) => void;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  return (
    <div
      onClick={() => onChange(!checked)}
      title={hint}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        cursor: 'pointer', padding: '2px 0',
      }}
    >
      <span style={{
        fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: 0.5, color: t.textMuted,
      }}>
        {label}
      </span>
      <span style={{
        position: 'relative',
        display: 'inline-block',
        width: 30, height: 16, borderRadius: 999,
        background: checked ? t.accent : t.border,
        transition: 'background 0.15s',
      }}>
        <span style={{
          position: 'absolute',
          top: 2, left: checked ? 16 : 2,
          width: 12, height: 12,
          borderRadius: '50%',
          background: '#fff',
          transition: 'left 0.15s',
        }} />
      </span>
    </div>
  );
}
/**
 * ModelViewerTab — playground tab for chatting with a single model.
 *
 * Opens when the user clicks Play on a model card. Mirrors the previous
 * ModelPlaygroundModal UX: preset prompt chips, advanced sampling params,
 * multimodal image upload, JSON mode, tool call toggle, streaming.
 *
 * Reuses existing backend endpoints:
 *   - POST /api/models/invoke       (single-shot chat)
 *   - GET  /api/settings/models     (model capability lookup for vision)
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

interface Props { tab: Tab }

/** Provider → color map */
const PROVIDER_COLOR: Record<string, string> = {
  openai: '#10b981', anthropic: '#f97316', deepseek: '#3b82f6',
  google: '#a78bfa', agnes: '#ec4899', minimax: '#0ea5e9',
  glm: '#facc15', qwen: '#6366f1', kimi: '#64748b',
  ollama: '#94a3b8',
};

/** Preset prompts — each maps to a chip that, when clicked, fills the input
 *  and applies the right settings (json mode, tools, stream, image). */
const PRESETS: Array<{
  label: string;
  prompt: string;
  jsonMode?: boolean;
  tools?: boolean;
  stream?: boolean;
  image?: boolean;
  reasoning?: boolean;
}> = [
  { label: '👋 Greet',  prompt: 'Hi! Please introduce yourself in one sentence.' },
  { label: '🧮 Math',   prompt: 'What is 17 × 23 + √144? Please show your calculation.' },
  { label: '{} JSON',   prompt: 'Return Shanghai city info as JSON with fields: city, country, population.',
    jsonMode: true },
  { label: '🔧 Tools',  prompt: 'Look up the weather in Beijing and the current UTC time.',
    tools: true },
  { label: '🌐 Search', prompt: 'Search for the latest release date of DeepSeek V4.',
    tools: true },
  { label: '📡 Stream', prompt: 'Write a three-line poem about artificial intelligence.',
    stream: true },
  { label: '🖼 Vision', prompt: 'Please describe what you see in this image in detail.',
    image: true },
  { label: '🧠 Reasoning', prompt: 'All roses are flowers. Some flowers wilt quickly. Can we conclude that "some roses wilt quickly"? Walk through the logic step by step.',
    reasoning: true },
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
  const [showAdvanced, setShowAdvanced] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const provColor = PROVIDER_COLOR[provider?.toLowerCase() || ''] || '#94a3b8';

  // Reset on tab model change
  useEffect(() => {
    setChatHistory([]);
    setMessage('');
    setIsLoading(false);
    setJsonMode(false);
    setToolsEnabled(false);
    setStreamEnabled(false);
    setImageUrl('');
  }, [modelId]);

  // Auto-scroll
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  /** Run a preset: fill the input and apply its flags */
  const runPreset = (preset: typeof PRESETS[number]) => {
    setMessage(preset.prompt);
    setJsonMode(!!preset.jsonMode);
    setToolsEnabled(!!preset.tools);
    setStreamEnabled(!!preset.stream);
    // Auto-send after a tick so the state flushes
    setTimeout(() => {
      void doSend(preset.prompt, {
        jsonMode: !!preset.jsonMode,
        tools: !!preset.tools,
        stream: !!preset.stream,
        image: !!preset.image,
      });
    }, 50);
  };

  /** Send a chat message — central chat handler */
  const doSend = async (
    msg: string,
    overrides: { jsonMode?: boolean; tools?: boolean; stream?: boolean; image?: boolean } = {},
  ) => {
    if (!msg.trim() || isLoading) return;
    setChatHistory(h => [...h, { role: 'user', content: msg }]);
    setIsLoading(true);
    try {
      const useStream = overrides.stream ?? streamEnabled;
      const useTools = overrides.tools ?? toolsEnabled;
      const useJson = overrides.jsonMode ?? jsonMode;
      const stopArr = stopSeq.trim() ? stopSeq.split(',').map(s => s.trim()).filter(Boolean) : undefined;

      // Build the prompt — concatenate history for non-streaming
      const historyText = chatHistory.length === 0
        ? msg
        : chatHistory.map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`).join('\n')
          + `\nUser: ${msg}`;

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
        tool_names: useTools ? ['get_weather', 'get_current_time', 'search_web', 'calculate'] : undefined,
        stop: stopArr,
        json_mode: useJson,
        tools: useTools,
        stream: useStream,
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

  const handleSend = () => {
    const msg = message.trim();
    if (!msg) return;
    setMessage('');
    void doSend(msg);
  };

  const handleClear = () => setChatHistory([]);

  // ── Styles ──
  const labelStyle: React.CSSProperties = {
    fontSize: 10,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    color: t.textMuted,
    display: 'block',
    marginBottom: 3,
  };
  const inputStyle: React.CSSProperties = {
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

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: t.bgContent,
      color: t.textPrimary,
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '12px 16px',
        borderBottom: `1px solid ${t.border}`,
        flexShrink: 0,
      }}>
        <span style={{
          width: 32, height: 32, borderRadius: 6,
          background: provColor, color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 16, textTransform: 'uppercase',
        }}>
          {provider?.[0]?.toUpperCase() || '?'}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>{modelName}</div>
          <div style={{
            fontSize: 11, color: t.textMuted,
            fontFamily: 'monospace',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {modelId} · {provider}
          </div>
        </div>
        <button
          onClick={handleClear}
          style={{
            background: 'transparent',
            border: `1px solid ${t.border}`,
            color: t.textMuted,
            fontSize: 11,
            padding: '4px 10px',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          Clear
        </button>
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Left: advanced params (collapsible) */}
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
              display: 'flex', alignItems: 'center', justifyContent: 'center',
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
          </button>
          {showAdvanced && (
            <div style={{ padding: '0 14px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={labelStyle}>System prompt</label>
              <textarea
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                rows={5}
                style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', minHeight: 60 }}
              />
              <label style={labelStyle}>Temperature: {temperature.toFixed(2)}</label>
              <input
                type="range" min={0} max={2} step={0.05}
                value={temperature}
                onChange={e => setTemperature(parseFloat(e.target.value))}
                style={{ width: '100%', accentColor: provColor }}
              />
              <label style={labelStyle}>Max tokens: {maxTokens.toLocaleString()}</label>
              <input
                type="range" min={256} max={131072} step={256}
                value={maxTokens}
                onChange={e => setMaxTokens(parseInt(e.target.value))}
                style={{ width: '100%', accentColor: provColor }}
              />
              <label style={labelStyle}>Top P: {topP.toFixed(2)}</label>
              <input
                type="range" min={0} max={1} step={0.05}
                value={topP}
                onChange={e => setTopP(parseFloat(e.target.value))}
                style={{ width: '100%', accentColor: provColor }}
              />
              <label style={labelStyle}>Frequency penalty: {frequencyPenalty.toFixed(2)}</label>
              <input
                type="range" min={-2} max={2} step={0.1}
                value={frequencyPenalty}
                onChange={e => setFrequencyPenalty(parseFloat(e.target.value))}
                style={{ width: '100%', accentColor: provColor }}
              />
              <label style={labelStyle}>Presence penalty: {presencePenalty.toFixed(2)}</label>
              <input
                type="range" min={-2} max={2} step={0.1}
                value={presencePenalty}
                onChange={e => setPresencePenalty(parseFloat(e.target.value))}
                style={{ width: '100%', accentColor: provColor }}
              />
              <label style={labelStyle}>Stop sequences (comma-separated)</label>
              <input
                value={stopSeq}
                onChange={e => setStopSeq(e.target.value)}
                placeholder="e.g. ###, END"
                style={inputStyle}
              />
              <label style={labelStyle}>Image URL (vision test)</label>
              <input
                value={imageUrl}
                onChange={e => setImageUrl(e.target.value)}
                placeholder="https://..."
                style={inputStyle}
              />
              <ToggleRow label="JSON mode" hint="Force structured JSON output" checked={jsonMode}
                onChange={setJsonMode} t={t} />
              <ToggleRow label="Tools" hint="Enable function calling (weather, time, search, calc)" checked={toolsEnabled}
                onChange={setToolsEnabled} t={t} />
              <ToggleRow label="Stream" hint="Stream tokens as they're generated" checked={streamEnabled}
                onChange={setStreamEnabled} t={t} />
            </div>
          )}
        </div>

        {/* Right: chat area */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {/* Preset chips */}
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
            padding: '10px 14px',
            borderBottom: `1px solid ${t.border}`,
            background: t.bgSidebar,
          }}>
            <span style={{
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
              color: t.textMuted, marginRight: 4,
              alignSelf: 'center',
            }}>
              Presets:
            </span>
            {PRESETS.map(p => (
              <button
                key={p.label}
                onClick={() => runPreset(p)}
                disabled={isLoading}
                style={{
                  fontSize: 10,
                  padding: '3px 9px',
                  borderRadius: 999,
                  fontWeight: 500,
                  border: `1px solid ${provColor}`,
                  color: t.textPrimary,
                  background: 'transparent',
                  cursor: isLoading ? 'not-allowed' : 'pointer',
                  opacity: isLoading ? 0.5 : 1,
                }}
                onMouseEnter={e => { e.currentTarget.style.background = `${provColor}22`; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Messages */}
          <div style={{ flex: 1, overflowY: 'auto', padding: 14 }}>
            {chatHistory.length === 0 && (
              <div style={{ color: t.textMuted, fontStyle: 'italic', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
                Click a preset chip or type a message to chat with {modelName}.
              </div>
            )}
            {chatHistory.map((m, i) => (
              <div
                key={i}
                style={{
                  marginBottom: 12,
                  padding: '8px 12px',
                  borderRadius: 6,
                  background: m.role === 'user' ? `${provColor}20` : t.bgHover,
                  borderLeft: `3px solid ${m.error ? '#ef5350' : m.role === 'user' ? provColor : t.accent}`,
                  fontSize: 13,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                <div style={{
                  fontSize: 10, color: t.textMuted, textTransform: 'uppercase',
                  marginBottom: 4, display: 'flex', justifyContent: 'space-between',
                }}>
                  <span>{m.role === 'user' ? 'You' : modelName}</span>
                  {m.usage && (
                    <span>
                      {m.usage.total_tokens} tok ({m.usage.input_tokens}↑ / {m.usage.output_tokens}↓)
                    </span>
                  )}
                </div>
                {m.content}
              </div>
            ))}
            {isLoading && (
              <div style={{ color: t.textMuted, fontSize: 12, fontStyle: 'italic' }}>
                {streamEnabled ? 'streaming...' : 'thinking...'}
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Composer */}
          <div style={{
            padding: 12, borderTop: `1px solid ${t.border}`,
            display: 'flex', gap: 8,
          }}>
            <textarea
              ref={inputRef}
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
              style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', flex: 1 }}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !message.trim()}
              style={{
                alignSelf: 'flex-end',
                background: provColor,
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

/* ── Toggle row (left-side panel) ── */
function ToggleRow({ label, hint, checked, onChange, t }: {
  label: string; hint: string; checked: boolean;
  onChange: (v: boolean) => void;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  return (
    <div
      onClick={() => onChange(!checked)}
      style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        cursor: 'pointer', padding: '4px 0',
      }}
      title={hint}
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
/**
 * ModelViewerTab — workspace tab showing the FULL model detail card.
 *
 * The sidebar (ModelCardsSidebar) is just a browser that lists models.
 * All detailed info — capabilities badges, system prompt editor, set-default
 * button, test runner — lives here, in the editor area as a tab.
 *
 * Reuses existing backend APIs:
 *   - GET  /api/settings/models               (model catalog)
 *   - GET  /api/settings/model-defaults       (current default)
 *   - POST /api/settings/model-defaults       (set default)
 *   - POST /api/models/invoke                 (test runner)
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import type { Tab } from './useLayout';

const LS_KEY_DEFAULT = 'langconfig.defaultModel';

interface ModelInfo {
  model_id: string;
  display_name: string;
  provider: string;
  capabilities: Record<string, any>;
  is_active: boolean;
}

const PROVIDER_COLOR: Record<string, string> = {
  openai: '#10b981', anthropic: '#f59e0b', deepseek: '#3b82f6',
  google: '#a855f7', agnes: '#ec4899', minimax: '#06b6d4',
  glm: '#eab308', qwen: '#6366f1', kimi: '#71717a', ollama: '#94a3b8',
};

interface Props { tab: Tab }

export default function ModelViewerTab({ tab }: Props) {
  const t = useLayoutTokens();
  const { modelId, modelName, provider } = tab.data ?? {};

  const [model, setModel] = useState<ModelInfo | null>(null);
  const [isDefault, setIsDefault] = useState(false);
  const [savingDefault, setSavingDefault] = useState(false);
  const [defaultMsg, setDefaultMsg] = useState<string | null>(null);

  // Test runner state
  const [systemPrompt, setSystemPrompt] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [stream, setStream] = useState(true);
  const [message, setMessage] = useState('');
  const [chatHistory, setChatHistory] = useState<Array<{role: 'user'|'assistant'; content: string; usage?: any; error?: string}>>([]);
  const [isLoading, setIsLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Load model details
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.listAvailableModels();
        const cloud: ModelInfo[] = Array.isArray(res?.data?.cloud_models) ? res.data.cloud_models : [];
        const local = Array.isArray(res?.data?.local_models) ? res.data.local_models : [];
        // Find by model_id (cloud) or name (local)
        const found = cloud.find(m => m.model_id === modelId)
          ?? local.find((m: any) => m.name === modelId);
        if (!cancelled && found) setModel(found as ModelInfo);

        // Check default status
        try {
          const def = await apiClient.getModelDefaults();
          const cur = def?.data?.primary_model;
          if (!cancelled) setIsDefault(cur === modelId);
        } catch {}
      } catch (err: any) {
        console.warn('Failed to load model info:', err);
      }
    })();
    return () => { cancelled = true; };
  }, [modelId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  const handleSetDefault = useCallback(async () => {
    setSavingDefault(true);
    setDefaultMsg(null);
    try {
      await apiClient.updateModelDefaultsSettings({ primary_model: modelId });
      localStorage.setItem(LS_KEY_DEFAULT, modelId);
      setIsDefault(true);
      setDefaultMsg('Saved as default');
      setTimeout(() => setDefaultMsg(null), 2000);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'unknown';
      setDefaultMsg(`Failed: ${detail}`);
    } finally {
      setSavingDefault(false);
    }
  }, [modelId]);

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
      setChatHistory(h => [...h, { role: 'assistant', content: reply, usage: data.usage }]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'unknown';
      setChatHistory(h => [...h, { role: 'assistant', content: `(error) ${detail}`, error: detail }]);
    } finally {
      setIsLoading(false);
    }
  };

  const caps = model?.capabilities ?? {};
  const provColor = PROVIDER_COLOR[provider?.toLowerCase() || ''] || '#888';

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

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: t.bgContent, color: t.textPrimary, overflow: 'hidden',
    }}>
      {/* Header card — provider badge + name + id + default toggle */}
      <div style={{
        padding: '14px 18px',
        borderBottom: `1px solid ${t.border}`,
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        flexShrink: 0,
      }}>
        <div style={{
          width: 40, height: 40, borderRadius: 6,
          background: provColor, color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 18, textTransform: 'uppercase',
        }}>
          {provider?.[0]?.toUpperCase() || '?'}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 16, fontWeight: 600 }}>{modelName}</div>
          <div style={{ fontSize: 12, color: t.textMuted }}>{modelId} · {provider}</div>
        </div>
        <button
          onClick={handleSetDefault}
          disabled={savingDefault || isDefault}
          title={isDefault ? 'Already default' : 'Set as primary default model'}
          style={{
            background: isDefault ? '#10b981' : 'transparent',
            border: `1px solid ${isDefault ? '#10b981' : t.border}`,
            color: isDefault ? '#fff' : t.textMuted,
            fontSize: 12, fontWeight: 600,
            padding: '6px 14px',
            borderRadius: 4,
            cursor: isDefault ? 'default' : 'pointer',
            opacity: savingDefault ? 0.6 : 1,
          }}
          onMouseEnter={e => { if (!isDefault) { e.currentTarget.style.color = '#f59e0b'; e.currentTarget.style.borderColor = '#f59e0b'; }}}
          onMouseLeave={e => { if (!isDefault) { e.currentTarget.style.color = t.textMuted; e.currentTarget.style.borderColor = t.border; }}}
        >
          {isDefault ? '★ Default' : savingDefault ? 'Saving…' : '★ Set Default'}
        </button>
      </div>
      {defaultMsg && (
        <div style={{
          padding: '4px 18px', fontSize: 11,
          color: defaultMsg.startsWith('Failed') ? '#ef5350' : '#10b981',
          borderBottom: `1px solid ${t.border}`,
        }}>
          {defaultMsg}
        </div>
      )}

      {/* Capability badges row */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 6,
        padding: '10px 18px',
        borderBottom: `1px solid ${t.border}`,
      }}>
        {caps.streaming && <Badge label="Streaming" color="#3b82f6" />}
        {caps.tools && <Badge label="Tools" color="#a855f7" />}
        {caps.structured_output && <Badge label="Structured Output" color="#0ea5e9" />}
        {caps.vision && <Badge label="Vision" color="#10b981" />}
        {caps.audio && <Badge label="Audio" color="#06b6d4" />}
        {caps.video && <Badge label="Video" color="#8b5cf6" />}
        {caps.thinking && <Badge label="Thinking" color="#f59e0b" />}
        {caps.max_context && <Badge label={`${(caps.max_context / 1000).toFixed(0)}k context`} color="#64748b" />}
        {caps.max_output && <Badge label={`${(caps.max_output / 1000).toFixed(0)}k max out`} color="#64748b" />}
        {caps.open_source && <Badge label="Open Source" color="#22c55e" />}
        {caps.release && <Badge label={`Released ${caps.release}`} color="#94a3b8" />}
        {caps.input_price != null && caps.output_price != null && (
          <Badge label={`$${caps.input_price}/$${caps.output_price} per 1M tok`} color="#94a3b8" />
        )}
        {caps.speed_tps && <Badge label={`${caps.speed_tps} tok/s`} color="#94a3b8" />}
        {caps.strength && <Badge label={caps.strength} color="#94a3b8" />}
      </div>

      {/* Test runner — chat area */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Left: settings */}
        <div style={{
          width: 260,
          padding: 14,
          borderRight: `1px solid ${t.border}`,
          overflowY: 'auto',
          flexShrink: 0,
        }}>
          <h3 style={{
            fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: 0.5, color: t.textMuted, margin: '0 0 8px 0',
          }}>
            Test Runner
          </h3>
          <label style={{ fontSize: 10, color: t.textMuted, textTransform: 'uppercase', display: 'block', marginBottom: 3 }}>
            System prompt
          </label>
          <textarea
            value={systemPrompt}
            onChange={e => setSystemPrompt(e.target.value)}
            rows={4}
            style={{ ...inputStyle, resize: 'vertical', fontFamily: 'inherit', minHeight: 60 }}
          />
          <div style={{ marginTop: 10 }}>
            <label style={{ fontSize: 10, color: t.textMuted, textTransform: 'uppercase', display: 'block', marginBottom: 3 }}>
              Temperature: {temperature.toFixed(2)}
            </label>
            <input
              type="range" min={0} max={2} step={0.05}
              value={temperature}
              onChange={e => setTemperature(parseFloat(e.target.value))}
              style={{ width: '100%', accentColor: provColor }}
            />
          </div>
          <div style={{ marginTop: 10 }}>
            <label style={{ fontSize: 10, color: t.textMuted, textTransform: 'uppercase', display: 'block', marginBottom: 3 }}>
              Max tokens
            </label>
            <input
              type="number" min={64} max={32000}
              value={maxTokens}
              onChange={e => setMaxTokens(parseInt(e.target.value) || 2048)}
              style={inputStyle}
            />
          </div>
          <label style={{
            display: 'flex', alignItems: 'center', gap: 6,
            marginTop: 12, fontSize: 12, color: t.textPrimary, cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={stream}
              onChange={e => setStream(e.target.checked)}
              style={{ accentColor: provColor }}
            />
            Stream response
          </label>
        </div>

        {/* Right: chat */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <div style={{ flex: 1, overflowY: 'auto', padding: 14 }}>
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
            padding: 12, borderTop: `1px solid ${t.border}`,
            display: 'flex', gap: 8,
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

function Badge({ label, color }: { label: string; color: string }) {
  const t = useLayoutTokens();
  return (
    <span style={{
      fontSize: 10, fontWeight: 600,
      padding: '3px 8px',
      borderRadius: 4,
      background: `${color}22`,
      color,
      border: `1px solid ${color}44`,
    }}>
      {label}
    </span>
  );
}
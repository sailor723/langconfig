/**
 * Model Playground Modal — single-model chat tester.
 * Opens via the Play button on any model card.
 * Uses apiClient.modelInvoke for LLM calls.
 */

import { useState, useRef, useEffect } from 'react';
import { apiClient } from '@/lib/api-client';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  model?: string;
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  error?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  modelId: string;
  modelName: string;
  provider: string;
}

// Inline mini-logo (first-letter colored chip)
function MiniLogo({ provider, size = 18 }: { provider: string; size?: number }) {
  const p = provider.toLowerCase();
  const colorMap: Record<string, string> = {
    openai: '#10b981', anthropic: '#f97316', deepseek: '#3b82f6',
    google: '#a78bfa', agnes: '#ec4899', minimax: '#0ea5e9',
    glm: '#facc15', qwen: '#6366f1', kimi: '#64748b',
    ollama: '#94a3b8',
  };
  return (
    <span
      className="inline-flex items-center justify-center rounded-md font-bold"
      style={{
        width: size, height: size,
        backgroundColor: colorMap[p] || '#94a3b8',
        color: '#fff', fontSize: size * 0.55,
      }}
    >
      {p[0]?.toUpperCase() || '?'}
    </span>
  );
}

function Toggle({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="flex items-center justify-between cursor-pointer" title={hint}>
      <span className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>
        {label}
      </span>
      <span
        onClick={() => onChange(!checked)}
        className="relative inline-block w-8 h-4 rounded-full transition-colors"
        style={{ backgroundColor: checked ? 'var(--color-primary)' : 'var(--color-border)' }}
      >
        <span
          className="absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all"
          style={{ left: checked ? '18px' : '2px' }}
        />
      </span>
    </label>
  );
}

function PresetChip({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="text-[10px] px-2 py-1 rounded-full font-medium border transition-colors hover:brightness-125 disabled:opacity-50"
      style={{
        borderColor: 'var(--color-primary)',
        color: 'var(--color-text-primary)',
        backgroundColor: 'rgba(99,102,241,0.08)',
      }}
    >
      {label}
    </button>
  );
}

export default function ModelPlaygroundModal({ open, onClose, modelId, modelName, provider }: Props) {
  const [message, setMessage] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('You are a helpful assistant.');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(4096);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Extended sampling params
  const [topP, setTopP] = useState(1.0);
  const [frequencyPenalty, setFrequencyPenalty] = useState(0);
  const [presencePenalty, setPresencePenalty] = useState(0);
  const [stopSeq, setStopSeq] = useState('');
  const [jsonMode, setJsonMode] = useState(false);
  const [toolsEnabled, setToolsEnabled] = useState(false);
  const [streamEnabled, setStreamEnabled] = useState(false);

  // Image for multimodal test
  const [imageUrl, setImageUrl] = useState('');

  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Reset state when modal opens for a new model
  useEffect(() => {
    if (open) {
      setChatHistory([]);
      setMessage('');
      setIsLoading(false);
    }
  }, [open, modelId]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  // ESC to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Focus input on open
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

  const handleSend = async () => {
    const msg = message.trim();
    if (!modelId.trim() || !msg || isLoading) return;

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
  };

  const handleClear = () => {
    setChatHistory([]);
    setMessage('');
  };

  const runPreset = (text: string, opts?: { jsonMode?: boolean; tools?: boolean; stream?: boolean; image?: string }) => {
    if (isLoading) return;
    // Apply preset-specific settings
    if (opts?.jsonMode) setJsonMode(true); else setJsonMode(false);
    if (opts?.tools) setToolsEnabled(true); else if (!opts?.image) setToolsEnabled(false);
    if (opts?.stream) setStreamEnabled(true); else setStreamEnabled(false);
    if (opts?.image) setImageUrl(opts.image); else if (!text.includes('image')) { /* keep existing */ }
    setMessage(text);
    // Auto-send after a tick so state updates flush
    setTimeout(() => handleSend(), 50);
  };

  if (!open) return null;

  const lastUsage = chatHistory.filter(m => m.usage).slice(-1)[0]?.usage;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0,0,0,0.6)' }}
      onClick={onClose}
    >
      <div
        className="flex flex-col rounded-2xl shadow-2xl overflow-hidden border"
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          borderColor: 'var(--color-border)',
          width: 'min(960px, 95vw)',
          height: 'min(720px, 92vh)',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={`inline-flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-r from-blue-500 to-cyan-500`}
              style={{ color: '#fff' }}
            >
              <MiniLogo provider={provider} size={18} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
                  Playground
                </h2>
                <span
                  className="text-[10px] px-2 py-0.5 rounded-full font-medium"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    color: 'var(--color-text-muted)',
                  }}
                >
                  {provider}
                </span>
              </div>
              <p className="text-xs font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
                {modelName} ({modelId})
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleClear}
              className="text-xs px-2.5 py-1 rounded-lg border"
              style={{
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-muted)',
              }}
            >
              Clear
            </button>
            <button
              onClick={onClose}
              className="text-xs px-2.5 py-1 rounded-lg"
              style={{
                backgroundColor: 'var(--color-input-background)',
                color: 'var(--color-text-muted)',
              }}
              title="Close (ESC)"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Body — split: advanced params (collapsible) + chat */}
        <div className="flex flex-1 overflow-hidden">
          {/* Side: Advanced params */}
          <div
            className={`flex flex-col gap-3 p-4 border-r overflow-y-auto scrollbar-thin transition-all ${
              showAdvanced ? 'w-64' : 'w-10'
            }`}
            style={{ borderColor: 'var(--color-border)' }}
          >
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="text-[10px] font-semibold uppercase tracking-widest flex items-center gap-1"
              style={{ color: 'var(--color-text-muted)' }}
              title={showAdvanced ? 'Hide params' : 'Show params'}
            >
              {showAdvanced ? '◀' : '▶'}
              {showAdvanced && 'Params'}
            </button>

            {showAdvanced && (
              <>
                {/* System prompt */}
                <div>
                  <label className="text-[10px] font-semibold uppercase tracking-widest mb-1 block" style={{ color: 'var(--color-text-muted)' }}>
                    System Prompt
                  </label>
                  <textarea
                    value={systemPrompt}
                    onChange={e => setSystemPrompt(e.target.value)}
                    rows={5}
                    className="w-full rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1"
                    style={{
                      backgroundColor: 'var(--color-input-background)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text-primary)',
                    }}
                  />
                </div>

                {/* Temperature */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>
                      Temperature
                    </label>
                    <span className="text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>{temperature.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    value={temperature}
                    onChange={e => setTemperature(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                    style={{ backgroundColor: 'var(--color-border)', accentColor: 'var(--color-primary)' }}
                  />
                </div>

                {/* Max Tokens */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>
                      Max Tokens
                    </label>
                    <span className="text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>{maxTokens.toLocaleString()}</span>
                  </div>
                  <input
                    type="range"
                    min="256"
                    max="131072"
                    step="256"
                    value={maxTokens}
                    onChange={e => setMaxTokens(parseInt(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                    style={{ backgroundColor: 'var(--color-border)', accentColor: 'var(--color-primary)' }}
                  />
                </div>

                {/* Top P */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }} title="Nucleus sampling">
                      Top P
                    </label>
                    <span className="text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>{topP.toFixed(2)}</span>
                  </div>
                  <input type="range" min="0" max="1" step="0.05" value={topP}
                    onChange={e => setTopP(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                    style={{ backgroundColor: 'var(--color-border)', accentColor: 'var(--color-primary)' }} />
                </div>

                {/* Frequency Penalty */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>
                      Freq Penalty
                    </label>
                    <span className="text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>{frequencyPenalty.toFixed(1)}</span>
                  </div>
                  <input type="range" min="-2" max="2" step="0.1" value={frequencyPenalty}
                    onChange={e => setFrequencyPenalty(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                    style={{ backgroundColor: 'var(--color-border)', accentColor: 'var(--color-primary)' }} />
                </div>

                {/* Presence Penalty */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>
                      Pres Penalty
                    </label>
                    <span className="text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>{presencePenalty.toFixed(1)}</span>
                  </div>
                  <input type="range" min="-2" max="2" step="0.1" value={presencePenalty}
                    onChange={e => setPresencePenalty(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                    style={{ backgroundColor: 'var(--color-border)', accentColor: 'var(--color-primary)' }} />
                </div>

                {/* Stop Sequences */}
                <div>
                  <label className="text-[10px] font-semibold uppercase tracking-widest mb-1 block" style={{ color: 'var(--color-text-muted)' }} title="Comma-separated stop sequences">
                    Stop Sequences
                  </label>
                  <input type="text" value={stopSeq} onChange={e => setStopSeq(e.target.value)}
                    placeholder="e.g. END, STOP, ###"
                    className="w-full rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1"
                    style={{ backgroundColor: 'var(--color-input-background)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)' }} />
                </div>

                {/* Toggles: JSON mode, Tools, Stream */}
                <div className="space-y-1.5 pt-1 border-t" style={{ borderColor: 'var(--color-border)' }}>
                  <Toggle label="JSON mode" checked={jsonMode} onChange={setJsonMode} hint="Force valid JSON output" />
                  <Toggle label="Tool calling" checked={toolsEnabled} onChange={setToolsEnabled} hint="Enable function tools" />
                  <Toggle label="Streaming" checked={streamEnabled} onChange={setStreamEnabled} hint="Stream response chunks" />
                </div>

                {/* Image URL — multimodal */}
                <div>
                  <label className="text-[10px] font-semibold uppercase tracking-widest mb-1 block" style={{ color: 'var(--color-text-muted)' }} title="Send an image with your message for multimodal models">
                    Image URL (vision)
                  </label>
                  <input type="text" value={imageUrl} onChange={e => setImageUrl(e.target.value)}
                    placeholder="https://...png/jpg/webp"
                    className="w-full rounded-lg px-2 py-1.5 text-xs focus:outline-none focus:ring-1"
                    style={{ backgroundColor: 'var(--color-input-background)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)' }} />
                  {imageUrl.trim() && (
                    // eslint-disable-next-line jsx-a11y/img-redundant-alt
                    <img src={imageUrl} alt="preview" className="mt-1 max-h-24 rounded border"
                      style={{ borderColor: 'var(--color-border)' }}
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }} />
                  )}
                </div>

                {lastUsage && (
                  <div className="text-[10px] p-2 rounded-lg"
                    style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-muted)' }}>
                    <div className="font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>Last usage</div>
                    <div>in: {lastUsage.input_tokens?.toLocaleString()}</div>
                    <div>out: {lastUsage.output_tokens?.toLocaleString()}</div>
                    <div>total: {lastUsage.total_tokens?.toLocaleString()}</div>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Chat area */}
          <div className="flex-1 flex flex-col min-w-0">
            <div className="flex-1 overflow-y-auto p-4 space-y-3 scrollbar-thin">
              {chatHistory.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center"
                  style={{ color: 'var(--color-text-muted)' }}>
                  <span className="material-symbols-outlined text-5xl mb-2">chat</span>
                  <p className="text-sm">Send a message to test {modelName}</p>
                </div>
              )}

              {chatHistory.map((m, i) => (
                <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className="max-w-[80%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap"
                    style={{
                      backgroundColor: m.role === 'user'
                        ? 'var(--color-primary)'
                        : m.error
                          ? 'rgba(239,68,68,0.1)'
                          : 'var(--color-input-background)',
                      color: m.role === 'user' ? '#fff' : m.error ? '#ef4444' : 'var(--color-text-primary)',
                      border: m.role === 'assistant' && !m.error ? '1px solid var(--color-border)' : 'none',
                    }}
                  >
                    {m.error ? `⚠ ${m.error}` : m.content}
                    {m.usage && (
                      <div className="text-[10px] mt-1 opacity-70">
                        in {m.usage.input_tokens} · out {m.usage.output_tokens} · {m.usage.total_tokens}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {isLoading && (
                <div className="flex justify-start">
                  <div className="rounded-2xl px-4 py-2.5 text-sm"
                    style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-muted)' }}>
                    <span className="inline-flex gap-1">
                      <span className="animate-bounce">●</span>
                      <span className="animate-bounce" style={{ animationDelay: '0.15s' }}>●</span>
                      <span className="animate-bounce" style={{ animationDelay: '0.3s' }}>●</span>
                    </span>
                  </div>
                </div>
              )}
              <div ref={chatEndRef} />
            </div>

            {/* Preset chips — one-click samples */}
            <div className="border-t px-3 pt-2 pb-1 flex flex-wrap gap-1.5"
              style={{ borderColor: 'var(--color-border)' }}>
              <span className="text-[10px] uppercase tracking-widest mr-1 self-center"
                style={{ color: 'var(--color-text-muted)' }}>Try:</span>
              <PresetChip label="👋 Greeting" onClick={() => runPreset('Hi! Introduce yourself in one sentence.')} disabled={isLoading} />
              <PresetChip label="🧮 Math" onClick={() => runPreset('What is 17 * 23 + sqrt(144)?')} disabled={isLoading} />
              <PresetChip label="{} JSON" onClick={() => runPreset('Return JSON with keys: city, country, population for Tokyo', { jsonMode: true })} disabled={isLoading} />
              <PresetChip label="🔧 Tools" onClick={() => runPreset('What is the weather in Tokyo and the current time in UTC?', { tools: true })} disabled={isLoading} />
              <PresetChip label="🌐 Search" onClick={() => runPreset('Search the web for the latest DeepSeek V4 release date', { tools: true })} disabled={isLoading} />
              <PresetChip label="📡 Stream" onClick={() => runPreset('Write a 3-line poem about AI', { stream: true })} disabled={isLoading} />
              <PresetChip label="🖼 Vision" onClick={() => runPreset('What do you see in this image? Describe in detail.', {
                image: 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/1024px-Cat03.jpg'
              })} disabled={isLoading} />
              <PresetChip label="🇫🇷 Reason" onClick={() => runPreset('If all roses are flowers and some flowers fade quickly, can we conclude some roses fade quickly? Explain step by step.')} disabled={isLoading} />
            </div>

            {/* Input */}
            <div className="border-t p-3" style={{ borderColor: 'var(--color-border)' }}>
              <div className="flex gap-2">
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
                  className="flex-1 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-1 resize-none"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                  disabled={isLoading}
                />
                <button
                  onClick={handleSend}
                  disabled={isLoading || !message.trim() || !modelId.trim()}
                  className="px-4 rounded-xl text-sm font-medium transition-colors disabled:opacity-50"
                  style={{
                    backgroundColor: 'var(--color-primary)',
                    color: '#fff',
                  }}
                >
                  Send
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
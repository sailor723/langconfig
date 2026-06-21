import { useState, useRef, useEffect } from 'react';
import { apiClient } from '@/lib/api-client';
import { useAvailableModels } from '@/hooks/useAvailableModels';

type ModelProvider = string;

// Provider display helpers - built dynamically from API data
const PROVIDER_COLORS: Record<string, string> = {
  deepseek: 'from-blue-500 to-cyan-500',
  openai: 'from-emerald-500 to-teal-500',
  anthropic: 'from-orange-500 to-amber-500',
  google: 'from-violet-500 to-purple-500',
  agnes: 'from-pink-500 to-rose-500',
  glm: 'from-yellow-500 to-amber-500',
  minimax: 'from-cyan-500 to-sky-500',
  local: 'from-slate-500 to-gray-500',
};

const DEFAULT_PROVIDER_COLOR = 'from-indigo-500 to-blue-500';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  model?: string;
  usage?: { input_tokens: number; output_tokens: number; total_tokens: number } | null;
  error?: string;
}

export default function PlaygroundPage() {
  // Model selection
  const [provider, setProvider] = useState<ModelProvider>('deepseek');
  const [selectedLocalModelId, setSelectedLocalModelId] = useState<string>('');
  const [customModel, setCustomModel] = useState('');
  const [showCustom, setShowCustom] = useState(false);
  const [configOpen, setConfigOpen] = useState(true);

  // Input params
  const [message, setMessage] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('You are a helpful assistant.');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(4096);

  // Chat state
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Refs
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Fetch available models
  const { localModels, cloudModels, isLoading: modelsLoading } = useAvailableModels({
    includeLocal: true,
    onlyValidated: true,
  });

  // Derive cloud provider list from API data (dynamic - not hardcoded)
  const cloudProviders = [...new Set(cloudModels.map(m => m.provider))].sort();

  // Build display labels from API data
  const getProviderLabel = (p: string): string => {
    const labels: Record<string, string> = {};
    for (const m of cloudModels) {
      if (!labels[m.provider]) {
        const display = m.provider.charAt(0).toUpperCase() + m.provider.slice(1);
        labels[m.provider] = display;
      }
    }
    labels['local'] = 'Local';
    return labels[p] || p;
  };

  // Map frontend provider name to backend provider name
  const getProviderBackendName = (p: string): string => p.toLowerCase();

  const getModelsForProvider = (p: string) =>
    p === 'local' ? localModels : cloudModels.filter(m => m.provider.toLowerCase() === getProviderBackendName(p));

  const selectedModel = showCustom
    ? customModel
    : provider === 'local'
      ? selectedLocalModelId
      : getModelsForProvider(provider)?.[0]?.id || '';

  const selectedMetadata = provider === 'local'
    ? localModels.find(m => m.id === selectedLocalModelId)
    : null;

  const displayModelName = selectedMetadata?.name || selectedModel;

  // Check if cloud model has an API key configured
  const isCloudModelConfigured = (modelName: string) => {
    if (modelName.startsWith('deepseek')) return true;
    return cloudModels.some(m => modelName.startsWith(m.id.split('-')[0]));
  };

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  // Focus input after loading
  useEffect(() => {
    if (!isLoading) inputRef.current?.focus();
  }, [isLoading]);

  const handleSend = async () => {
    const msg = message.trim();
    if (!selectedModel.trim() || !msg || isLoading) return;

    // Add user message
    const userMsg: ChatMessage = { role: 'user', content: msg };
    setChatHistory(prev => [...prev, userMsg]);
    setMessage('');
    setIsLoading(true);

    try {
      const res = await apiClient.modelInvoke({
        model: selectedModel,
        message: msg,
        system_prompt: systemPrompt || undefined,
        temperature,
        max_tokens: maxTokens,
      });
      const data = res.data;
      const assistantMsg: ChatMessage = {
        role: 'assistant',
        content: data.content,
        model: data.model,
        usage: data.usage,
      };
      setChatHistory(prev => [...prev, assistantMsg]);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Unknown error';
      const errorMsg: ChatMessage = { role: 'assistant', content: '', error: detail };
      setChatHistory(prev => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleProviderClick = (p: ModelProvider) => {
    setProvider(p);
    setShowCustom(false);
  };

  const clearChat = () => {
    setChatHistory([]);
  };

  return (
    <div className="flex h-full" style={{ backgroundColor: 'var(--color-background)' }}>
      {/* ═══ Left Sidebar - Model Config ═══ */}
      <div
        className={`flex flex-col transition-all duration-300 ${configOpen ? 'w-72' : 'w-12'}`}
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          borderRight: '1px solid var(--color-border)',
        }}
      >
        {/* Sidebar toggle */}
        <button
          onClick={() => setConfigOpen(!configOpen)}
          className="flex items-center justify-center h-10 transition-colors"
          style={{
            color: 'var(--color-text-muted)',
            borderBottom: '1px solid var(--color-border)',
          }}
        >
          <span className="material-symbols-outlined text-lg hover:opacity-80">{configOpen ? 'chevron_left' : 'chevron_right'}</span>
        </button>

        {configOpen && (
          <div className="flex-1 overflow-y-auto p-3 space-y-4 scrollbar-thin">
            {/* Provider selector */}
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-widest mb-2 block" style={{ color: 'var(--color-text-muted)' }}>Provider</label>
              <div className="space-y-1.5">
                {[...cloudProviders, 'local'].map((p) => (
                  <button
                    key={p}
                    onClick={() => handleProviderClick(p)}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all border"
                    style={{
                      backgroundColor: provider === p && !showCustom ? 'var(--color-input-background)' : 'transparent',
                      color: provider === p && !showCustom ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                      borderColor: provider === p && !showCustom ? 'var(--color-border)' : 'transparent',
                    }}
                  >
                    <span className={`w-2 h-2 rounded-full bg-gradient-to-r ${PROVIDER_COLORS[p] || DEFAULT_PROVIDER_COLOR}`} />
                    {getProviderLabel(p)}
                    {p !== 'local' && (
                      <span
                        className={`ml-auto w-1.5 h-1.5 rounded-full ${getModelsForProvider(p).length > 0 ? 'bg-emerald-500' : ''}`}
                        style={{ backgroundColor: getModelsForProvider(p).length === 0 ? 'var(--color-text-muted)' : undefined, opacity: getModelsForProvider(p).length === 0 ? 0.4 : 1 }}
                        title={getModelsForProvider(p).length > 0 ? 'Available' : 'No API key'}
                      />
                    )}
                  </button>
                ))}
                <button
                  onClick={() => { setShowCustom(true); setProvider('deepseek'); }}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all border"
                  style={{
                    backgroundColor: showCustom ? 'var(--color-input-background)' : 'transparent',
                    color: showCustom ? 'var(--color-text-primary)' : 'var(--color-text-muted)',
                    borderColor: showCustom ? 'var(--color-border)' : 'transparent',
                  }}
                >
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--color-text-muted)' }} />
                  Custom
                </button>
              </div>
            </div>

            {/* Model select */}
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-widest mb-2 block" style={{ color: 'var(--color-text-muted)' }}>Model</label>
              {showCustom ? (
                <input
                  type="text"
                  value={customModel}
                  onChange={e => setCustomModel(e.target.value)}
                  placeholder="e.g. gpt-4o"
                  className="w-full rounded-lg px-3 py-2 text-sm placeholder-zinc-400 focus:outline-none focus:ring-1"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                />
              ) : provider === 'local' ? (
                <div>
                  {modelsLoading ? (
                    <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Loading...</p>
                  ) : localModels.length === 0 ? (
                    <input
                      type="text"
                      value={selectedLocalModelId}
                      onChange={e => setSelectedLocalModelId(e.target.value)}
                      placeholder="e.g. local-ollama-llama3"
                      className="w-full rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1"
                      style={{
                        backgroundColor: 'var(--color-input-background)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-primary)',
                      }}
                    />
                  ) : (
                    <select
                      value={selectedLocalModelId}
                      onChange={e => setSelectedLocalModelId(e.target.value)}
                      className="w-full rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1"
                      style={{
                        backgroundColor: 'var(--color-input-background)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-primary)',
                      }}
                    >
                      <option value="">Select model...</option>
                      {localModels.map(m => (
                        <option key={m.id} value={m.id}>{m.name}</option>
                      ))}
                    </select>
                  )}
                </div>
              ) : (
                <select
                  value={selectedModel}
                  onChange={() => {}}
                  className="w-full rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1"
                  style={{
                    backgroundColor: 'var(--color-input-background)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-primary)',
                  }}
                >
                  {getModelsForProvider(provider).map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              )}
              {!showCustom && provider !== 'local' && !isCloudModelConfigured(selectedModel) && selectedModel && (
                <p className="text-[11px] mt-1.5 flex items-center gap-1" style={{ color: 'var(--color-warning, #f59e0b)' }}>
                  <span className="material-symbols-outlined text-xs">warning</span>
                  No API key
                </p>
              )}
            </div>

            {/* Temperature */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>Temperature</label>
                <span className="text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>{temperature.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={temperature}
                onChange={e => setTemperature(parseFloat(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow-lg"
                style={{
                  backgroundColor: 'var(--color-border)',
                  accentColor: 'var(--color-primary)',
                }}
              />
            </div>

            {/* Max Tokens */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[11px] font-semibold uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>Max Tokens</label>
                <span className="text-xs font-mono" style={{ color: 'var(--color-text-muted)' }}>{maxTokens.toLocaleString()}</span>
              </div>
              <input
                type="range"
                min="256"
                max="131072"
                step="256"
                value={maxTokens}
                onChange={e => setMaxTokens(parseInt(e.target.value))}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:shadow-lg"
                style={{
                  backgroundColor: 'var(--color-border)',
                  accentColor: 'var(--color-primary)',
                }}
              />
            </div>

            {/* System Prompt */}
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-widest mb-2 block" style={{ color: 'var(--color-text-muted)' }}>System Prompt</label>
              <textarea
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                placeholder="Optional system instructions..."
                rows={2}
                className="w-full rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1"
                style={{
                  backgroundColor: 'var(--color-input-background)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-primary)',
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* ═══ Main Chat Area ═══ */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Chat header */}
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{
            borderBottom: '1px solid var(--color-border)',
            backgroundColor: 'var(--color-panel-dark)',
          }}
        >
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full bg-gradient-to-r ${PROVIDER_COLORS[provider]}`} />
              <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>{displayModelName || 'Select a model'}</span>
            </div>
            {selectedModel && (
              <span
                className="text-[11px] px-2 py-0.5 rounded-full border"
                style={{
                  color: 'var(--color-text-muted)',
                  backgroundColor: 'var(--color-background)',
                  borderColor: 'var(--color-border)',
                }}
              >
                {provider === 'local' ? 'Local' : 'Cloud'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {chatHistory.length > 0 && (
              <button
                onClick={clearChat}
                className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg transition-colors"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <span className="material-symbols-outlined text-sm">delete</span>
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 scrollbar-thin">
          {chatHistory.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full text-center">
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
                style={{
                  backgroundColor: 'rgba(99,102,241,0.08)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <span className="material-symbols-outlined text-3xl" style={{ color: 'var(--color-primary)' }}>chat</span>
              </div>
              <h3 className="text-lg font-semibold mb-1" style={{ color: 'var(--color-text-primary)' }}>Model Playground</h3>
              <p className="text-sm max-w-md" style={{ color: 'var(--color-text-muted)' }}>
                Select a provider and model from the sidebar, then send a message to test it.
              </p>
            </div>
          )}

          {chatHistory.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className="max-w-[75%]">
                {/* Message bubble */}
                {msg.role === 'user' ? (
                  <div
                    className="rounded-2xl rounded-br-md px-4 py-2.5"
                    style={{
                      backgroundColor: 'var(--color-primary)',
                      color: '#FFFFFF',
                    }}
                  >
                    <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                  </div>
                ) : msg.error ? (
                  <div
                    className="rounded-2xl rounded-bl-md px-4 py-3"
                    style={{
                      backgroundColor: 'rgba(239,68,68,0.1)',
                      border: '1px solid rgba(239,68,68,0.2)',
                    }}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="material-symbols-outlined text-sm" style={{ color: '#ef4444' }}>error</span>
                      <span className="text-xs font-medium" style={{ color: '#ef4444' }}>Error</span>
                    </div>
                    <p className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: '#fca5a5' }}>{msg.error}</p>
                  </div>
                ) : (
                  <div>
                    <div
                      className="rounded-2xl rounded-bl-md px-4 py-2.5"
                      style={{
                        backgroundColor: 'var(--color-panel-dark)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text-primary)',
                      }}
                    >
                      <p className="text-sm whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    </div>
                    {/* Metadata */}
                    <div className="flex items-center gap-3 mt-1.5 px-1">
                      {msg.model && (
                        <span className="text-[10px] font-mono" style={{ color: 'var(--color-text-muted)' }}>{msg.model}</span>
                      )}
                      {msg.usage && (
                        <span className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                          {msg.usage.output_tokens} tokens
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* Loading indicator */}
          {isLoading && (
            <div className="flex justify-start">
              <div
                className="rounded-2xl rounded-bl-md px-4 py-3"
                style={{
                  backgroundColor: 'var(--color-panel-dark)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <div className="flex items-center gap-2">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ backgroundColor: 'var(--color-primary)', opacity: 0.6, animationDelay: '0ms' }} />
                    <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ backgroundColor: 'var(--color-primary)', opacity: 0.6, animationDelay: '150ms' }} />
                    <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ backgroundColor: 'var(--color-primary)', opacity: 0.6, animationDelay: '300ms' }} />
                  </div>
                  <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Thinking...</span>
                </div>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Input bar */}
        <div
          className="px-4 py-3"
          style={{
            borderTop: '1px solid var(--color-border)',
            backgroundColor: 'var(--color-panel-dark)',
          }}
        >
          <div
            className="flex items-end gap-2 rounded-2xl px-4 py-2 transition-all"
            style={{
              backgroundColor: 'var(--color-input-background)',
              border: '1px solid var(--color-border)',
            }}
          >
            <textarea
              ref={inputRef}
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message... (Shift+Enter for new line)"
              rows={1}
              className="flex-1 bg-transparent border-none outline-none text-sm resize-none max-h-32 py-1 leading-relaxed"
              style={{ color: 'var(--color-text-primary)' }}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !selectedModel.trim() || !message.trim()}
              className="flex items-center justify-center w-9 h-9 rounded-xl text-white transition-all shrink-0 disabled:opacity-40 disabled:cursor-not-allowed"
              style={{
                backgroundColor: 'var(--color-primary)',
              }}
            >
              {isLoading ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white/80 rounded-full animate-spin" />
              ) : (
                <span className="material-symbols-outlined text-lg">arrow_upward</span>
              )}
            </button>
          </div>
          <p className="text-[10px] mt-1.5 px-1" style={{ color: 'var(--color-text-muted)' }}>
            Model: {displayModelName || 'Not selected'} · Temp: {temperature.toFixed(1)} · Max tokens: {maxTokens.toLocaleString()}
          </p>
        </div>
      </div>
    </div>
  );
}

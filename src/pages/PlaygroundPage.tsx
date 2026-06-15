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

  const providerBtnClass = (p: ModelProvider, isActive: boolean) => {
    const base = 'flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all border';
    if (isActive) {
      return `${base} bg-gradient-to-r ${PROVIDER_COLORS[p]} text-white border-transparent shadow-lg shadow-${p === 'deepseek' ? 'blue' : p === 'gpt' ? 'emerald' : p === 'claude' ? 'orange' : 'violet'}-500/20`;
    }
    return `${base} bg-zinc-800/50 text-zinc-400 border-zinc-700/50 hover:bg-zinc-700/50 hover:text-zinc-300 hover:border-zinc-600/50`;
  };

  return (
    <div className="flex h-full bg-[#0a0a0f]">
      {/* ═══ Left Sidebar - Model Config ═══ */}
      <div className={`flex flex-col border-r border-zinc-800/60 bg-[#0d0d14] transition-all duration-300 ${configOpen ? 'w-72' : 'w-12'}`}>
        {/* Sidebar toggle */}
        <button
          onClick={() => setConfigOpen(!configOpen)}
          className="flex items-center justify-center h-10 text-zinc-500 hover:text-zinc-300 transition-colors border-b border-zinc-800/60"
        >
          <span className="material-symbols-outlined text-lg">{configOpen ? 'chevron_left' : 'chevron_right'}</span>
        </button>

        {configOpen && (
          <div className="flex-1 overflow-y-auto p-3 space-y-4 scrollbar-thin">
            {/* Provider selector */}
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-widest text-zinc-500 mb-2 block">Provider</label>
              <div className="space-y-1.5">
                {[...cloudProviders, 'local'].map((p) => (
                  <button
                    key={p}
                    onClick={() => handleProviderClick(p)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                      provider === p && !showCustom
                        ? 'bg-zinc-700/80 text-white border border-zinc-600/60 shadow-sm'
                        : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60 border border-transparent'
                    }`}
                  >
                    <span className={`w-2 h-2 rounded-full bg-gradient-to-r ${PROVIDER_COLORS[p] || DEFAULT_PROVIDER_COLOR}`} />
                    {getProviderLabel(p)}
                    {p !== 'local' && (
                      <span className={`ml-auto w-1.5 h-1.5 rounded-full ${getModelsForProvider(p).length > 0 ? 'bg-emerald-500' : 'bg-zinc-600'}`} title={getModelsForProvider(p).length > 0 ? 'Available' : 'No API key'} />
                    )}
                  </button>
                ))}
                <button
                  onClick={() => { setShowCustom(true); setProvider('deepseek'); }}
                  className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                    showCustom
                      ? 'bg-zinc-700/80 text-white border border-zinc-600/60 shadow-sm'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/60 border border-transparent'
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-zinc-500" />
                  Custom
                </button>
              </div>
            </div>

            {/* Model select */}
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-widest text-zinc-500 mb-2 block">Model</label>
              {showCustom ? (
                <input
                  type="text"
                  value={customModel}
                  onChange={e => setCustomModel(e.target.value)}
                  placeholder="e.g. gpt-4o"
                  className="w-full bg-zinc-800/60 border border-zinc-700/60 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:border-emerald-500/50 focus:outline-none focus:ring-1 focus:ring-emerald-500/20"
                />
              ) : provider === 'local' ? (
                <div>
                  {modelsLoading ? (
                    <p className="text-xs text-zinc-500">Loading...</p>
                  ) : localModels.length === 0 ? (
                    <input
                      type="text"
                      value={selectedLocalModelId}
                      onChange={e => setSelectedLocalModelId(e.target.value)}
                      placeholder="e.g. local-ollama-llama3"
                      className="w-full bg-zinc-800/60 border border-zinc-700/60 rounded-lg px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:border-emerald-500/50 focus:outline-none focus:ring-1 focus:ring-emerald-500/20"
                    />
                  ) : (
                    <select
                      value={selectedLocalModelId}
                      onChange={e => setSelectedLocalModelId(e.target.value)}
                      className="w-full bg-zinc-800/60 border border-zinc-700/60 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:border-emerald-500/50 focus:outline-none focus:ring-1 focus:ring-emerald-500/20"
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
                  className="w-full bg-zinc-800/60 border border-zinc-700/60 rounded-lg px-3 py-2 text-sm text-zinc-200 focus:border-emerald-500/50 focus:outline-none focus:ring-1 focus:ring-emerald-500/20"
                >
                  {getModelsForProvider(provider).map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
              )}
              {!showCustom && provider !== 'local' && !isCloudModelConfigured(selectedModel) && selectedModel && (
                <p className="text-[11px] text-amber-400/80 mt-1.5 flex items-center gap-1">
                  <span className="material-symbols-outlined text-xs">warning</span>
                  No API key
                </p>
              )}
            </div>

            {/* Temperature */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Temperature</label>
                <span className="text-xs text-zinc-400 font-mono">{temperature.toFixed(1)}</span>
              </div>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={temperature}
                onChange={e => setTemperature(parseFloat(e.target.value))}
                className="w-full h-1.5 bg-zinc-700 rounded-full appearance-none cursor-pointer accent-emerald-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-500 [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-emerald-500/30"
              />
            </div>

            {/* Max Tokens */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[11px] font-semibold uppercase tracking-widest text-zinc-500">Max Tokens</label>
                <span className="text-xs text-zinc-400 font-mono">{maxTokens.toLocaleString()}</span>
              </div>
              <input
                type="range"
                min="256"
                max="131072"
                step="256"
                value={maxTokens}
                onChange={e => setMaxTokens(parseInt(e.target.value))}
                className="w-full h-1.5 bg-zinc-700 rounded-full appearance-none cursor-pointer accent-emerald-500 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5 [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-emerald-500 [&::-webkit-slider-thumb]:shadow-lg [&::-webkit-slider-thumb]:shadow-emerald-500/30"
              />
            </div>

            {/* System Prompt */}
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-widest text-zinc-500 mb-2 block">System Prompt</label>
              <textarea
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                placeholder="Optional system instructions..."
                rows={2}
                className="w-full bg-zinc-800/60 border border-zinc-700/60 rounded-lg px-3 py-2 text-sm text-zinc-300 placeholder-zinc-600 focus:border-emerald-500/50 focus:outline-none focus:ring-1 focus:ring-emerald-500/20 resize-none"
              />
            </div>
          </div>
        )}
      </div>

      {/* ═══ Main Chat Area ═══ */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Chat header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-zinc-800/60 bg-[#0d0d14]/80">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full bg-gradient-to-r ${PROVIDER_COLORS[provider]}`} />
              <span className="text-sm font-semibold text-zinc-100">{displayModelName || 'Select a model'}</span>
            </div>
            {selectedModel && (
              <span className="text-[11px] text-zinc-500 bg-zinc-800/60 px-2 py-0.5 rounded-full border border-zinc-700/50">
                {provider === 'local' ? 'Local' : 'Cloud'}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {chatHistory.length > 0 && (
              <button
                onClick={clearChat}
                className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-300 transition-colors px-2.5 py-1.5 rounded-lg hover:bg-zinc-800/60"
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
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-emerald-500/10 flex items-center justify-center mb-4">
                <span className="material-symbols-outlined text-3xl text-emerald-400/60">chat</span>
              </div>
              <h3 className="text-lg font-semibold text-zinc-300 mb-1">Model Playground</h3>
              <p className="text-sm text-zinc-500 max-w-md">
                Select a provider and model from the sidebar, then send a message to test it.
              </p>
            </div>
          )}

          {chatHistory.map((msg, idx) => (
            <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[75%] ${msg.role === 'user' ? 'order-1' : 'order-1'}`}>
                {/* Message bubble */}
                {msg.role === 'user' ? (
                  <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-2xl rounded-br-md px-4 py-2.5">
                    <p className="text-sm text-zinc-200 whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                  </div>
                ) : msg.error ? (
                  <div className="bg-red-900/20 border border-red-800/30 rounded-2xl rounded-bl-md px-4 py-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="material-symbols-outlined text-sm text-red-400">error</span>
                      <span className="text-xs font-medium text-red-400">Error</span>
                    </div>
                    <p className="text-sm text-red-300/90 whitespace-pre-wrap leading-relaxed">{msg.error}</p>
                  </div>
                ) : (
                  <div>
                    <div className="bg-zinc-800/60 border border-zinc-700/50 rounded-2xl rounded-bl-md px-4 py-2.5">
                      <p className="text-sm text-zinc-200 whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                    </div>
                    {/* Metadata */}
                    <div className="flex items-center gap-3 mt-1.5 px-1">
                      {msg.model && (
                        <span className="text-[10px] text-zinc-600 font-mono">{msg.model}</span>
                      )}
                      {msg.usage && (
                        <span className="text-[10px] text-zinc-600">
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
              <div className="bg-zinc-800/40 border border-zinc-700/40 rounded-2xl rounded-bl-md px-4 py-3">
                <div className="flex items-center gap-2">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/60 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/60 animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500/60 animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                  <span className="text-xs text-zinc-500">Thinking...</span>
                </div>
              </div>
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        {/* Input bar */}
        <div className="px-4 py-3 border-t border-zinc-800/60 bg-[#0d0d14]">
          <div className="flex items-end gap-2 bg-zinc-800/40 border border-zinc-700/50 rounded-2xl px-4 py-2 focus-within:border-emerald-500/40 focus-within:ring-1 focus-within:ring-emerald-500/10 transition-all">
            <textarea
              ref={inputRef}
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type a message... (Shift+Enter for new line)"
              rows={1}
              className="flex-1 bg-transparent border-none outline-none text-sm text-zinc-200 placeholder-zinc-600 resize-none max-h-32 py-1 leading-relaxed"
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !selectedModel.trim() || !message.trim()}
              className="flex items-center justify-center w-9 h-9 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:bg-zinc-700 disabled:text-zinc-500 text-white transition-all shrink-0 disabled:cursor-not-allowed"
            >
              {isLoading ? (
                <span className="w-4 h-4 border-2 border-white/30 border-t-white/80 rounded-full animate-spin" />
              ) : (
                <span className="material-symbols-outlined text-lg">arrow_upward</span>
              )}
            </button>
          </div>
          <p className="text-[10px] text-zinc-600 mt-1.5 px-1">
            Model: {displayModelName || 'Not selected'} · Temp: {temperature.toFixed(1)} · Max tokens: {maxTokens.toLocaleString()}
          </p>
        </div>
      </div>
    </div>
  );
}
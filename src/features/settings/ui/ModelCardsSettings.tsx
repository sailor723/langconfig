/**
 * Model Cards Settings — visual grid of available AI models.
 * Shows API key status, capabilities, and quick actions per model.
 */

import { useState, useCallback, useEffect } from 'react';
import { apiClient } from '@/lib/api-client';

interface ModelInfo {
  model_id: string;
  display_name: string;
  provider: string;
  capabilities: Record<string, any>;
  is_active: boolean;
}

interface LocalModelInfo {
  id: number;
  name: string;
  display_name: string;
  provider: string;
  is_validated: boolean;
  is_active: boolean;
  capabilities: Record<string, any>;
}

interface EmbeddingModelInfo {
  id: string;
  name: string;
  provider: string;
  type: 'cloud' | 'local';
}

interface ProviderGroup {
  provider: string;
  cloudModels: ModelInfo[];
  localModels: LocalModelInfo[];
}

// Provider display metadata
const PROVIDER_META: Record<string, { label: string; gradient: string }> = {
  openai:    { label: 'OpenAI',    gradient: 'from-emerald-500 to-teal-500'  },
  anthropic: { label: 'Anthropic', gradient: 'from-orange-500 to-amber-500' },
  deepseek:  { label: 'DeepSeek',  gradient: 'from-blue-500 to-cyan-500'    },
  google:    { label: 'Google',    gradient: 'from-violet-500 to-purple-500'},
  agnes:     { label: 'Agnes AI',  gradient: 'from-pink-500 to-rose-500'   },
  minimax:   { label: 'MiniMax',  gradient: 'from-cyan-500 to-sky-500'    },
  glm:       { label: 'GLM',      gradient: 'from-yellow-500 to-amber-500' },
  ollama:    { label: 'Ollama',    gradient: 'from-slate-500 to-gray-500'   },
};

// Inline company logos (no network dependency)
function ProviderLogo({ provider, size = 14 }: { provider: string; size?: number }) {
  const p = provider.toLowerCase();
  const s = size;
  switch (p) {
    case 'openai':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
          <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.052 6.052 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.79a4.495 4.495 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.013l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0l-5.843 3.369V7.012a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08-4.778 2.758a.795.795 0 0 0-.393.681zm1.097-2.365l2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z"/>
        </svg>
      );
    case 'anthropic':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L2 19.5h3.5L12 7l6.5 12.5H22L12 2zm0 7.5L8.5 16h7L12 9.5z"/>
        </svg>
      );
    case 'deepseek':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 2L4 7v10l8 5 8-5V7l-8-5zm0 2.2l6 3.5v8.6l-6 3.5-6-3.5V7.7l6-3.5z"/>
          <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.2"/>
          <path d="M9 12h6M12 9v6" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
        </svg>
      );
    case 'google':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24">
          <path fill="#4285F4" d="M22.5 12.27c0-.79-.07-1.54-.2-2.27H12v4.51h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.22-4.74 3.22-8.32z"/>
          <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.99.66-2.25 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
          <path fill="#FBBC05" d="M5.84 14.1A6.94 6.94 0 0 1 5.5 12c0-.73.13-1.44.34-2.1V7.06H2.18A11 11 0 0 0 1 12c0 1.77.42 3.45 1.18 4.94l3.66-2.84z"/>
          <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.46 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
        </svg>
      );
    case 'ollama':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.5"/>
          <circle cx="8.5" cy="10" r="1.3" fill="currentColor"/>
          <circle cx="15.5" cy="10" r="1.3" fill="currentColor"/>
          <path d="M8 15q4 3 8 0" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      );
    case 'minimax':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
          <path d="M3 3h4l5 9 5-9h4v18h-4V9l-5 9-5-9v12H3z"/>
        </svg>
      );
    case 'glm':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor">
          <path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z"/>
        </svg>
      );
    case 'agnes':
      return (
        <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 4l3 8h-6l3-8zM8 14h8M12 4v6"/>
          <circle cx="18" cy="6" r="0.5" fill="currentColor"/>
          <circle cx="5" cy="8" r="0.5" fill="currentColor"/>
        </svg>
      );
    default:
      return (
        <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="9"/>
          <path d="M8 12h8" strokeLinecap="round"/>
        </svg>
      );
  }
}

function CapabilityTag({ label }: { label: string }) {
  const icons: Record<string, string> = {
    'tools': '🔧', 'vision': '👁', 'streaming': '📡',
    'function_calling': '⚡', 'json_mode': '{}',
  };
  return (
    <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border"
      style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-muted)', backgroundColor: 'var(--color-input-background)' }}>
      {icons[label] || '●'} {label.replace(/_/g, ' ')}
    </span>
  );
}

function ModelCard({ model, apiKeySet, isLocal, isDefault, onTest, onSetDefault }: {
  model: ModelInfo | LocalModelInfo;
  apiKeySet: boolean;
  isLocal: boolean;
  isDefault: boolean;
  onTest: (provider: string) => void;
  onSetDefault: (modelId: string) => void;
}) {
  const provider = isLocal ? 'ollama' : (model as ModelInfo).provider.toLowerCase();
  const meta = PROVIDER_META[provider] || PROVIDER_META.ollama;
  const isValid = isLocal ? (model as LocalModelInfo).is_validated : true;
  const capKeys = Object.keys(model.capabilities || {}).slice(0, 4);
  const caps = model.capabilities || {};
  const modelIdOrName = 'name' in model ? (model as LocalModelInfo).name : (model as ModelInfo).model_id;

  // Determine modality:
  // 1) explicit capability flags
  // 2) known model-id patterns (covers minimax-M*, claude-3+, gpt-4o, gemini-*, etc.)
  const modelIdLower = modelIdOrName.toLowerCase();
  const hasExplicitVision = caps.vision === true ||
                            caps.multimodal === true ||
                            caps.input_modalities?.includes?.('image') ||
                            caps.supports_image === true;
  const hasPatternVision =
    modelIdLower.includes('vision') ||
    modelIdLower.includes('-vl') ||
    modelIdLower.includes('multimodal') ||
    modelIdLower.startsWith('gpt-4o') ||
    modelIdLower.startsWith('gpt-4-vision') ||
    modelIdLower.startsWith('gpt-4-turbo') ||
    modelIdLower.startsWith('gpt-5') ||
    modelIdLower.startsWith('gemini-') ||
    modelIdLower.startsWith('minimax-m') ||
    /^claude-(3|opus-4|sonnet-4|haiku-4)/.test(modelIdLower) ||
    modelIdLower.includes('llava') ||
    modelIdLower.includes('llama3.2-vision');
  const isMultimodal = hasExplicitVision || hasPatternVision;
  const modality = isMultimodal ? 'Multimodal' : 'Text';
  const modalityIcon = isMultimodal ? '🖼' : '📝';
  const modalityColor = isMultimodal ? '#a78bfa' : '#94a3b8';

  return (
    <div
      className="rounded-xl border p-3 flex flex-col transition-all hover:border-primary/40 w-full relative"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        borderColor: isDefault ? 'var(--color-primary)' : 'var(--color-border)',
        boxShadow: isDefault ? '0 0 0 1px var(--color-primary)' : 'none',
        aspectRatio: '1.618 / 1',
      }}
    >
      {/* Default badge (top-center) */}
      {/* Top: name + status dot (logo removed - shown in section header) */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
            {model.display_name}
          </h4>
          <p className="text-[10px] font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
            {modelIdOrName}
          </p>
        </div>
        {/* Status dot (top-right) */}
        {!isLocal ? (
          <span
            className="w-2.5 h-2.5 rounded-full shrink-0 mt-1"
            style={{ backgroundColor: apiKeySet ? '#10b981' : '#ef4444' }}
            title={apiKeySet ? 'API key set' : 'No API key'}
          />
        ) : (
          <span
            className="w-2.5 h-2.5 rounded-full shrink-0 mt-1"
            style={{ backgroundColor: isValid ? '#10b981' : '#f59e0b' }}
            title={isValid ? 'Validated' : 'Not validated'}
          />
        )}
      </div>
      {/* Properties row — streaming, tools, context */}
      {(caps.streaming || caps.tools || caps.structured_output || caps.max_context) && (
        <div className="flex flex-wrap items-center gap-1 mt-1.5">
          {caps.streaming && (
            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{ backgroundColor: 'rgba(56,189,248,0.12)', color: '#7dd3fc' }}
              title="Supports streaming">
              <span>📡</span> Stream
            </span>
          )}
          {caps.tools && (
            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{ backgroundColor: 'rgba(251,191,36,0.12)', color: '#fcd34d' }}
              title="Supports function calling">
              <span>🔧</span> Tools
            </span>
          )}
          {caps.structured_output && (
            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{ backgroundColor: 'rgba(244,114,182,0.12)', color: '#f9a8d4' }}
              title="Supports structured output (JSON mode)">
              <span>{}</span> JSON
            </span>
          )}
          {caps.max_context && (
            <span className="inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{ backgroundColor: 'rgba(148,163,184,0.15)', color: '#cbd5e1' }}
              title="Maximum context window">
              <span>📏</span> {formatContextSize(caps.max_context)}
            </span>
          )}
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Bottom row: Test (left) + Set Default + Modality (right) */}
      <div className="flex items-center justify-between mt-1 gap-1">
        {/* Test button — bottom-left */}
        {!isLocal ? (
          <button
            onClick={() => onTest(provider)}
            title="Click to test connection"
            className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium border transition-colors hover:border-primary/50"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-muted)',
              backgroundColor: 'var(--color-input-background)',
            }}
          >
            <span style={{ color: apiKeySet ? '#10b981' : '#ef4444' }}>●</span> Test
          </button>
        ) : (
          <span className="text-[10px]" style={{ color: isValid ? '#10b981' : '#f59e0b' }}>
            {isValid ? '✓ Validated' : '⚠ Unvalidated'}
          </span>
        )}

        {/* Right side: Set Default button + Modality badge */}
        <div className="flex items-center gap-1">
          {!isDefault && (
            <button
              onClick={() => onSetDefault(modelIdOrName)}
              title="Set as default model"
              className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium border transition-colors hover:border-primary/50"
              style={{
                borderColor: 'var(--color-primary)',
                color: 'var(--color-primary)',
                backgroundColor: 'transparent',
              }}
            >
              ★ Set Default
            </button>
          )}
          {isDefault && (
            <span
              className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium"
              style={{
                backgroundColor: 'var(--color-primary)',
                color: '#fff',
              }}
              title="Current default model"
            >
              ★ Default
            </span>
          )}

          {/* Modality badge */}
          <span
            className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
            style={{
              backgroundColor: isMultimodal ? 'rgba(167,139,250,0.15)' : 'rgba(148,163,184,0.12)',
              color: modalityColor,
            }}
            title={isMultimodal ? 'Accepts text and images' : 'Text only'}
          >
            {modalityIcon} {modality}
          </span>
        </div>
      </div>
    </div>
  );
}

// Format context window size: e.g. 64000 -> "64K", 200000 -> "200K", 1000000 -> "1M"
function formatContextSize(size: number): string {
  if (size >= 1_000_000) return `${(size / 1_000_000).toFixed(size % 1_000_000 === 0 ? 0 : 1)}M`;
  if (size >= 1_000) return `${Math.round(size / 1_000)}K`;
  return String(size);
}

function ProviderGroupCard({ group, apiKeyStatus, defaultModel, testResult, onTest, onSetDefault }: {
  group: ProviderGroup;
  apiKeyStatus: Record<string, boolean>;
  defaultModel: string;
  testResult?: { success: boolean; message: string };
  onTest: (provider: string) => void;
  onSetDefault: (modelId: string) => void;
}) {
  const meta = PROVIDER_META[group.provider] || PROVIDER_META.ollama;
  const apiKeySet = apiKeyStatus[group.provider] || false;
  const total = group.cloudModels.length + group.localModels.length;
  if (total === 0) return null;

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{ borderColor: 'var(--color-border)' }}
    >
      {/* Provider header */}
      <div
        className="flex items-center justify-between px-4 py-3 flex-wrap gap-2"
        style={{ backgroundColor: 'var(--color-input-background)', borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex items-center gap-2.5">
          <div className={`inline-flex items-center justify-center w-6 h-6 rounded-md bg-gradient-to-r ${meta.gradient}`} style={{ color: '#fff' }}>
            <ProviderLogo provider={group.provider} size={14} />
          </div>
          <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            {meta.label}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
            style={{
              backgroundColor: apiKeySet ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.1)',
              color: apiKeySet ? '#10b981' : '#ef4444',
            }}
          >
            {apiKeySet ? 'Key Set' : 'No Key'}
          </span>
          {/* Inline test result (replaces panel-level) */}
          {testResult && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full font-medium inline-flex items-center gap-1"
              style={{
                backgroundColor: testResult.success ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
                color: testResult.success ? '#10b981' : '#ef4444',
              }}
            >
              {testResult.success ? '✓' : '✗'} {testResult.message}
            </span>
          )}
        </div>
        <span className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          {total} model{total !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Models grid */}
      <div className="grid grid-cols-5 gap-3 p-4">
        {group.cloudModels.map(m => (
          <ModelCard
            key={m.model_id}
            model={m}
            apiKeySet={apiKeySet}
            isLocal={false}
            isDefault={m.model_id === defaultModel}
            onTest={onTest}
            onSetDefault={onSetDefault}
          />
        ))}
        {group.localModels.map(m => (
          <ModelCard
            key={m.name}
            model={m as any}
            apiKeySet={true}
            isLocal={true}
            isDefault={m.name === defaultModel || `local-${m.name}` === defaultModel}
            onTest={onTest}
            onSetDefault={onSetDefault}
          />
        ))}
      </div>
    </div>
  );
}

function EmbeddingModelCard({ model, isDefault, onTest }: {
  model: EmbeddingModelInfo;
  isDefault: boolean;
  onTest?: (provider: string) => void;
}) {
  const provider = model.provider.toLowerCase();
  const meta = PROVIDER_META[provider] || PROVIDER_META.ollama;
  const isCloud = model.type === 'cloud';

  return (
    <div
      className="rounded-xl border p-3 flex flex-col transition-all hover:border-primary/40 w-full relative"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        borderColor: isDefault ? 'var(--color-primary)' : 'var(--color-border)',
        boxShadow: isDefault ? '0 0 0 1px var(--color-primary)' : 'none',
        aspectRatio: '1.618 / 1',
      }}
    >
      {isDefault && (
        <div
          className="absolute -top-1.5 left-1/2 -translate-x-1/2 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          ★ Active
        </div>
      )}
      {/* Top: logo + name + status dot */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <div className={`shrink-0 inline-flex items-center justify-center w-5 h-5 rounded-md bg-gradient-to-r ${meta.gradient}`} style={{ color: '#fff' }}>
              <ProviderLogo provider={provider} size={12} />
            </div>
            <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
              {model.name}
            </h4>
          </div>
          <p className="text-[11px] font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
            {model.id}
          </p>
        </div>
        {/* Status dot (top-right) */}
        <span
          className="w-2.5 h-2.5 rounded-full shrink-0 mt-1"
          style={{ backgroundColor: '#10b981' }}
          title={isCloud ? 'Available' : 'Local'}
        />
      </div>
      {/* Spacer */}
      <div className="flex-1" />
      {/* Bottom row: Test (left) + Embedding type (right) */}
      <div className="flex items-center justify-between mt-1">
        {onTest && isCloud ? (
          <button
            onClick={() => onTest(provider)}
            className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded font-medium border transition-colors hover:border-primary/50"
            style={{
              borderColor: 'var(--color-border)',
              color: 'var(--color-text-muted)',
              backgroundColor: 'var(--color-input-background)',
            }}
          >
            <span style={{ color: '#10b981' }}>●</span> Test
          </button>
        ) : (
          <span className="text-[10px]" style={{ color: '#10b981' }}>✓ Ready</span>
        )}
        <span
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
          style={{
            backgroundColor: isCloud ? 'rgba(99,102,241,0.15)' : 'rgba(148,163,184,0.12)',
            color: isCloud ? '#a5b4fc' : '#94a3b8',
          }}
        >
          {isCloud ? '☁ Cloud' : '💻 Local'}
        </span>
      </div>
    </div>
  );
}

export default function ModelCardsSettings() {
  const [cloudModels, setCloudModels] = useState<ModelInfo[]>([]);
  const [localModels, setLocalModels] = useState<LocalModelInfo[]>([]);
  const [embeddingModels, setEmbeddingModels] = useState<EmbeddingModelInfo[]>([]);
  const [defaultEmbedding, setDefaultEmbedding] = useState<string>('');
  const [defaultModel, setDefaultModel] = useState<string>('');
  const [apiKeyStatus, setApiKeyStatus] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [modelsRes, keysRes, embRes, defaultsRes] = await Promise.all([
        apiClient.listAvailableModels(),
        apiClient.getApiKeys(),
        apiClient.getAvailableEmbeddingModels().catch(() => ({ data: { models: [] } })),
        apiClient.getModelDefaults().catch(() => ({ data: { primary_model: '', embedding_model: '' } })),
      ]);

      const cloud = modelsRes.data?.cloud_models || [];
      const local = modelsRes.data?.local_models || [];
      setCloudModels(cloud);
      setLocalModels(local);
      setEmbeddingModels(embRes.data?.models || []);
      setDefaultEmbedding(defaultsRes.data?.embedding_model || '');
      setDefaultModel(defaultsRes.data?.primary_model || '');

      const keys = keysRes.data || [];
      const status: Record<string, boolean> = {};
      for (const k of keys) {
        status[k.provider] = k.is_set || false;
      }
      setApiKeyStatus(status);
    } catch (err) {
      console.error('Failed to load models:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleTest = async (provider: string) => {
    setTesting(provider);
    setTestResult(prev => ({ ...prev, [provider]: { success: false, message: 'Testing...' } }));
    try {
      const res = await apiClient.testApiKey(provider);
      const data = res.data;
      setTestResult(prev => ({ ...prev, [provider]: { success: data.success, message: data.message } }));
      setTimeout(() => {
        setTestResult(prev => {
          const next = { ...prev };
          delete next[provider];
          return next;
        });
      }, 5000);
    } catch (err: any) {
      setTestResult(prev => ({ ...prev, [provider]: {
        success: false,
        message: err?.response?.data?.detail || err?.message || 'Failed'
      } }));
    } finally {
      setTesting(null);
    }
  };

  const handleSetDefault = async (modelId: string) => {
    try {
      await apiClient.updateModelDefaultsSettings({ primary_model: modelId });
      setDefaultModel(modelId);
      setTestResult(prev => ({ ...prev, [modelId]: { success: true, message: 'Set as default ✓' } }));
      setTimeout(() => {
        setTestResult(prev => {
          const next = { ...prev };
          delete next[modelId];
          return next;
        });
      }, 3000);
    } catch (err: any) {
      setTestResult(prev => ({ ...prev, [modelId]: {
        success: false,
        message: err?.response?.data?.detail || err?.message || 'Failed to set default'
      } }));
    }
  };

  // Group by provider
  const allProviders = new Set<string>();
  cloudModels.forEach(m => allProviders.add(m.provider.toLowerCase()));
  localModels.forEach(m => allProviders.add(m.provider.toLowerCase()));

  const groups: ProviderGroup[] = Array.from(allProviders).sort().map(p => ({
    provider: p,
    cloudModels: cloudModels.filter(m => m.provider.toLowerCase() === p),
    localModels: localModels.filter(m => m.provider.toLowerCase() === p),
  })).filter(g => g.cloudModels.length + g.localModels.length > 0);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading models...</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Panel header with default model badge */}
      <div className="flex items-center justify-between flex-wrap gap-3 pb-3 border-b"
        style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-2xl" style={{ color: 'var(--color-text-primary)' }}>hub</span>
          <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            AI Models
          </h2>
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Overview of all configured AI models and their status
          </span>
        </div>
        {defaultModel && (
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{ backgroundColor: 'var(--color-input-background)', border: '1px solid var(--color-primary)' }}>
            <span className="text-[10px] uppercase font-bold tracking-wider" style={{ color: 'var(--color-primary)' }}>
              ★ Default Model
            </span>
            <span className="text-sm font-medium font-mono" style={{ color: 'var(--color-text-primary)' }}>
              {defaultModel}
            </span>
          </div>
        )}
      </div>

      {/* Provider cards (test results shown inline next to section logo) */}
      {groups.length === 0 && (
        <div className="text-center py-8" style={{ color: 'var(--color-text-muted)' }}>
          <span className="material-symbols-outlined text-3xl mb-2">smart_toy</span>
          <p className="text-sm">No models configured yet.</p>
        </div>
      )}

      <div className="space-y-4">
        {groups.map(g => (
          <ProviderGroupCard
            key={g.provider}
            group={g}
            apiKeyStatus={apiKeyStatus}
            defaultModel={defaultModel}
            testResult={testResult[g.provider]}
            onTest={handleTest}
            onSetDefault={handleSetDefault}
          />
        ))}
      </div>

      {/* Embedding Models Section */}
      {embeddingModels.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-primary)' }}>
            <span className="material-symbols-outlined text-base">database</span>
            Embedding Models
            <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium" style={{ backgroundColor: 'rgba(167,139,250,0.15)', color: '#a78bfa' }}>
              {embeddingModels.length}
            </span>
          </h3>
          <div className="grid grid-cols-5 gap-3">
            {embeddingModels.map(m => (
              <EmbeddingModelCard
                key={m.id}
                model={m}
                isDefault={m.id === defaultEmbedding || m.name === defaultEmbedding}
                onTest={handleTest}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

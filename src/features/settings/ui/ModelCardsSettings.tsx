/**
 * Model Cards Settings — visual grid of available AI models.
 * Shows API key status, capabilities, and quick actions per model.
 */

import { useState, useCallback, useEffect } from 'react';
import { apiClient } from '@/lib/api-client';
import SettingsSection from './SettingsSection';

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

// Provider logos — simple SVG marks, white-on-gradient
function ProviderLogo({ provider, size = 14 }: { provider: string; size?: number }) {
  const p = provider.toLowerCase();
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'currentColor' };
  switch (p) {
    case 'openai':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.052 6.052 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.056 6.056 0 0 0-.747-7.073zM13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.141-.081 4.779-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.142.085 4.783 2.759a.771.771 0 0 0 .78 0l5.843-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.79a4.495 4.495 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.667zm2.01-3.013l-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0l-5.843 3.369V7.012a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08-4.778 2.758a.795.795 0 0 0-.393.681zm1.097-2.365l2.602-1.5 2.607 1.5v2.999l-2.597 1.5-2.607-1.5z"/>
        </svg>
      );
    case 'anthropic':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M12 2L2 19.5h3.5L12 7l6.5 12.5H22L12 2zm0 7.5L8.5 16h7L12 9.5z"/>
        </svg>
      );
    case 'deepseek':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2"/>
          <circle cx="12" cy="12" r="4"/>
        </svg>
      );
    case 'google':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M12 11v3.2h7.6c-.3 1.7-2 5-7.6 5-4.6 0-8.3-3.8-8.3-8.4S7.4 2.4 12 2.4c2.6 0 4.4 1.1 5.4 2l3.7-3.6C18.7-1.4 15.6-1 12-1 4.8-1-1 4.8-1 12s5.8 13 13 13c7.5 0 12.5-5.3 12.5-12.7 0-.9-.1-1.5-.2-2.3H12z"/>
        </svg>
      );
    case 'agnes':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M12 2L4 7v10l8 5 8-5V7l-8-5zm0 2.5l6 3.7v7.6l-6 3.7-6-3.7V8.2l6-3.7z"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
      );
    case 'minimax':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M3 3h6v6H3V3zm6 6h6V3H9v6zm6-6h6v6h-6V3zM3 15h6v6H3v-6zm6 0h6v6H9v-6zm6 0h6v6h-6v-6z"/>
        </svg>
      );
    case 'glm':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 3l4 4-4 4-4-4 4-4zm0 10l4 4-4 4-4-4 4-4z"/>
        </svg>
      );
    case 'ollama':
      return (
        <svg {...common} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2"/>
          <circle cx="8" cy="10" r="1.5"/>
          <circle cx="16" cy="10" r="1.5"/>
          <path d="M8 16q4 3 8 0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
        </svg>
      );
    default:
      return (
        <svg {...common} viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2"/>
          <path d="M8 12h8" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
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

function ModelCard({ model, apiKeySet, isLocal, isDefault, onTest }: {
  model: ModelInfo | LocalModelInfo;
  apiKeySet: boolean;
  isLocal: boolean;
  isDefault: boolean;
  onTest: (provider: string) => void;
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
      className="rounded-xl border p-3 flex flex-col gap-2 transition-all hover:border-primary/40 w-full relative"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        borderColor: isDefault ? 'var(--color-primary)' : 'var(--color-border)',
        boxShadow: isDefault ? '0 0 0 1px var(--color-primary)' : 'none',
        aspectRatio: '1.618 / 1',
      }}
    >
      {/* Default badge (top-left corner) */}
      {isDefault && (
        <div
          className="absolute top-0 left-2 -translate-y-1/2 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: 'var(--color-primary)',
            color: '#fff',
          }}
        >
          ★ Default
        </div>
      )}

      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <div className={`shrink-0 inline-flex items-center justify-center w-5 h-5 rounded-md bg-gradient-to-r ${meta.gradient}`} style={{ color: '#fff' }}>
              <ProviderLogo provider={provider} size={12} />
            </div>
            <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
              {model.display_name}
            </h4>
          </div>
          <p className="text-[11px] font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
            {modelIdOrName}
          </p>
        </div>
        {/* Clickable status dot — triggers test for cloud models, validate for local */}
        {!isLocal ? (
          <button
            onClick={() => onTest(provider)}
            title={apiKeySet ? 'Click to test connection' : 'No API key — click to test'}
            className="w-3.5 h-3.5 rounded-full shrink-0 ring-2 ring-transparent hover:ring-primary/40 transition-all cursor-pointer"
            style={{
              backgroundColor: apiKeySet ? '#10b981' : '#ef4444',
              boxShadow: '0 0 6px rgba(0,0,0,0.3)',
            }}
          />
        ) : (
          <span
            className="w-3.5 h-3.5 rounded-full shrink-0"
            style={{
              backgroundColor: isValid ? '#10b981' : '#f59e0b',
              boxShadow: '0 0 6px rgba(0,0,0,0.3)',
            }}
            title={isValid ? 'Validated' : 'Not validated'}
          />
        )}
      </div>

      {/* Modality + capabilities */}
      <div className="flex flex-wrap gap-1">
        {/* Modality badge (always shown) */}
        <span
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
          style={{
            backgroundColor: isMultimodal ? 'rgba(167,139,250,0.12)' : 'rgba(148,163,184,0.12)',
            color: modalityColor,
          }}
          title={isMultimodal ? 'Accepts text and images' : 'Text only'}
        >
          {modalityIcon} {modality}
        </span>
        {capKeys.slice(0, 3).map(k => <CapabilityTag key={k} label={k} />)}
      </div>
    </div>
  );
}

function ProviderGroupCard({ group, apiKeyStatus, defaultModel, onTest }: {
  group: ProviderGroup;
  apiKeyStatus: Record<string, boolean>;
  defaultModel: string;
  onTest: (provider: string) => void;
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
        className="flex items-center justify-between px-4 py-3"
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
      className="rounded-xl border p-3 flex flex-col gap-2 transition-all hover:border-primary/40 w-full relative"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        borderColor: isDefault ? 'var(--color-primary)' : 'var(--color-border)',
        boxShadow: isDefault ? '0 0 0 1px var(--color-primary)' : 'none',
        aspectRatio: '1.618 / 1',
      }}
    >
      {isDefault && (
        <div
          className="absolute top-0 left-2 -translate-y-1/2 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
          style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          ★ Active
        </div>
      )}
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
        {onTest && isCloud && (
          <button
            onClick={() => onTest(provider)}
            title="Click to test"
            className="w-3.5 h-3.5 rounded-full shrink-0 ring-2 ring-transparent hover:ring-primary/40 transition-all cursor-pointer"
            style={{ backgroundColor: '#10b981', boxShadow: '0 0 6px rgba(0,0,0,0.3)' }}
          />
        )}
        {!isCloud && (
          <span
            className="w-3.5 h-3.5 rounded-full shrink-0"
            style={{ backgroundColor: '#10b981', boxShadow: '0 0 6px rgba(0,0,0,0.3)' }}
            title="Local"
          />
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        <span
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
          style={{
            backgroundColor: isCloud ? 'rgba(99,102,241,0.12)' : 'rgba(148,163,184,0.12)',
            color: isCloud ? '#a5b4fc' : '#94a3b8',
          }}
        >
          {isCloud ? '☁ Cloud' : '💻 Local'}
        </span>
        <span
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full font-medium"
          style={{ backgroundColor: 'rgba(167,139,250,0.12)', color: '#a78bfa' }}
        >
          🧬 Embedding
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
    <SettingsSection
      title="AI Models"
      description="Overview of all configured AI models and their status."
      icon="hub"
    >
      {/* Test results */}
      {Object.entries(testResult).map(([provider, result]) => (
        <div
          key={provider}
          className={`mb-4 px-4 py-3 rounded-lg text-sm flex items-center gap-2 ${
            result.success ? 'border-emerald-500/30' : 'border-red-500/30'
          }`}
          style={{
            backgroundColor: result.success ? 'rgba(16,185,129,0.08)' : 'rgba(239,68,68,0.08)',
            border: `1px solid ${result.success ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
            color: result.success ? '#10b981' : '#ef4444',
          }}
        >
          <span>{result.success ? '✓' : '✗'}</span>
          <span className="capitalize font-medium">{provider}:</span>
          <span>{result.message}</span>
        </div>
      ))}

      {/* Provider cards */}
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
            onTest={handleTest}
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
    </SettingsSection>
  );
}

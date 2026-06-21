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

interface ProviderGroup {
  provider: string;
  cloudModels: ModelInfo[];
  localModels: LocalModelInfo[];
}

// Provider display metadata
const PROVIDER_META: Record<string, { label: string; gradient: string; icon: string }> = {
  openai:    { label: 'OpenAI',    gradient: 'from-emerald-500 to-teal-500',  icon: '◉' },
  anthropic: { label: 'Anthropic', gradient: 'from-orange-500 to-amber-500', icon: '◈' },
  deepseek:  { label: 'DeepSeek',  gradient: 'from-blue-500 to-cyan-500',    icon: '◆' },
  google:    { label: 'Google',    gradient: 'from-violet-500 to-purple-500',icon: '◇' },
  agnes:     { label: 'Agnes AI',  gradient: 'from-pink-500 to-rose-500',   icon: '❖' },
  minimax:   { label: 'MiniMax',  gradient: 'from-cyan-500 to-sky-500',    icon: '◐' },
  glm:       { label: 'GLM',      gradient: 'from-yellow-500 to-amber-500', icon: '◑' },
  ollama:    { label: 'Ollama',    gradient: 'from-slate-500 to-gray-500',   icon: '◇' },
};

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

function ModelCard({ model, apiKeySet, isLocal, onTest }: {
  model: ModelInfo | LocalModelInfo;
  apiKeySet: boolean;
  isLocal: boolean;
  onTest: (provider: string) => void;
}) {
  const provider = isLocal ? 'ollama' : (model as ModelInfo).provider.toLowerCase();
  const meta = PROVIDER_META[provider] || PROVIDER_META.ollama;
  const isValid = isLocal ? (model as LocalModelInfo).is_validated : true;
  const capKeys = Object.keys(model.capabilities || {}).slice(0, 4);

  return (
    <div
      className="rounded-xl border p-3 flex flex-col gap-2 transition-all hover:border-primary/40 w-full"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        borderColor: 'var(--color-border)',
        aspectRatio: '1.618 / 1',
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-0.5">
            <div className={`w-2 h-2 rounded-full bg-gradient-to-r ${meta.gradient} shrink-0`} />
            <h4 className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
              {model.display_name}
            </h4>
          </div>
          <p className="text-[11px] font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
            {'name' in model ? (model as LocalModelInfo).name : (model as ModelInfo).model_id}
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

      {/* Capabilities */}
      {capKeys.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {capKeys.map(k => <CapabilityTag key={k} label={k} />)}
        </div>
      )}
    </div>
  );
}

function ProviderGroupCard({ group, apiKeyStatus, onTest }: {
  group: ProviderGroup;
  apiKeyStatus: Record<string, boolean>;
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
          <div className={`w-2.5 h-2.5 rounded-full bg-gradient-to-r ${meta.gradient}`} />
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
      <div className="grid grid-cols-4 gap-3 p-4">
        {group.cloudModels.map(m => (
          <ModelCard
            key={m.model_id}
            model={m}
            apiKeySet={apiKeySet}
            isLocal={false}
            onTest={onTest}
          />
        ))}
        {group.localModels.map(m => (
          <ModelCard
            key={m.name}
            model={m as any}
            apiKeySet={true}
            isLocal={true}
            onTest={onTest}
          />
        ))}
      </div>
    </div>
  );
}

export default function ModelCardsSettings() {
  const [cloudModels, setCloudModels] = useState<ModelInfo[]>([]);
  const [localModels, setLocalModels] = useState<LocalModelInfo[]>([]);
  const [apiKeyStatus, setApiKeyStatus] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [modelsRes, keysRes] = await Promise.all([
        apiClient.listAvailableModels(),
        apiClient.getApiKeys(),
      ]);

      const cloud = modelsRes.data?.cloud_models || [];
      const local = modelsRes.data?.local_models || [];
      setCloudModels(cloud);
      setLocalModels(local);

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
            onTest={handleTest}
          />
        ))}
      </div>
    </SettingsSection>
  );
}

/**
 * ModelCardsGridTab — workspace tab showing ONE provider's model cards.
 *
 * Opens when the user clicks a provider in ModelCardsSidebar. Mirrors the
 * ModelCardsSettings UI: grid of cards with capability badges, Test, Play,
 * Set Default buttons. Reuses all existing backend endpoints.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';
import type { Tab } from './useLayout';

interface CloudModel {
  model_id: string;
  display_name: string;
  provider: string;
  capabilities: Record<string, any>;
  is_active: boolean;
}
interface LocalModel {
  id: number;
  name: string;
  display_name: string;
  provider: string;
  is_validated: boolean;
  is_active: boolean;
  capabilities: Record<string, any>;
}

interface Props { tab: Tab }

const LS_KEY_DEFAULT = 'langconfig.defaultModel';

const PROVIDER_META: Record<string, { label: string; color: string }> = {
  openai:    { label: 'OpenAI',    color: '#10b981' },
  anthropic: { label: 'Anthropic', color: '#f59e0b' },
  deepseek:  { label: 'DeepSeek',  color: '#3b82f6' },
  google:    { label: 'Google',    color: '#a855f7' },
  agnes:     { label: 'Agnes AI',  color: '#ec4899' },
  minimax:   { label: 'MiniMax',  color: '#06b6d4' },
  glm:       { label: 'GLM',      color: '#eab308' },
  qwen:      { label: 'Qwen',     color: '#6366f1' },
  kimi:      { label: 'Kimi',     color: '#71717a' },
  ollama:    { label: 'Ollama',    color: '#64748b' },
};

function formatContextSize(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M ctx`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}k ctx`;
  return `${n} ctx`;
}

/** Detect modality from capabilities + model-id patterns */
function getModality(modelId: string, caps: Record<string, any>): { modality: string; icon: string; color: string } {
  const id = modelId.toLowerCase();
  const hasExplicit =
    caps.vision === true ||
    caps.multimodal === true ||
    caps.input_modalities?.includes?.('image') ||
    caps.supports_image === true;
  const hasPattern =
    id.includes('vision') || id.includes('-vl') || id.includes('multimodal') ||
    id.startsWith('gpt-4o') || id.startsWith('gpt-4-vision') || id.startsWith('gpt-4-turbo') ||
    id.startsWith('gpt-5') || id.startsWith('gemini-') || id.startsWith('minimax-m') ||
    /^claude-(3|opus-4|sonnet-4|haiku-4)/.test(id) ||
    id.includes('llava') || id.includes('llama3.2-vision');
  const isMM = hasExplicit || hasPattern;
  return isMM
    ? { modality: 'Multimodal', icon: '🖼', color: '#a78bfa' }
    : { modality: 'Text', icon: '📝', color: '#94a3b8' };
}

export default function ModelCardsGridTab({ tab }: Props) {
  const t = useLayoutTokens();
  const { provider } = tab.data ?? {};
  const meta = PROVIDER_META[provider] ?? { label: provider, color: '#888' };

  const [cloudModels, setCloudModels] = useState<CloudModel[]>([]);
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [apiKeyStatus, setApiKeyStatus] = useState<Record<string, boolean>>({});
  const [defaultModel, setDefaultModel] = useState<string>(() => localStorage.getItem(LS_KEY_DEFAULT) || '');
  const [loading, setLoading] = useState(true);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});
  const [toast, setToast] = useState<Record<string, { kind: 'success' | 'error'; text: string }>>({});
  const { openTab } = useLayoutState();

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [modelsRes, keysRes, defaultsRes] = await Promise.all([
        apiClient.listAvailableModels(),
        apiClient.getApiKeys().catch(() => ({ data: [] as any })),
        apiClient.getModelDefaults().catch(() => ({ data: { primary_model: '' } as any })),
      ]);
      const cloud: CloudModel[] = modelsRes.data?.cloud_models || [];
      const local: LocalModel[] = modelsRes.data?.local_models || [];
      // Filter to this provider only
      setCloudModels(cloud.filter(m => m.provider.toLowerCase() === provider.toLowerCase()));
      setLocalModels(local.filter(m => m.provider.toLowerCase() === provider.toLowerCase()));
      // API key status
      const keys = keysRes.data || [];
      const status: Record<string, boolean> = {};
      if (Array.isArray(keys)) {
        for (const k of keys) status[k.provider] = k.is_set || false;
      }
      setApiKeyStatus(status);
      // Respect localStorage over server value — the backend cannot persist
      // user-set defaults (they are loaded from .env).
      setDefaultModel(localStorage.getItem(LS_KEY_DEFAULT) || defaultsRes.data?.primary_model || '');
    } catch (err: any) {
      setToast({ p: { kind: 'error', text: err?.message || 'Failed to load models' } });
    } finally {
      setLoading(false);
    }
  }, [provider]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleTest = async (prov: string) => {
    setTestingProvider(prov);
    setTestResult(prev => ({ ...prev, [prov]: { success: false, message: 'Testing...' } }));
    try {
      const res = await apiClient.testApiKey(prov);
      const data = res.data;
      setTestResult(prev => ({ ...prev, [prov]: { success: data.success, message: data.message } }));
      setTimeout(() => {
        setTestResult(prev => { const next = { ...prev }; delete next[prov]; return next; });
      }, 5000);
    } catch (err: any) {
      setTestResult(prev => ({ ...prev, [prov]: {
        success: false, message: err?.response?.data?.detail || err?.message || 'Failed'
      } }));
    } finally {
      setTestingProvider(null);
    }
  };

  const handleSetDefault = async (modelId: string) => {
    try {
      await apiClient.updateModelDefaultsSettings({ primary_model: modelId });
      setDefaultModel(modelId);
      localStorage.setItem(LS_KEY_DEFAULT, modelId);
      setToast(prev => ({ ...prev, [modelId]: { kind: 'success', text: 'Set as default ✓' } }));
      setTimeout(() => {
        setToast(prev => { const next = { ...prev }; delete next[modelId]; return next; });
      }, 3000);
    } catch (err: any) {
      setToast(prev => ({ ...prev, [modelId]: {
        kind: 'error',
        text: err?.response?.data?.detail || err?.message || 'Failed',
      } }));
    }
  };

  const handlePlay = (modelId: string, modelName: string, prov: string) => {
    openTab({
      id: `playground-${modelId}`,
      label: `Test: ${modelName}`,
      viewType: 'model-viewer',
      data: { modelId, modelName, provider: prov },
    });
  };

  const total = cloudModels.length + localModels.length;
  const hasKey = apiKeyStatus[provider.toLowerCase()];
  const providerTestResult = testResult[provider];

  return (
    <div style={{
      padding: 20,
      overflowY: 'auto',
      height: '100%',
      background: t.bgContent,
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        paddingBottom: 16,
        marginBottom: 16,
        borderBottom: `1px solid ${t.border}`,
      }}>
        <span style={{
          width: 36, height: 36, borderRadius: 8,
          background: meta.color,
          color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 18, textTransform: 'uppercase',
        }}>
          {meta.label[0]}
        </span>
        <div style={{ flex: 1 }}>
          <h1 style={{
            margin: 0, fontSize: 20, fontWeight: 600,
            color: t.textPrimary,
          }}>
            {meta.label} Models
          </h1>
          <p style={{
            margin: '2px 0 0 0', fontSize: 12,
            color: t.textMuted,
          }}>
            {total} model{total === 1 ? '' : 's'} configured
          </p>
        </div>
        {/* Test provider button */}
        {cloudModels.length > 0 && (
          <button
            onClick={() => handleTest(provider)}
            disabled={testingProvider === provider}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: 'transparent',
              border: `1px solid #3b82f6`,
              color: '#93c5fd',
              fontSize: 11, fontWeight: 600,
              padding: '6px 12px',
              borderRadius: 4,
              cursor: testingProvider === provider ? 'wait' : 'pointer',
              opacity: testingProvider === provider ? 0.6 : 1,
            }}
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2" strokeLinecap="round">
              <path d="M14 6l4-4 2 2-4 4-1-1-9 9-2-2 9-9z"/>
              <path d="M5 19l-2 2"/>
            </svg>
            {testingProvider === provider ? 'Testing...' : 'Test API Key'}
          </button>
        )}
        {providerTestResult && (
          <span style={{
            fontSize: 11,
            color: providerTestResult.success ? '#10b981' : '#ef5350',
            padding: '4px 10px',
            borderRadius: 4,
            background: providerTestResult.success ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
          }}>
            {providerTestResult.message}
          </span>
        )}
        {!hasKey && cloudModels.length > 0 && (
          <span style={{
            fontSize: 11, color: '#f59e0b',
            padding: '4px 10px', borderRadius: 4,
            background: 'rgba(245,158,11,0.1)',
            border: '1px solid rgba(245,158,11,0.3)',
          }}>
            ⚠ No API key set
          </span>
        )}
      </div>

      {loading ? (
        <div style={{ color: t.textMuted, fontSize: 13 }}>Loading {meta.label} models…</div>
      ) : total === 0 ? (
        <div style={{ color: t.textMuted, fontSize: 13, fontStyle: 'italic' }}>
          No models configured for {meta.label}.
        </div>
      ) : (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
          gap: 12,
        }}>
          {/* Cloud cards */}
          {cloudModels.map(m => {
            const isDefault = defaultModel === m.model_id;
            const caps = m.capabilities || {};
            const mod = getModality(m.model_id, caps);
            const cardToast = toast[m.model_id];
            return (
              <div
                key={`cloud-${m.model_id}`}
                style={{
                  background: t.bgSidebar,
                  border: `1px solid ${isDefault ? '#10b981' : t.border}`,
                  borderRadius: 8,
                  padding: 10,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                  boxShadow: isDefault ? '0 0 0 1px #10b981' : 'none',
                }}
              >
                {/* Top: name + id + status dot */}
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <h4 style={{
                      margin: 0, fontSize: 13, fontWeight: 600,
                      color: t.textPrimary,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {m.display_name}
                    </h4>
                    <p style={{
                      margin: '2px 0 0', fontSize: 10, fontFamily: 'monospace',
                      color: t.textMuted,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {m.model_id}
                    </p>
                  </div>
                  <span
                    style={{
                      width: 8, height: 8, borderRadius: '50%', flexShrink: 0, marginTop: 4,
                      background: hasKey ? '#10b981' : '#ef4444',
                    }}
                    title={hasKey ? 'API key set' : 'No API key'}
                  />
                </div>

                {/* Capability badges */}
                {(caps.thinking || caps.tools || caps.structured_output || caps.audio || caps.video || caps.open_source || caps.max_context) && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {caps.thinking && <Badge color="#a855f7" icon="🧠" text="Think" />}
                    {caps.tools && <Badge color="#fbbf24" icon="🔧" text="Tools" />}
                    {caps.structured_output && <Badge color="#f472b6" icon="{}" text="JSON" />}
                    {caps.audio && <Badge color="#22d3ee" icon="🎵" text="Audio" />}
                    {caps.video && <Badge color="#f87171" icon="🎬" text="Video" />}
                    {caps.open_source && <Badge color="#4ade80" icon="📖" text="Open" />}
                    {caps.max_context && <Badge color="#94a3b8" icon="📏" text={formatContextSize(caps.max_context)} />}
                  </div>
                )}

                {/* Stats row */}
                {(caps.input_price !== undefined || caps.speed_tps) && (
                  <div style={{
                    display: 'flex', flexWrap: 'wrap', gap: 8,
                    fontSize: 10, color: t.textMuted,
                  }}>
                    {caps.input_price !== undefined && (
                      <span title={`Input $${caps.input_price} / 1M tok${caps.output_price !== undefined ? ` · Output $${caps.output_price} / 1M tok` : ''}`}>
                        <span style={{ color: '#10b981' }}>$</span>
                        {caps.input_price === 0
                          ? 'Free'
                          : `${caps.input_price.toFixed(2)}/${caps.output_price?.toFixed(2) ?? '?'}`}
                      </span>
                    )}
                    {caps.speed_tps && (
                      <span title={`Output speed: ~${caps.speed_tps} tok/s`}>
                        <span style={{ color: '#facc15' }}>⚡</span> {caps.speed_tps} t/s
                      </span>
                    )}
                  </div>
                )}
                {caps.strength && (
                  <div style={{ fontSize: 10, color: t.textMuted, fontStyle: 'italic' }} title={caps.strength}>
                    "{caps.strength}"
                  </div>
                )}

                {/* Toast */}
                {cardToast && (
                  <div style={{
                    fontSize: 10,
                    color: cardToast.kind === 'success' ? '#10b981' : '#ef5350',
                    padding: '3px 8px',
                    borderRadius: 3,
                    background: cardToast.kind === 'success' ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                  }}>
                    {cardToast.text}
                  </div>
                )}

                {/* Bottom row: actions */}
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  marginTop: 'auto', paddingTop: 8,
                  borderTop: `1px solid ${t.border}`,
                }}>
                  <div style={{ display: 'flex', gap: 4 }}>
                    <ActionButton
                      onClick={() => handlePlay(m.model_id, m.display_name, m.provider)}
                      label="Play"
                      color="#10b981"
                      icon={<svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>}
                      title="Open Playground"
                    />
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 9, color: mod.color }} title={mod.modality}>
                      {mod.icon} {mod.modality}
                    </span>
                    {isDefault ? (
                      <span style={{
                        background: '#10b981',
                        color: '#fff',
                        fontSize: 10,
                        padding: '2px 8px',
                        borderRadius: 3,
                        fontWeight: 600,
                      }}>
                        ★ Default
                      </span>
                    ) : (
                      <ActionButton
                        onClick={() => handleSetDefault(m.model_id)}
                        label="Set Default"
                        color="#3b82f6"
                        title="Set as default model"
                      />
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          {/* Local cards */}
          {localModels.map(m => {
            const isDefault = defaultModel === m.name;
            const isValid = m.is_validated;
            const caps = m.capabilities || {};
            const cardToast = toast[m.name];
            return (
              <div
                key={`local-${m.id}`}
                style={{
                  background: t.bgSidebar,
                  border: `1px solid ${isDefault ? '#10b981' : t.border}`,
                  borderRadius: 8,
                  padding: 10,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                  boxShadow: isDefault ? '0 0 0 1px #10b981' : 'none',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <h4 style={{ margin: 0, fontSize: 13, fontWeight: 600, color: t.textPrimary }}>{m.display_name}</h4>
                    <p style={{ margin: '2px 0 0', fontSize: 10, fontFamily: 'monospace', color: t.textMuted }}>{m.name}</p>
                  </div>
                  <span
                    style={{
                      width: 8, height: 8, borderRadius: '50%', flexShrink: 0, marginTop: 4,
                      background: isValid ? '#10b981' : '#f59e0b',
                    }}
                    title={isValid ? 'Validated' : 'Not validated'}
                  />
                </div>
                {caps.max_context && (
                  <div><Badge color="#94a3b8" icon="📏" text={formatContextSize(caps.max_context)} /></div>
                )}
                <div style={{ fontSize: 10, color: isValid ? '#10b981' : '#f59e0b' }}>
                  {isValid ? '✓ Validated' : '⚠ Unvalidated'}
                </div>
                {cardToast && (
                  <div style={{
                    fontSize: 10,
                    color: cardToast.kind === 'success' ? '#10b981' : '#ef5350',
                    padding: '3px 8px',
                    borderRadius: 3,
                    background: cardToast.kind === 'success' ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                  }}>
                    {cardToast.text}
                  </div>
                )}
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  marginTop: 'auto', paddingTop: 8,
                  borderTop: `1px solid ${t.border}`,
                }}>
                  <ActionButton
                    onClick={() => handlePlay(m.name, m.display_name, m.provider)}
                    label="Play"
                    color="#10b981"
                    icon={<svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>}
                  />
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {isDefault ? (
                      <span style={{ background: '#10b981', color: '#fff', fontSize: 10, padding: '2px 8px', borderRadius: 3, fontWeight: 600 }}>★ Default</span>
                    ) : (
                      <ActionButton
                        onClick={() => handleSetDefault(m.name)}
                        label="Set Default"
                        color="#3b82f6"
                      />
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ── Sub-components ── */
function Badge({ color, icon, text }: { color: string; icon: string; text: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      fontSize: 10, padding: '2px 7px',
      borderRadius: 999,
      fontWeight: 500,
      background: `${color}20`,
      color,
    }}>
      <span>{icon}</span>{text}
    </span>
  );
}

function ActionButton({
  onClick, label, color, icon, title,
}: {
  onClick: () => void;
  label: string;
  color: string;
  icon?: React.ReactNode;
  title?: string;
}) {
  return (
    <button
      onClick={onClick}
      title={title || label}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 10,
        padding: '3px 8px',
        borderRadius: 3,
        fontWeight: 600,
        border: `1px solid ${color}`,
        color,
        background: 'transparent',
        cursor: 'pointer',
      }}
      onMouseEnter={e => { e.currentTarget.style.background = `${color}20`; }}
      onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
    >
      {icon}
      {label}
    </button>
  );
}
/**
 * ModelCardsSidebar — left-sidebar browser for available models.
 *
 * VS Code Explorer pattern: this is a LIST ONLY — no inline details, no
 * buttons, no rich rendering. Each row is just an entry that, when clicked,
 * opens the model in the editor area as a tab (ModelViewerTab).
 *
 * Detailed info (capabilities, system prompt, temperature, test runner,
 * set-default action) lives in the ModelViewerTab — not here.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';

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

/** Provider display metadata (label + dot color for grouping headers) */
const PROVIDER_META: Record<string, { label: string; dot: string }> = {
  openai:    { label: 'OpenAI',    dot: '#10b981' },
  anthropic: { label: 'Anthropic', dot: '#f59e0b' },
  deepseek:  { label: 'DeepSeek',  dot: '#3b82f6' },
  google:    { label: 'Google',    dot: '#a855f7' },
  agnes:     { label: 'Agnes AI',  dot: '#ec4899' },
  minimax:   { label: 'MiniMax',  dot: '#06b6d4' },
  glm:       { label: 'GLM',      dot: '#eab308' },
  qwen:      { label: 'Qwen',     dot: '#6366f1' },
  kimi:      { label: 'Kimi',     dot: '#71717a' },
  ollama:    { label: 'Ollama',    dot: '#64748b' },
};

const LS_KEY_DEFAULT = 'langconfig.defaultModel';

export default function ModelCardsSidebar() {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();
  const [cloudModels, setCloudModels] = useState<CloudModel[]>([]);
  const [localModels, setLocalModels] = useState<LocalModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [defaultModel, setDefaultModel] = useState<string>(() =>
    localStorage.getItem(LS_KEY_DEFAULT) || '',
  );
  const [filter, setFilter] = useState('');

  /** Open a model in the editor area (viewer + test runner) */
  const handleOpen = useCallback((modelId: string, modelName: string, provider: string) => {
    openTab({
      id: `model-${modelId}`,
      label: modelName,
      viewType: 'model-viewer',
      data: { modelId, modelName, provider },
    });
  }, [openTab]);

  const loadModels = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [modelsRes, defaultsRes] = await Promise.all([
        apiClient.listAvailableModels(),
        apiClient.getModelDefaults().catch(() => ({ data: { primary_model: '' } as any })),
      ]);

      const payload: any = modelsRes?.data ?? {};
      setCloudModels(Array.isArray(payload.cloud_models) ? payload.cloud_models : []);
      setLocalModels(Array.isArray(payload.local_models) ? payload.local_models : []);

      const serverDefault: string = defaultsRes?.data?.primary_model || '';
      if (serverDefault) {
        localStorage.setItem(LS_KEY_DEFAULT, serverDefault);
        setDefaultModel(serverDefault);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load models');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadModels(); }, [loadModels]);

  // Group by provider for the header sections
  const cloudByProv: Record<string, CloudModel[]> = {};
  for (const m of cloudModels) {
    if (!cloudByProv[m.provider]) cloudByProv[m.provider] = [];
    cloudByProv[m.provider].push(m);
  }
  const localByProv: Record<string, LocalModel[]> = {};
  for (const m of localModels) {
    if (!localByProv[m.provider]) localByProv[m.provider] = [];
    localByProv[m.provider].push(m);
  }
  const provOrder = Array.from(new Set([
    ...Object.keys(cloudByProv),
    ...Object.keys(localByProv),
  ])).sort();

  // Apply text filter
  const f = filter.trim().toLowerCase();
  const matches = (text: string) => !f || text.toLowerCase().includes(f);

  if (loading) {
    return <div style={{ padding: 16, color: t.textMuted, fontSize: 12 }}>Loading models…</div>;
  }
  if (error) {
    return (
      <div style={{ padding: 16, color: '#ef5350', fontSize: 12 }}>
        {error}
        <button
          onClick={loadModels}
          style={{
            marginLeft: 8, background: 'transparent', border: `1px solid ${t.border}`,
            color: t.textPrimary, padding: '2px 8px', borderRadius: 3, cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div style={{ overflowY: 'auto', height: '100%' }}>
      {/* Filter input */}
      <div style={{ padding: '6px 8px', borderBottom: `1px solid ${t.border}` }}>
        <input
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter models…"
          style={{
            width: '100%',
            padding: '3px 8px',
            background: t.bgContent,
            border: `1px solid ${t.border}`,
            borderRadius: 3,
            color: t.textPrimary,
            fontSize: 12,
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* Provider sections — minimal list, just labels + entries */}
      {provOrder.map(prov => {
        const meta = PROVIDER_META[prov] ?? { label: prov, dot: '#888' };
        const cloud = (cloudByProv[prov] || []).filter(m => matches(m.display_name) || matches(m.model_id));
        const local = (localByProv[prov] || []).filter(m => matches(m.display_name) || matches(m.name));
        if (cloud.length + local.length === 0) return null;
        return (
          <div key={prov} style={{ paddingBottom: 6 }}>
            {/* Provider header */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px 3px',
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: 0.5,
              textTransform: 'uppercase',
              color: t.textMuted,
            }}>
              <span style={{
                width: 5, height: 5, borderRadius: '50%', background: meta.dot, flexShrink: 0,
              }} />
              {meta.label}
              <span style={{ marginLeft: 'auto', opacity: 0.6 }}>{cloud.length + local.length}</span>
            </div>
            {/* Cloud entries */}
            {cloud.map(m => {
              const isDefault = defaultModel === m.model_id;
              return (
                <div
                  key={`cloud-${m.model_id}`}
                  onClick={() => handleOpen(m.model_id, m.display_name, m.provider)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '3px 12px 3px 22px',
                    fontSize: 12,
                    color: t.textPrimary,
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  title={`${m.display_name} (${m.model_id})`}
                >
                  <span style={{
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    fontWeight: isDefault ? 600 : 400,
                  }}>
                    {m.display_name}
                  </span>
                  {isDefault && (
                    <span style={{ fontSize: 9, color: '#10b981', flexShrink: 0 }}>★</span>
                  )}
                </div>
              );
            })}
            {/* Local entries */}
            {local.map(m => {
              const isDefault = defaultModel === m.name;
              return (
                <div
                  key={`local-${m.id}`}
                  onClick={() => handleOpen(m.name, m.display_name, m.provider)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 4,
                    padding: '3px 12px 3px 22px',
                    fontSize: 12,
                    color: t.textPrimary,
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
                  title={`${m.display_name} (${m.name})`}
                >
                  <span style={{
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    fontWeight: isDefault ? 600 : 400,
                  }}>
                    {m.display_name}
                  </span>
                  {!m.is_validated && (
                    <span style={{ fontSize: 9, color: '#f59e0b', flexShrink: 0 }}>⚠</span>
                  )}
                  {isDefault && (
                    <span style={{ fontSize: 9, color: '#10b981', flexShrink: 0 }}>★</span>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}

      {provOrder.length === 0 && (
        <div style={{ padding: 16, color: t.textMuted, fontSize: 12, fontStyle: 'italic' }}>
          {filter ? `No models match "${filter}"` : 'No models configured'}
        </div>
      )}
    </div>
  );
}
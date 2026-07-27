/**
 * ModelCardsSidebar — left-sidebar browser for model providers.
 *
 * VS Code Explorer pattern: shows ONLY provider names as a tree. No
 * model entries inline. Clicking a provider opens its model-cards grid
 * in the editor area as a tab (ModelCardsGridTab).
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

/** Provider display metadata (label + dot color) */
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
  const [providers, setProviders] = useState<Array<{ provider: string; cloud: number; local: number }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, setDefaultModel] = useState<string>(() =>
    localStorage.getItem(LS_KEY_DEFAULT) || '',
  );

  /** Open a provider's model grid in the editor area */
  const handleOpen = useCallback((provider: string) => {
    const meta = PROVIDER_META[provider] ?? { label: provider, dot: '#888' };
    openTab({
      id: `provider-${provider}`,
      label: meta.label,
      viewType: 'model-cards',
      data: { provider },
    });
  }, [openTab]);

  const loadProviders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [modelsRes, defaultsRes] = await Promise.all([
        apiClient.listAvailableModels(),
        apiClient.getModelDefaults().catch(() => ({ data: { primary_model: '' } as any })),
      ]);
      const payload: any = modelsRes?.data ?? {};
      const cloud: CloudModel[] = Array.isArray(payload.cloud_models) ? payload.cloud_models : [];
      const local: LocalModel[] = Array.isArray(payload.local_models) ? payload.local_models : [];
      // Count per provider
      const byProv: Record<string, { cloud: number; local: number }> = {};
      for (const m of cloud) {
        if (!byProv[m.provider]) byProv[m.provider] = { cloud: 0, local: 0 };
        byProv[m.provider].cloud++;
      }
      for (const m of local) {
        if (!byProv[m.provider]) byProv[m.provider] = { cloud: 0, local: 0 };
        byProv[m.provider].local++;
      }
      setProviders(
        Object.entries(byProv)
          .map(([provider, counts]) => ({ provider, ...counts }))
          .sort((a, b) => a.provider.localeCompare(b.provider))
      );

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

  useEffect(() => { loadProviders(); }, [loadProviders]);

  if (loading) {
    return <div style={{ padding: 16, color: t.textMuted, fontSize: 12 }}>Loading providers…</div>;
  }
  if (error) {
    return (
      <div style={{ padding: 16, color: '#ef5350', fontSize: 12 }}>
        {error}
        <button
          onClick={loadProviders}
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
    <div style={{ overflowY: 'auto', height: '100%', padding: '8px 0' }}>
      {/* Header label */}
      <div style={{
        padding: '4px 12px 8px',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 0.5,
        textTransform: 'uppercase',
        color: t.textMuted,
      }}>
        Providers ({providers.length})
      </div>

      {/* Provider list — minimal, clickable rows */}
      {providers.map(({ provider, cloud, local }) => {
        const meta = PROVIDER_META[provider] ?? { label: provider, dot: '#888' };
        const total = cloud + local;
        return (
          <div
            key={provider}
            onClick={() => handleOpen(provider)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 12px',
              fontSize: 13,
              color: t.textPrimary,
              cursor: 'pointer',
              userSelect: 'none',
            }}
            onMouseEnter={e => { e.currentTarget.style.background = t.bgHover; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
            title={`View ${meta.label} models`}
          >
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: meta.dot, flexShrink: 0,
            }} />
            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {meta.label}
            </span>
            <span style={{ fontSize: 11, color: t.textDim, flexShrink: 0 }}>
              {total}
            </span>
            <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>
              ▶
            </span>
          </div>
        );
      })}

      {providers.length === 0 && (
        <div style={{ padding: 16, color: t.textMuted, fontSize: 12, fontStyle: 'italic' }}>
          No providers configured
        </div>
      )}
    </div>
  );
}

// Helper export so the grid tab can share provider metadata
export { PROVIDER_META, LS_KEY_DEFAULT };

// Re-export types so the grid tab doesn't duplicate
export type { CloudModel, LocalModel };
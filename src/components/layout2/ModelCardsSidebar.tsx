/**
 * ModelCardsSidebar — shows available cloud + local models in the left sidebar.
 *
 * Replaces the previous model-cards UI in Settings. Models are grouped by
 * provider, each card shows API key status and offers a "Play" / "Set Default"
 * action. The currently selected default model is shared via localStorage
 * and surfaced in the StatusBar.
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

interface ProviderGroup {
  provider: string;
  cloudModels: CloudModel[];
  localModels: LocalModel[];
}

/** Provider display metadata (logo + colors) */
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
  const [groups, setGroups] = useState<ProviderGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeKeys, setActiveKeys] = useState<Record<string, boolean>>({});
  const [defaultModel, setDefaultModel] = useState<string>(() =>
    localStorage.getItem(LS_KEY_DEFAULT) || '',
  );
  const [filter, setFilter] = useState('');

  // Opens a playground tab for the selected model
  const handlePlay = useCallback((modelId: string, modelName: string, provider: string) => {
    openTab({
      id: `playground-${modelId}`,
      label: `Test: ${modelName}`,
      viewType: 'model-playground',
      data: { modelId, modelName, provider },
    });
  }, [openTab]);

  const loadModels = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [modelsRes, keysRes, defaultsRes] = await Promise.all([
        apiClient.listAvailableModels(),
        apiClient.getApiKeys().catch(() => ({ data: {} as any })),
        apiClient.getModelDefaults().catch(() => ({ data: { primary_model: '' } as any })),
      ]);

      // Build a map: provider → has API key configured
      const keyMap: Record<string, boolean> = {};
      const keysData = keysRes?.data || {};
      for (const k of Object.keys(keysData)) {
        if (keysData[k]) keyMap[k] = true;
      }
      setActiveKeys(keyMap);

      // Default model — server-side, falls back to localStorage
      const serverDefault: string = defaultsRes?.data?.primary_model || '';
      if (serverDefault) {
        localStorage.setItem(LS_KEY_DEFAULT, serverDefault);
        setDefaultModel(serverDefault);
      } else if (!localStorage.getItem(LS_KEY_DEFAULT) && serverDefault) {
        setDefaultModel(serverDefault);
      }

      // Group models by provider — backend returns {cloud_models: [...], local_models: [...]}
      const payload: any = modelsRes?.data ?? {};
      const cloudList: CloudModel[] = Array.isArray(payload.cloud_models) ? payload.cloud_models : [];
      const localList: LocalModel[] = Array.isArray(payload.local_models) ? payload.local_models : [];
      const byProv: Record<string, ProviderGroup> = {};
      for (const m of cloudList) {
        if (!byProv[m.provider]) byProv[m.provider] = { provider: m.provider, cloudModels: [], localModels: [] };
        byProv[m.provider].cloudModels.push(m);
      }
      for (const m of localList) {
        if (!byProv[m.provider]) byProv[m.provider] = { provider: m.provider, cloudModels: [], localModels: [] };
        byProv[m.provider].localModels.push(m);
      }
      const sorted = Object.values(byProv).sort((a, b) => a.provider.localeCompare(b.provider));
      setGroups(sorted);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load models');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadModels(); }, [loadModels]);

  const handleSetDefault = useCallback(async (modelId: string) => {
    setDefaultModel(modelId);
    localStorage.setItem(LS_KEY_DEFAULT, modelId);
    try {
      await apiClient.updateModelDefaultsSettings({ primary_model: modelId });
    } catch (err: any) {
      // Continue optimistically — localStorage still works
      console.warn('Failed to persist default to backend:', err);
    }
  }, []);

  // ── Filter by display name or id ──
  const filteredGroups = filter.trim()
    ? groups.map(g => ({
        ...g,
        cloudModels: g.cloudModels.filter(m =>
          m.display_name.toLowerCase().includes(filter.toLowerCase()) ||
          m.model_id.toLowerCase().includes(filter.toLowerCase()),
        ),
        localModels: g.localModels.filter(m =>
          m.display_name.toLowerCase().includes(filter.toLowerCase()) ||
          m.name.toLowerCase().includes(filter.toLowerCase()),
        ),
      })).filter(g => g.cloudModels.length + g.localModels.length > 0)
    : groups;

  if (loading) {
    return (
      <div style={{ padding: 16, color: t.textMuted, fontSize: 12 }}>Loading models…</div>
    );
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
      <div style={{ padding: '8px 12px', borderBottom: `1px solid ${t.border}` }}>
        <input
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter models…"
          style={{
            width: '100%',
            padding: '4px 8px',
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

      {/* Provider groups */}
      {filteredGroups.map(group => {
        const meta = PROVIDER_META[group.provider] ?? { label: group.provider, dot: '#888' };
        const totalCount = group.cloudModels.length + group.localModels.length;
        const hasKey = activeKeys[group.provider];
        return (
          <div key={group.provider} style={{ padding: '8px 0' }}>
            {/* Provider header */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '4px 12px',
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: 0.3,
              textTransform: 'uppercase',
              color: t.textMuted,
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%', background: meta.dot, flexShrink: 0,
              }} />
              {meta.label}
              <span style={{ marginLeft: 'auto', opacity: 0.7 }}>{totalCount}</span>
              {!hasKey && group.cloudModels.length > 0 && (
                <span title="No API key configured" style={{
                  fontSize: 10, color: '#f59e0b', marginLeft: 4,
                }}>⚠</span>
              )}
            </div>

            {/* Cloud models */}
            {group.cloudModels.map(m => {
              const isDefault = defaultModel === m.model_id;
              return (
                <ModelRow
                  key={`cloud-${m.model_id}`}
                  name={m.display_name}
                  sub={m.model_id}
                  isDefault={isDefault}
                  isActive={m.is_active && !!hasKey}
                  capabilities={m.capabilities}
                  onSetDefault={() => handleSetDefault(m.model_id)}
                  onPlay={() => handlePlay(m.model_id, m.display_name, m.provider)}
                  t={t}
                />
              );
            })}
            {/* Local models */}
            {group.localModels.map(m => (
              <ModelRow
                key={`local-${m.id}`}
                name={m.display_name}
                sub={m.name}
                isDefault={defaultModel === m.name}
                isActive={m.is_active && m.is_validated}
                capabilities={m.capabilities}
                onSetDefault={() => handleSetDefault(m.name)}
                onPlay={() => handlePlay(m.name, m.display_name, m.provider)}
                t={t}
              />
            ))}
          </div>
        );
      })}

      {filteredGroups.length === 0 && (
        <div style={{ padding: 16, color: t.textMuted, fontSize: 12, fontStyle: 'italic' }}>
          {filter ? `No models match "${filter}"` : 'No models configured'}
        </div>
      )}
    </div>
  );
}

/* ── Single model row ── */
function ModelRow({
  name, sub, isDefault, isActive, capabilities, onSetDefault, onPlay, t,
}: {
  name: string;
  sub: string;
  isDefault: boolean;
  isActive: boolean;
  capabilities?: Record<string, any>;
  onSetDefault: () => void;
  onPlay: () => void;
  t: ReturnType<typeof useLayoutTokens>;
}) {
  // Compact capability badges — only show icons for true flags
  const caps = capabilities ?? {};
  const badge = (flag: boolean, glyph: string, color: string) =>
    flag ? (
      <span title={glyph} style={{
        fontSize: 10, color, marginLeft: 2, fontWeight: 700,
      }}>{glyph}</span>
    ) : null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '6px 12px 6px 24px',
        fontSize: 12,
        color: t.textPrimary,
        background: isDefault ? t.bgHover : 'transparent',
        borderTop: `1px solid ${t.border}`,
      }}
      onMouseEnter={e => { if (!isDefault) e.currentTarget.style.background = t.bgHover; }}
      onMouseLeave={e => { if (!isDefault) e.currentTarget.style.background = 'transparent'; }}
    >
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: isActive ? '#10b981' : '#6b6b6b', flexShrink: 0,
      }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontWeight: isDefault ? 600 : 400,
        }}>
          {name}
          {isDefault && (
            <span style={{ marginLeft: 6, fontSize: 10, color: '#10b981' }}>★ default</span>
          )}
          {badge(caps.thinking, '🧠', '#f59e0b')}
          {badge(caps.vision, '👁', '#3b82f6')}
          {badge(caps.tools, '🔧', '#a855f7')}
          {caps.audio && badge(true, '🎵', '#06b6d4')}
        </div>
        {sub !== name && (
          <div style={{
            fontSize: 10, color: t.textDim, overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {sub}
          </div>
        )}
      </div>
      {/* Play / Set Default actions */}
      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
        <button
          onClick={e => { e.stopPropagation(); onPlay(); }}
          title="Open Playground"
          style={{
            background: 'transparent',
            border: `1px solid #10b981`,
            color: '#10b981',
            fontSize: 10,
            padding: '2px 7px',
            borderRadius: 3,
            cursor: 'pointer',
          }}
          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(16,185,129,0.12)'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
        >
          ▶ Test
        </button>
        {!isDefault && (
          <button
            onClick={e => { e.stopPropagation(); onSetDefault(); }}
            title="Set as default"
            style={{
              background: 'transparent',
              border: `1px solid ${t.border}`,
              color: t.textMuted,
              fontSize: 10,
              padding: '2px 7px',
              borderRadius: 3,
              cursor: 'pointer',
            }}
            onMouseEnter={e => { e.currentTarget.style.color = '#f59e0b'; e.currentTarget.style.borderColor = '#f59e0b'; }}
            onMouseLeave={e => { e.currentTarget.style.color = t.textMuted; e.currentTarget.style.borderColor = t.border; }}
          >
            ★ Default
          </button>
        )}
      </div>
    </div>
  );
}
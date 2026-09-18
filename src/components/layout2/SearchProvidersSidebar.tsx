/**
 * SearchProvidersSidebar — left-sidebar browser for web search providers.
 *
 * VS Code Explorer pattern: shows ONLY provider names (like ModelCardsSidebar).
 * Clicking a provider opens its detail tab in the editor area.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import { useLayoutState } from './useLayout';
import apiClient from '../../lib/api-client';

interface SearchProviderInfo {
  id: string;
  display_name: string;
  description: string;
  category: string;
  requires_api_key: boolean;
  api_key_field: string | null;
  key_url: string | null;
  capabilities: string[];
  pricing: Record<string, any>;
  docs_url: string | null;
  icon_color: string;
  is_active: boolean;
  sort_order: number;
  has_key: boolean;
  masked_key: string | null;
}

const CATEGORY_LABEL: Record<string, string> = {
  web: 'Web Search',
  encyclopedia: 'Encyclopedia',
  semantic: 'Semantic Search',
  news: 'News',
  academic: 'Academic',
};

export default function SearchProvidersSidebar() {
  const t = useLayoutTokens();
  const { openTab } = useLayoutState();
  const [providers, setProviders] = useState<SearchProviderInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleOpen = useCallback((provider: SearchProviderInfo) => {
    openTab({
      id: `search-provider-${provider.id}`,
      label: provider.display_name,
      viewType: 'search-provider-detail',
      data: { providerId: provider.id },
    });
  }, [openTab]);

  const loadProviders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.listSearchProviders();
      const list: SearchProviderInfo[] = res.data?.providers ?? [];
      setProviders(list);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load search providers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadProviders(); }, [loadProviders]);

  if (loading) {
    return <div style={{ padding: 16, color: t.textMuted, fontSize: 12 }}>Loading search providers…</div>;
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
      {providers.map((p) => {
        const catLabel = CATEGORY_LABEL[p.category] ?? p.category;
        return (
          <div
            key={p.id}
            onClick={() => handleOpen(p)}
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
            title={`View ${p.display_name}`}
          >
            {/* Colored dot */}
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: p.icon_color, flexShrink: 0,
            }} />
            <span style={{
              flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {p.display_name}
            </span>
            {/* Key status indicator */}
            {p.requires_api_key && (
              <span style={{
                fontSize: 9, flexShrink: 0,
                color: p.has_key ? '#10b981' : '#f59e0b',
              }} title={p.has_key ? 'API key set' : 'No API key'}>
                {p.has_key ? '✓' : '⊕'}
              </span>
            )}
            <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>
              {catLabel}
            </span>
            <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>
              ▶
            </span>
          </div>
        );
      })}

      {providers.length === 0 && (
        <div style={{ padding: 16, color: t.textMuted, fontSize: 12, fontStyle: 'italic' }}>
          No search providers configured
        </div>
      )}
    </div>
  );
}

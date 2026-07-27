/**
 * SearchProviderDetailTab — workspace tab showing one search provider's details.
 *
 * Shows: description, capabilities, pricing, API key management, test button.
 * Follows the same VS Code-style pattern as ModelCardsGridTab.
 */
import { useEffect, useState, useCallback } from 'react';
import { useLayoutTokens } from './tokens';
import apiClient from '../../lib/api-client';
import type { Tab } from './useLayout';

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

interface Props { tab: Tab }

const CATEGORY_LABEL: Record<string, string> = {
  web: 'Web Search',
  encyclopedia: 'Encyclopedia',
  semantic: 'Semantic Search',
  news: 'News',
  academic: 'Academic',
};

export default function SearchProviderDetailTab({ tab }: Props) {
  const t = useLayoutTokens();
  const { providerId } = tab.data ?? {};

  const [provider, setProvider] = useState<SearchProviderInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // API key management
  const [editingKey, setEditingKey] = useState(false);
  const [keyInput, setKeyInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [toast, setToast] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);

  const loadProvider = useCallback(async () => {
    if (!providerId) return;
    setLoading(true);
    setError(null);
    try {
      const [providerRes, listRes] = await Promise.all([
        apiClient.getSearchProvider(providerId),
        apiClient.listSearchProviders().catch(() => ({ data: { providers: [] as any } })),
      ]);
      // The detail endpoint returns the provider directly; the list endpoint
      // has the full key status. Merge them to get has_key/masked_key.
      const detail = providerRes.data;
      const list: SearchProviderInfo[] = listRes.data?.providers ?? [];
      const fromList = list.find((p: SearchProviderInfo) => p.id === providerId);
      setProvider({
        ...detail,
        has_key: fromList?.has_key ?? detail.has_key ?? false,
        masked_key: fromList?.masked_key ?? detail.masked_key ?? null,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to load provider');
    } finally {
      setLoading(false);
    }
  }, [providerId]);

  useEffect(() => { loadProvider(); }, [loadProvider]);

  const showToast = (kind: 'success' | 'error', text: string) => {
    setToast({ kind, text });
    setTimeout(() => setToast(null), 4000);
  };

  const handleSaveKey = async () => {
    if (!keyInput.trim() || !provider) return;
    setSaving(true);
    try {
      await apiClient.setSearchProviderKey(provider.id, keyInput.trim());
      setEditingKey(false);
      setKeyInput('');
      showToast('success', 'API key saved ✓');
      await loadProvider();
    } catch (err: any) {
      showToast('error', err?.response?.data?.detail || 'Failed to save key');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteKey = async () => {
    if (!provider) return;
    try {
      await apiClient.deleteSearchProviderKey(provider.id);
      showToast('success', 'API key removed');
      await loadProvider();
    } catch (err: any) {
      showToast('error', err?.response?.data?.detail || 'Failed to remove key');
    }
  };

  const handleTest = async () => {
    if (!provider) return;
    setTesting(true);
    try {
      const res = await apiClient.testSearchProvider(provider.id);
      const data = res.data;
      showToast(data?.success ? 'success' : 'error', data?.message || 'Test completed');
    } catch (err: any) {
      showToast('error', err?.response?.data?.detail || 'Test failed');
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 24, color: t.textMuted, fontSize: 13 }}>
        Loading provider details…
      </div>
    );
  }
  if (error || !provider) {
    return (
      <div style={{ padding: 24, color: '#ef5350', fontSize: 13 }}>
        {error || 'Provider not found'}
        <button
          onClick={loadProvider}
          style={{
            marginLeft: 12, background: 'transparent', border: `1px solid ${t.border}`,
            color: t.textPrimary, padding: '4px 12px', borderRadius: 3, cursor: 'pointer', fontSize: 12,
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  const catLabel = CATEGORY_LABEL[provider.category] ?? provider.category;

  return (
    <div style={{
      padding: 24, overflowY: 'auto', height: '100%',
      background: t.bgContent, maxWidth: 720,
    }}>
      {/* ── Header ─────────────────────────────────────── */}
      <div style={{
        display: 'flex', alignItems: 'flex-start', gap: 14,
        paddingBottom: 20, marginBottom: 20,
        borderBottom: `1px solid ${t.border}`,
      }}>
        {/* Colored initial badge */}
        <div style={{
          width: 42, height: 42, borderRadius: 10, flexShrink: 0,
          background: provider.icon_color,
          color: '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 700, fontSize: 20, textTransform: 'uppercase',
        }}>
          {provider.display_name[0]}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: t.textPrimary }}>
            {provider.display_name}
          </h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
            <span style={{ fontSize: 11, color: t.textMuted, fontFamily: 'monospace' }}>
              {provider.id}
            </span>
            <span style={{
              fontSize: 10, padding: '2px 8px', borderRadius: 999,
              background: `${provider.icon_color}20`, color: provider.icon_color,
              fontWeight: 600,
            }}>
              {catLabel}
            </span>
          </div>
        </div>
        {/* API key status badge */}
        {provider.requires_api_key ? (
          <span style={{
            fontSize: 11, padding: '4px 10px', borderRadius: 4,
            background: provider.has_key ? 'rgba(16,185,129,0.12)' : 'rgba(245,158,11,0.12)',
            color: provider.has_key ? '#10b981' : '#f59e0b',
            fontWeight: 600, whiteSpace: 'nowrap',
          }}>
            {provider.has_key
              ? `✓ ${provider.masked_key || 'Key set'}`
              : '⊕ No API key'}
          </span>
        ) : (
          <span style={{
            fontSize: 11, padding: '4px 10px', borderRadius: 4,
            background: 'rgba(34,197,94,0.12)', color: '#22c55e',
            fontWeight: 600,
          }}>
            ✓ No key needed
          </span>
        )}
      </div>

      {/* ── Description ─────────────────────────────────── */}
      <p style={{ fontSize: 13, lineHeight: 1.6, color: t.textPrimary, margin: '0 0 20px' }}>
        {provider.description}
      </p>

      {/* ── Capabilities ─────────────────────────────────── */}
      <Section title="Capabilities" t_muted={t.textMuted}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {provider.capabilities.map((cap: string) => (
            <span key={cap} style={{
              fontSize: 11, padding: '4px 10px', borderRadius: 4,
              background: t.bgSidebar, color: t.textPrimary,
              border: `1px solid ${t.border}`,
              fontFamily: 'monospace',
            }}>
              {cap}
            </span>
          ))}
          {provider.capabilities.length === 0 && (
            <span style={{ fontSize: 12, color: t.textMuted, fontStyle: 'italic' }}>
              No capabilities listed
            </span>
          )}
        </div>
      </Section>

      {/* ── Pricing ─────────────────────────────────────── */}
      {provider.pricing && Object.keys(provider.pricing).length > 0 && (
        <Section title="Pricing" t_muted={t.textMuted}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {Object.entries(provider.pricing).map(([k, v]) => (
              <div key={k} style={{ fontSize: 12, color: t.textPrimary }}>
                <span style={{ fontWeight: 600, color: t.textMuted, textTransform: 'capitalize' }}>
                  {k.replace(/_/g, ' ')}:
                </span>{' '}
                {String(v)}
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* ── API Key Management ─────────────────────────── */}
      {provider.requires_api_key && (
        <Section title="API Key" t_muted={t.textMuted}>
          {provider.key_url && (
            <p style={{ fontSize: 11, color: t.textMuted, margin: '0 0 10px' }}>
              Get an API key at{' '}
              <a href={provider.key_url} target="_blank" rel="noopener noreferrer"
                style={{ color: '#3b82f6' }}>
                {provider.key_url}
              </a>
            </p>
          )}

          {editingKey ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="password"
                value={keyInput}
                onChange={e => setKeyInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSaveKey();
                  if (e.key === 'Escape') { setEditingKey(false); setKeyInput(''); }
                }}
                placeholder={`Enter ${(provider.api_key_field || 'API key').toUpperCase()}`}
                autoFocus
                disabled={saving}
                style={{
                  flex: 1, maxWidth: 360,
                  fontSize: 12, padding: '6px 10px', borderRadius: 4,
                  background: t.bgSidebar, color: t.textPrimary,
                  border: `1px solid ${t.accent}`,
                  outline: 'none',
                  fontFamily: 'monospace',
                }}
              />
              <button onClick={handleSaveKey} disabled={saving || !keyInput.trim()}
                style={{
                  padding: '6px 14px', fontSize: 11, fontWeight: 600,
                  background: '#10b981', color: '#fff', border: 'none',
                  borderRadius: 4, cursor: saving ? 'wait' : 'pointer',
                  opacity: saving ? 0.6 : 1,
                }}>
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => { setEditingKey(false); setKeyInput(''); }}
                style={{ fontSize: 11, color: t.textMuted, background: 'transparent', border: 'none', cursor: 'pointer' }}>
                Cancel
              </button>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => { setEditingKey(true); setKeyInput(''); }}
                style={{
                  padding: '6px 14px', fontSize: 11, fontWeight: 600,
                  background: 'transparent',
                  border: `1px solid ${provider.has_key ? '#f59e0b' : '#3b82f6'}`,
                  color: provider.has_key ? '#f59e0b' : '#93c5fd',
                  borderRadius: 4, cursor: 'pointer',
                }}>
                {provider.has_key ? 'Update Key' : 'Set Key'}
              </button>
              {provider.has_key && (
                <button onClick={handleDeleteKey}
                  style={{
                    padding: '6px 14px', fontSize: 11, fontWeight: 600,
                    background: 'transparent',
                    border: '1px solid rgba(239,68,68,0.4)',
                    color: '#ef4444', borderRadius: 4, cursor: 'pointer',
                  }}>
                  Remove Key
                </button>
              )}
            </div>
          )}
        </Section>
      )}

      {/* ── Actions ─────────────────────────────────────── */}
      <Section title="Actions" t_muted={t.textMuted}>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={handleTest} disabled={testing}
            style={{
              padding: '7px 16px', fontSize: 12, fontWeight: 600,
              background: t.bgSidebar, color: t.textPrimary,
              border: `1px solid ${t.border}`, borderRadius: 4,
              cursor: testing ? 'wait' : 'pointer',
              opacity: testing ? 0.6 : 1,
            }}>
            {testing ? 'Testing...' : 'Test Connection'}
          </button>
          {provider.docs_url && (
            <a href={provider.docs_url} target="_blank" rel="noopener noreferrer"
              style={{
                padding: '7px 16px', fontSize: 12, fontWeight: 600,
                background: 'transparent',
                border: `1px solid ${t.border}`, borderRadius: 4,
                color: t.textPrimary, textDecoration: 'none',
                display: 'inline-flex', alignItems: 'center', gap: 4,
              }}>
              Docs ↗
            </a>
          )}
        </div>
      </Section>

      {/* ── Toast ───────────────────────────────────────── */}
      {toast && (
        <div style={{
          marginTop: 16, padding: '8px 14px', borderRadius: 4, fontSize: 12,
          background: toast.kind === 'success' ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
          color: toast.kind === 'success' ? '#10b981' : '#ef4444',
          border: `1px solid ${toast.kind === 'success' ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
        }}>
          {toast.text}
        </div>
      )}
    </div>
  );
}

/* ── Section sub-component ── */
function Section({ title, children, t_muted }: { title: string; children: React.ReactNode; t_muted: string }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{
        margin: '0 0 8px', fontSize: 11, fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: 0.5,
        color: t_muted,
      }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

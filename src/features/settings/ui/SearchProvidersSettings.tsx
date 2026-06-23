/**
 * Search Providers Settings — visual grid of web/encyclopedia search backends.
 *
 * Created 2026-06-24 alongside backend/api/system/search_providers.py.
 * Each provider card shows: name, description, capabilities, pricing,
 * API key status, and inline API key editor (when applicable).
 */
import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '@/lib/api-client';

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

const CATEGORY_META: Record<string, { label: string; gradient: string; icon: string }> = {
  web:           { label: 'Web Search',         gradient: 'from-blue-500 to-cyan-500',     icon: 'travel_explore' },
  encyclopedia:  { label: 'Encyclopedia',       gradient: 'from-gray-500 to-slate-500',    icon: 'menu_book' },
  semantic:      { label: 'Semantic Search',    gradient: 'from-purple-500 to-violet-500', icon: 'psychology' },
  news:          { label: 'News',               gradient: 'from-red-500 to-rose-500',      icon: 'newspaper' },
  academic:      { label: 'Academic',           gradient: 'from-emerald-500 to-teal-500',  icon: 'school' },
};

export default function SearchProvidersSettings() {
  const [providers, setProviders] = useState<SearchProviderInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState('');
  const [savingId, setSavingId] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.listSearchProviders();
      setProviders(res.data?.providers || []);
    } catch (err) {
      console.error('Failed to load search providers:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const handleSaveKey = async (provider: SearchProviderInfo) => {
    if (!keyInput.trim()) return;
    setSavingId(provider.id);
    try {
      await apiClient.setSearchProviderKey(provider.id, keyInput.trim());
      setEditingId(null);
      setKeyInput('');
      setTestResult(prev => ({ ...prev, [provider.id]: { success: true, message: 'API key saved ✓' } }));
      await loadData();
      setTimeout(() => {
        setTestResult(prev => { const n = { ...prev }; delete n[provider.id]; return n; });
      }, 3000);
    } catch (err: any) {
      setTestResult(prev => ({ ...prev, [provider.id]: { success: false, message: err?.response?.data?.detail || 'Failed' } }));
    } finally {
      setSavingId(null);
    }
  };

  const handleDeleteKey = async (provider: SearchProviderInfo) => {
    try {
      await apiClient.deleteSearchProviderKey(provider.id);
      setTestResult(prev => ({ ...prev, [provider.id]: { success: true, message: 'API key removed' } }));
      await loadData();
      setTimeout(() => {
        setTestResult(prev => { const n = { ...prev }; delete n[provider.id]; return n; });
      }, 3000);
    } catch (err: any) {
      setTestResult(prev => ({ ...prev, [provider.id]: { success: false, message: err?.response?.data?.detail || 'Failed' } }));
    }
  };

  const handleTest = async (provider: SearchProviderInfo) => {
    setTestingId(provider.id);
    try {
      const res = await apiClient.testSearchProvider(provider.id);
      setTestResult(prev => ({ ...prev, [provider.id]: { success: res.data?.success, message: res.data?.message || '' } }));
      setTimeout(() => {
        setTestResult(prev => { const n = { ...prev }; delete n[provider.id]; return n; });
      }, 4000);
    } catch (err: any) {
      setTestResult(prev => ({ ...prev, [provider.id]: { success: false, message: 'Test failed' } }));
    } finally {
      setTestingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading search providers…</span>
      </div>
    );
  }

  // Group by category
  const grouped = new Map<string, SearchProviderInfo[]>();
  for (const p of providers) {
    if (!grouped.has(p.category)) grouped.set(p.category, []);
    grouped.get(p.category)!.push(p);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between pb-3 border-b"
        style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-2xl" style={{ color: 'var(--color-text-primary)' }}>search</span>
          <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>Search Providers</h2>
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Web / encyclopedia backends for agents with search tools
          </span>
        </div>
        <span className="text-[11px]" style={{ color: 'var(--color-text-muted)' }}>
          {providers.length} provider{providers.length !== 1 ? 's' : ''}
        </span>
      </div>

      {Array.from(grouped.entries()).map(([category, items]) => {
        const meta = CATEGORY_META[category] || CATEGORY_META.web;
        return (
          <div key={category} className="rounded-xl border overflow-hidden"
            style={{ borderColor: 'var(--color-border)' }}>
            {/* Category header */}
            <div className="flex items-center gap-2.5 px-4 py-2.5"
              style={{ backgroundColor: 'var(--color-input-background)' }}>
              <div className={`inline-flex items-center justify-center w-6 h-6 rounded-md bg-gradient-to-r ${meta.gradient}`}
                style={{ color: '#fff' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>{meta.icon}</span>
              </div>
              <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>{meta.label}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                style={{ backgroundColor: 'rgba(59,130,246,0.15)', color: '#3b82f6' }}>
                {items.length}
              </span>
            </div>

            {/* Provider cards grid */}
            <div className="grid grid-cols-4 gap-3 p-4">
              {items.map(p => {
                const isEditing = editingId === p.id;
                const isSaving = savingId === p.id;
                const isTesting = testingId === p.id;
                const result = testResult[p.id];

                return (
                  <div key={p.id}
                    className="rounded-lg border p-4 flex flex-col gap-2"
                    style={{ borderColor: 'var(--color-border)', backgroundColor: 'var(--color-bg-primary)' }}>
                    {/* Header: name + status badge */}
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: p.icon_color }} />
                          <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                            {p.display_name}
                          </span>
                        </div>
                        <span className="text-[10px] font-mono ml-4" style={{ color: 'var(--color-text-muted)' }}>
                          {p.id}
                        </span>
                      </div>
                      {/* Status badge */}
                      {p.requires_api_key ? (
                        isEditing ? null : (
                          <button
                            onClick={() => { setEditingId(p.id); setKeyInput(''); }}
                            className="text-[10px] px-1.5 py-0.5 rounded-full font-medium hover:opacity-80"
                            title={p.has_key ? 'Click to update key' : 'Click to set key'}
                            style={{
                              backgroundColor: p.has_key ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.1)',
                              color: p.has_key ? '#10b981' : '#ef4444',
                              border: 'none',
                              cursor: 'pointer',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {p.has_key ? `✓ ${p.masked_key}` : '⊕ Set Key'}
                          </button>
                        )
                      ) : (
                        <span
                          className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                          style={{ backgroundColor: 'rgba(34,197,94,0.15)', color: '#22c55e' }}
                        >
                          ✓ No key needed
                        </span>
                      )}
                    </div>

                    {/* Description */}
                    <p className="text-[11px] leading-relaxed" style={{ color: 'var(--color-text-muted)' }}>
                      {p.description}
                    </p>

                    {/* Capabilities */}
                    <div className="flex flex-wrap gap-1">
                      {p.capabilities.slice(0, 5).map(cap => (
                        <span key={cap} className="text-[9px] px-1.5 py-0.5 rounded font-mono"
                          style={{ backgroundColor: 'var(--color-input-background)', color: 'var(--color-text-muted)' }}>
                          {cap}
                        </span>
                      ))}
                      {p.capabilities.length > 5 && (
                        <span className="text-[9px] px-1.5 py-0.5"
                          style={{ color: 'var(--color-text-muted)' }}>
                          +{p.capabilities.length - 5}
                        </span>
                      )}
                    </div>

                    {/* Pricing summary */}
                    {p.pricing && Object.keys(p.pricing).length > 0 && (
                      <div className="text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                        {Object.entries(p.pricing).slice(0, 2).map(([k, v]) => (
                          <div key={k}>• <span className="font-semibold">{k}:</span> {String(v)}</div>
                        ))}
                      </div>
                    )}

                    {/* Test result toast */}
                    {result && (
                      <div className="text-[10px] px-2 py-1 rounded"
                        style={{
                          backgroundColor: result.success ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                          color: result.success ? '#10b981' : '#ef4444',
                        }}>
                        {result.message}
                      </div>
                    )}

                    {/* Inline key editor */}
                    {isEditing && (
                      <div className="flex items-center gap-1.5 pt-2 border-t" style={{ borderColor: 'var(--color-border)' }}>
                        <input
                          type="password"
                          value={keyInput}
                          onChange={(e) => setKeyInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveKey(p);
                            if (e.key === 'Escape') { setEditingId(null); setKeyInput(''); }
                          }}
                          placeholder={`${(p.api_key_field || '').toUpperCase()}`}
                          autoFocus
                          disabled={isSaving}
                          className="flex-1 text-[10px] px-2 py-1 rounded border font-mono"
                          style={{
                            backgroundColor: 'var(--color-bg-primary)',
                            borderColor: 'var(--color-primary)',
                            color: 'var(--color-text-primary)',
                          }}
                        />
                        <button
                          onClick={() => handleSaveKey(p)}
                          disabled={isSaving || !keyInput.trim()}
                          className="px-3 py-1 rounded font-semibold text-sm disabled:opacity-50"
                          style={{ backgroundColor: '#d97757', color: '#ffffff', border: 'none', minWidth: '60px' }}
                        >
                          {isSaving ? '...' : 'Save'}
                        </button>
                        <button
                          onClick={() => { setEditingId(null); setKeyInput(''); }}
                          className="text-[10px] px-2 py-1 rounded font-medium"
                          style={{ color: 'var(--color-text-muted)' }}
                        >
                          ✕
                        </button>
                      </div>
                    )}

                    {/* Action buttons row */}
                    <div className="flex items-center gap-1.5 pt-2 mt-auto">
                      <button
                        onClick={() => handleTest(p)}
                        disabled={isTesting}
                        className="flex-1 text-[11px] px-2 py-1 rounded font-medium disabled:opacity-50"
                        style={{
                          backgroundColor: 'var(--color-input-background)',
                          color: 'var(--color-text-primary)',
                          border: '1px solid var(--color-border)',
                        }}
                      >
                        {isTesting ? 'Testing…' : 'Test'}
                      </button>
                      {p.has_key && !isEditing && (
                        <button
                          onClick={() => handleDeleteKey(p)}
                          className="text-[11px] px-2 py-1 rounded font-medium"
                          style={{
                            backgroundColor: 'transparent',
                            color: '#ef4444',
                            border: '1px solid rgba(239,68,68,0.3)',
                          }}
                          title="Remove API key"
                        >
                          Remove Key
                        </button>
                      )}
                      {p.docs_url && (
                        <a
                          href={p.docs_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[11px] px-2 py-1 rounded font-medium no-underline"
                          style={{
                            backgroundColor: 'transparent',
                            color: 'var(--color-text-muted)',
                            border: '1px solid var(--color-border)',
                          }}
                        >
                          Docs ↗
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
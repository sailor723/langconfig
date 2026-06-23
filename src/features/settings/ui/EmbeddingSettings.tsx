/**
 * Embedding Settings — moved from ModelCardsSettings 2026-06-23.
 * Shows embedding model cards in the dedicated "Embedding" sidebar tab.
 *
 * Uses the same data sources as ModelCardsSettings (api-client.getAvailableEmbeddingModels)
 * but renders only the embedding model grid — chat LLMs are in Model Cards.
 */
import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/api-client';

interface EmbeddingModelInfo {
  id: string;
  name: string;
  provider: string;
  type: 'cloud' | 'local';
}

const PROVIDER_META: Record<string, { label: string; gradient: string }> = {
  openai:    { label: 'OpenAI',    gradient: 'from-emerald-500 to-teal-500'  },
  google:    { label: 'Google',    gradient: 'from-violet-500 to-purple-500'},
  ollama:    { label: 'Ollama',    gradient: 'from-slate-500 to-gray-500'   },
  cohere:    { label: 'Cohere',    gradient: 'from-pink-500 to-rose-500'   },
  huggingface: { label: 'HuggingFace', gradient: 'from-yellow-500 to-amber-500' },
};

export default function EmbeddingSettings() {
  const [models, setModels] = useState<EmbeddingModelInfo[]>([]);
  const [defaultId, setDefaultId] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      apiClient.getAvailableEmbeddingModels().catch(() => ({ data: { models: [] as EmbeddingModelInfo[] } })),
      apiClient.getModelDefaults().catch(() => ({ data: { embedding_model: '' } })),
    ]).then(([embRes, defRes]) => {
      if (!alive) return;
      setModels(embRes.data?.models || []);
      setDefaultId(defRes.data?.embedding_model || '');
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  const setAsDefault = async (id: string) => {
    setSavingId(id);
    try {
      await apiClient.updateModelDefaults({ embedding_model: id });
      setDefaultId(id);
    } finally {
      setSavingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading embedding models…</span>
      </div>
    );
  }

  // Group by provider for visual consistency with Model Cards
  const grouped = new Map<string, EmbeddingModelInfo[]>();
  for (const m of models) {
    const p = (m.provider || 'other').toLowerCase();
    if (!grouped.has(p)) grouped.set(p, []);
    grouped.get(p)!.push(m);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between pb-3 border-b"
        style={{ borderColor: 'var(--color-border)' }}>
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-2xl" style={{ color: 'var(--color-text-primary)' }}>database</span>
          <h2 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
            Embedding Models
          </h2>
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            Used for RAG / vector search
          </span>
        </div>
        {defaultId && (
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg"
            style={{ backgroundColor: 'var(--color-input-background)', border: '1px solid var(--color-primary)' }}>
            <span className="text-[10px] uppercase font-bold tracking-wider" style={{ color: 'var(--color-primary)' }}>
              ★ Default
            </span>
            <span className="text-sm font-medium font-mono" style={{ color: 'var(--color-text-primary)' }}>
              {defaultId}
            </span>
          </div>
        )}
      </div>

      {models.length === 0 ? (
        <div className="text-center text-sm py-8" style={{ color: 'var(--color-text-muted)' }}>
          No embedding models available. Configure an OpenAI / Google / Ollama key first.
        </div>
      ) : (
        Array.from(grouped.entries()).map(([provider, items]) => {
          const meta = PROVIDER_META[provider] || { label: provider, gradient: 'from-slate-500 to-gray-500' };
          return (
            <div key={provider} className="rounded-xl border overflow-hidden"
              style={{ borderColor: 'var(--color-border)' }}>
              <div className="flex items-center justify-between px-4 py-2.5"
                style={{ backgroundColor: 'var(--color-input-background)' }}>
                <div className="flex items-center gap-2.5">
                  <div className={`inline-flex items-center justify-center w-6 h-6 rounded-md bg-gradient-to-r ${meta.gradient}`}
                    style={{ color: '#fff' }}>
                    <span className="text-[10px] font-bold">{meta.label[0]}</span>
                  </div>
                  <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                    {meta.label}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
                    style={{ backgroundColor: 'rgba(167,139,250,0.15)', color: '#a78bfa' }}>
                    {items.length} model{items.length !== 1 ? 's' : ''}
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-4 gap-3 p-4">
                {items.map(m => {
                  const isDefault = m.id === defaultId || m.name === defaultId;
                  const isSaving = savingId === m.id;
                  return (
                    <div key={m.id}
                      className="rounded-lg border p-3 flex flex-col gap-2"
                      style={{
                        borderColor: isDefault ? 'var(--color-primary)' : 'var(--color-border)',
                        backgroundColor: isDefault ? 'rgba(46,92,138,0.06)' : 'var(--color-bg-primary)',
                      }}>
                      <div className="flex items-start justify-between gap-1">
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-semibold truncate" style={{ color: 'var(--color-text-primary)' }}>
                            {m.name}
                          </div>
                          <div className="text-[10px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
                            {m.id}
                          </div>
                        </div>
                        {isDefault && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                            style={{ backgroundColor: 'rgba(46,92,138,0.15)', color: '#2E5C8A' }}>
                            ★ Default
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                        <span className="px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: m.type === 'cloud' ? 'rgba(59,130,246,0.12)' : 'rgba(107,114,128,0.12)' }}>
                          {m.type}
                        </span>
                      </div>
                      <button
                        onClick={() => setAsDefault(m.id)}
                        disabled={isDefault || isSaving}
                        className="text-[11px] px-2 py-1 rounded font-medium disabled:opacity-50"
                        style={{
                          backgroundColor: isDefault ? 'transparent' : 'var(--color-primary)',
                          color: isDefault ? 'var(--color-primary)' : '#ffffff',
                          border: isDefault ? '1px solid var(--color-primary)' : 'none',
                        }}
                      >
                        {isSaving ? 'Saving…' : isDefault ? 'Current default' : 'Set as default'}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}
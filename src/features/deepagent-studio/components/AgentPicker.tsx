/**
 * AgentPicker — top dropdown to select which DeepAgent to visualize.
 */

import { useEffect, useState } from 'react';
import apiClient from '@/lib/api-client';

interface AgentItem {
  id: number;
  name: string;
  description?: string;
}

interface Props {
  selectedId: number | null;
  onSelect: (id: number) => void;
  onEdit?: (id: number) => void;
  onTest?: (id: number) => void;
}

export default function AgentPicker({ selectedId, onSelect, onEdit, onTest }: Props) {
  const [agents, setAgents] = useState<AgentItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.listDeepAgents({});
        const list = (res as any).data ?? res;
        const items: AgentItem[] = (list ?? []).map((a: any) => ({
          id: a.id,
          name: a.config?.name ?? a.name ?? `Agent ${a.id}`,
          description: a.config?.description ?? a.description ?? '',
        }));
        if (!cancelled) setAgents(items);
      } catch {
        // ignore
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="flex items-center gap-2 flex-1 min-w-0">
      <span className="text-xs uppercase tracking-widest font-semibold"
        style={{ color: 'var(--color-text-muted)' }}>
        🎨 Agent:
      </span>
      <select
        value={selectedId ?? ''}
        onChange={(e) => onSelect(Number(e.target.value))}
        disabled={loading || agents.length === 0}
        className="px-3 py-1.5 rounded-lg text-sm focus:outline-none focus:ring-1"
        style={{
          backgroundColor: 'var(--color-input-background)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text-primary)',
          minWidth: 200,
          maxWidth: 360,
        }}
      >
        <option value="" disabled>
          {loading ? 'Loading…' : agents.length === 0 ? 'No agents found' : '— Select agent —'}
        </option>
        {agents.map(a => (
          <option key={a.id} value={a.id}>{a.name}</option>
        ))}
      </select>

      {selectedId && (
        <div className="flex items-center gap-1 ml-2">
          {onTest && (
            <button
              onClick={() => onTest(selectedId)}
              className="px-3 py-1.5 rounded-lg text-xs font-medium border"
              style={{
                borderColor: '#10b981',
                color: '#86efac',
                backgroundColor: 'rgba(16,185,129,0.12)',
              }}
              title="Run agent and watch skill routing in real-time"
            >
              ▶ Test
            </button>
          )}
          {onEdit && (
            <button
              onClick={() => onEdit(selectedId)}
              className="px-3 py-1.5 rounded-lg text-xs font-medium border"
              style={{
                borderColor: 'var(--color-border)',
                color: 'var(--color-text-primary)',
                backgroundColor: 'var(--color-input-background)',
              }}
              title="Open in new builder (isolated from existing panel)"
            >
              ⚙ Edit
            </button>
          )}
        </div>
      )}
    </div>
  );
}
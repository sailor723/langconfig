/**
 * ModernAgentPicker — sleek dropdown, brand-aligned, rendered via portal.
 */

import { useEffect, useState, useRef } from 'react';
import { createPortal } from 'react-dom';
import apiClient from '@/lib/api-client';

interface Agent {
  id: number;
  name: string;
  description?: string;
  category?: string;
}

interface Props {
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export default function ModernAgentPicker({ selectedId, onSelect }: Props) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [coords, setCoords] = useState<{ top: number; left: number; width: number }>({
    top: 0, left: 0, width: 320,
  });
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res: any = await apiClient.listDeepAgents();
        const list: Agent[] = (res?.data ?? res ?? []) as Agent[];
        setAgents(list);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!open) return;
    const updateCoords = () => {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (rect) {
        setCoords({
          top: rect.bottom + window.scrollY + 8,
          left: rect.left + window.scrollX,
          width: rect.width,
        });
      }
    };
    updateCoords();
    window.addEventListener('resize', updateCoords);
    window.addEventListener('scroll', updateCoords, true);
    return () => {
      window.removeEventListener('resize', updateCoords);
      window.removeEventListener('scroll', updateCoords, true);
    };
  }, [open]);

  const selected = agents.find((a) => a.id === selectedId);

  const handleSelect = (id: number) => {
    onSelect(id);
    setOpen(false);
  };

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-4 py-2 rounded-xl transition-all"
        style={{
          background: 'linear-gradient(135deg, rgba(0, 109, 221, 0.18) 0%, rgba(127, 200, 255, 0.08) 100%)',
          border: '1px solid rgba(0, 109, 221, 0.5)',
          color: '#F2FAFF',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.3)',
        }}
      >
        <span style={{ fontSize: 16 }}>🧠</span>
        <span className="text-sm font-medium">{selected?.name ?? 'Select Agent'}</span>
        <span style={{ color: '#7FC8FF', fontSize: 12 }}>▾</span>
      </button>

      {open &&
        createPortal(
          <>
            <div
              className="fixed inset-0"
              style={{ zIndex: 9998 }}
              onClick={() => setOpen(false)}
            />
            <div
              className="absolute max-h-96 overflow-y-auto rounded-xl shadow-2xl"
              style={{
                top: coords.top,
                left: coords.left,
                minWidth: Math.max(coords.width, 320),
                background: '#0D1322',
                border: '1px solid rgba(0, 109, 221, 0.5)',
                backdropFilter: 'blur(8px)',
                zIndex: 9999,
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {loading ? (
                <div className="p-4 text-center" style={{ color: '#7FC8FF' }}>
                  Loading...
                </div>
              ) : agents.length === 0 ? (
                <div className="p-4 text-center" style={{ color: '#99D3FF' }}>
                  No agents found
                </div>
              ) : (
                agents.map((a) => (
                  <div
                    key={a.id}
                    onClick={() => handleSelect(a.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') handleSelect(a.id);
                    }}
                    className="block w-full text-left px-4 py-3 cursor-pointer transition-colors"
                    style={{
                      color: '#F2FAFF',
                      borderBottom: '1px solid rgba(0, 109, 221, 0.15)',
                      background: a.id === selectedId ? 'rgba(0, 109, 221, 0.25)' : 'transparent',
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLElement).style.background = 'rgba(0, 109, 221, 0.4)';
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLElement).style.background = a.id === selectedId
                        ? 'rgba(0, 109, 221, 0.25)'
                        : 'transparent';
                    }}
                  >
                    <div className="text-sm font-medium">{a.name}</div>
                    {a.description && (
                      <div className="text-xs mt-0.5" style={{ color: '#99D3FF' }}>
                        {a.description.slice(0, 60)}
                        {a.description.length > 60 ? '…' : ''}
                      </div>
                    )}
                    {a.category && (
                      <div className="text-[9px] uppercase tracking-wider mt-1" style={{ color: '#7FC8FF' }}>
                        {a.category}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </>,
          document.body
        )}
    </div>
  );
}
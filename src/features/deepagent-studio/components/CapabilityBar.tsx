/**
 * CapabilityBar — bottom row of chips showing tools, memory, sandbox, router.
 */

import type { Capability } from '../types';

interface Props {
  capabilities: Capability[];
}

const TYPE_COLORS: Record<string, { bg: string; fg: string; icon: string }> = {
  tool:    { bg: 'rgba(59,130,246,0.12)',  fg: '#93c5fd', icon: '🔧' },
  memory:  { bg: 'rgba(168,85,247,0.12)',  fg: '#c4b5fd', icon: '🧠' },
  sandbox: { bg: 'rgba(245,158,11,0.12)',  fg: '#fcd34d', icon: '📂' },
  router:  { bg: 'rgba(236,72,153,0.12)',  fg: '#f9a8d4', icon: '🧭' },
  prompt:  { bg: 'rgba(99,102,241,0.12)',  fg: '#a5b4fc', icon: '📝' },
};

export default function CapabilityBar({ capabilities }: Props) {
  if (capabilities.length === 0) {
    return (
      <div
        className="text-[10px] text-center py-2"
        style={{ color: 'var(--color-text-muted)', backgroundColor: 'var(--color-panel-dark)' }}
      >
        No additional capabilities
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap items-center gap-1.5 px-3 py-2"
      style={{ backgroundColor: 'var(--color-panel-dark)', borderTop: '1px solid var(--color-border)' }}
    >
      <span className="text-[10px] uppercase tracking-widest font-semibold mr-1"
        style={{ color: 'var(--color-text-muted)' }}>
        ⚙️ Capabilities:
      </span>
      {capabilities.map((cap, idx) => {
        const c = TYPE_COLORS[cap.type] ?? { bg: 'rgba(255,255,255,0.05)', fg: 'var(--color-text-muted)', icon: '•' };
        return (
          <span
            key={`${cap.type}-${idx}`}
            className="text-[10px] px-2 py-0.5 rounded-full font-medium flex items-center gap-1"
            style={{ backgroundColor: c.bg, color: c.fg }}
            title={`${cap.label}: ${cap.value}`}
          >
            <span>{c.icon}</span>
            <span>{cap.label}</span>
            {cap.type === 'tool' && <span style={{ opacity: 0.6 }}>· {cap.value}</span>}
          </span>
        );
      })}
    </div>
  );
}
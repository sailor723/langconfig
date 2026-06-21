/**
 * MainAgentNode — center node of the DeepAgent visualization.
 * Displays the agent's core config as a list of clickable property rows.
 * Each property opens a detailed popup (handled by parent DeepAgentCanvas).
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

/** Distinct visual themes per property group, so LLM / Prompt / Tools are easy to tell apart. */
const THEMES: Record<string, { bg: string; hoverBg: string; accent: string; accentSoft: string }> = {
  llm: {
    bg: 'rgba(59,130,246,0.10)',
    hoverBg: 'rgba(59,130,246,0.18)',
    accent: '#60a5fa',
    accentSoft: '#1e3a8a',
  },
  prompt: {
    bg: 'rgba(168,85,247,0.10)',
    hoverBg: 'rgba(168,85,247,0.18)',
    accent: '#c084fc',
    accentSoft: '#581c87',
  },
  tools: {
    bg: 'rgba(245,158,11,0.10)',
    hoverBg: 'rgba(245,158,11,0.18)',
    accent: '#fbbf24',
    accentSoft: '#78350f',
  },
};

interface Data {
  label: string;
  model: string;
  prompt_preview: string;
  temperature: number;
  max_tokens: number;
  middleware: string[];
  description?: string;
  use_deepagents?: boolean;
  enable_compiled_subagents?: boolean;
  use_local_sandbox?: boolean;
  tools?: string[];
}

const MainAgentNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#10b981' : 'var(--color-primary)';

  const onPropClick = (prop: string) => {
    // Custom event — parent listens and opens a popup
    window.dispatchEvent(new CustomEvent('da:open-property', {
      detail: { nodeId: 'main', prop, nodeLabel: data.label },
    }));
  };

  return (
    <div
      className="rounded-2xl px-3 py-3 shadow-lg relative h-full w-full"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        border: `2px solid ${borderColor}`,
        minWidth: 280,
        minHeight: 240,
        color: 'var(--color-text-primary)',
      }}
    >
      <NodeResizer
        color="var(--color-primary)"
        isVisible={selected}
        minWidth={280}
        minHeight={240}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 8, height: 8, borderRadius: 2 }}
      />

      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--color-primary)', opacity: 0 }} />
      <Handle type="target" position={Position.Top} style={{ background: 'var(--color-primary)', opacity: 0 }} />

      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span
          className="inline-flex items-center justify-center rounded-lg text-lg flex-shrink-0"
          style={{ width: 32, height: 32, backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          🤖
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold truncate">{data.label}</div>
          <div className="text-[10px] font-mono truncate" style={{ color: 'var(--color-text-muted)' }}>
            DeepAgent
          </div>
        </div>
        <span
          className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase flex-shrink-0"
          style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          ★ Main
        </span>
      </div>

      {/* Properties header */}
      <div
        className="text-[10px] uppercase tracking-widest font-semibold mb-1.5"
        style={{ color: 'var(--color-text-muted)' }}
      >
        ── Agent Properties ──
      </div>

      {/* Property rows — clickable (3 main groups, each with own theme) */}
      <div className="space-y-1.5 overflow-auto" style={{ maxHeight: 'calc(100% - 100px)' }}>
        <PropRow
          icon="🤖"
          label="LLM"
          value={`${data.model} · ${data.temperature.toFixed(1)} · ${data.max_tokens?.toLocaleString() ?? '—'}t`}
          onClick={() => onPropClick('llm')}
          theme={THEMES.llm}
        />
        <PropRow
          icon="📜"
          label="Prompt"
          value={`${(data.prompt_preview ?? '').length} chars`}
          onClick={() => onPropClick('prompt')}
          theme={THEMES.prompt}
        />
        {data.tools && data.tools.length > 0 && (
          <PropRow
            icon="🔧"
            label="Tools"
            value={`${data.tools.length} native`}
            onClick={() => onPropClick('tools')}
            theme={THEMES.tools}
          />
        )}
      </div>
    </div>
  );
});

/** Compact clickable row in the node card with theme-specific colors. */
function PropRow({
  icon, label, value, onClick, theme,
}: {
  icon: string;
  label: string;
  value: string;
  onClick: () => void;
  theme: { bg: string; hoverBg: string; accent: string; accentSoft: string };
}) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation(); // don't trigger ReactFlow's node selection
        onClick();
      }}
      className="w-full flex items-center gap-2 px-2 py-1 rounded text-left transition-colors"
      style={{
        backgroundColor: theme.bg,
        color: 'var(--color-text-primary)',
        borderLeft: `3px solid ${theme.accent}`,
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = theme.hoverBg; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = theme.bg; }}
    >
      <span className="text-xs">{icon}</span>
      <span className="text-[11px] flex-1 truncate font-semibold" style={{ color: theme.accent }}>{label}</span>
      <span className="text-[11px] font-mono truncate max-w-[100px]" style={{ color: 'var(--color-text-primary)' }}>{value}</span>
      <span className="text-[10px]" style={{ color: theme.accent }}>→</span>
    </button>
  );
}

MainAgentNode.displayName = 'MainAgentNode';
export default MainAgentNode;
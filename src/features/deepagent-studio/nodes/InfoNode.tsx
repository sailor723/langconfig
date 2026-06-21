/**
 * InfoNode — compact themed card displayed on the canvas, linked to the
 * Main Agent via an edge. Used for LLM and Prompt properties.
 *
 * Rich key/value formatting for LLM, full prompt (scrollable + expand toggle)
 * for Prompt.
 */

import { memo, useState } from 'react';
import { Maximize2, Minimize2 } from 'lucide-react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

export type InfoKind = 'llm' | 'prompt';

interface Data {
  kind: InfoKind;
  label: string;
  /** LLM-specific */
  model?: string;
  temperature?: number;
  max_tokens?: number;
  context_window?: number;  // optional
  /** Prompt-specific */
  prompt?: string;
  /** Theme colors */
  bg: string;
  accent: string;
  border: string;
}

const InfoNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#A85A2E' : data.border;
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className="rounded-lg px-2 py-1.5 shadow-sm relative h-full w-full flex flex-col"
      style={{
        backgroundColor: data.bg,
        border: `1.5px solid ${borderColor}`,
        color: '#1F1E1B',
        minWidth: 170,
        minHeight: 80,
      }}
    >
      <NodeResizer
        color={data.accent}
        isVisible={selected}
        minWidth={170}
        minHeight={80}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 5, height: 5, borderRadius: 2 }}
      />

      {/* Handle — connects back to Main Agent */}
      <Handle
        type="source"
        position={data.kind === 'llm' ? Position.Right : Position.Left}
        style={{ background: data.accent, opacity: 0 }}
      />
      <Handle type="target" position={Position.Top} style={{ background: data.accent, opacity: 0 }} />

      {/* Header */}
      <div
        className="flex items-center gap-1 mb-1 pb-1"
        style={{ borderBottom: `1px solid ${data.border}` }}
      >
        <span className="text-[10px]" style={{ color: data.accent }}>
          {data.kind === 'llm' ? '🤖' : '📜'}
        </span>
        <div
          className="text-[8px] uppercase tracking-widest font-bold flex-1 truncate"
          style={{ color: data.accent }}
        >
          {data.label}
        </div>
        {data.kind === 'prompt' && (
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(v => !v); }}
            onMouseDown={(e) => e.stopPropagation()}
            title={expanded ? 'Collapse' : 'Expand to fit prompt'}
            className="flex items-center justify-center rounded transition-colors hover:bg-black/10"
            style={{ width: 16, height: 16, color: data.accent, flexShrink: 0 }}
          >
            {expanded ? <Minimize2 size={10} /> : <Maximize2 size={10} />}
          </button>
        )}
      </div>

      {/* Body */}
      {data.kind === 'llm' ? (
        <div className="flex-1 flex flex-col gap-0.5 text-[9px] overflow-hidden">
          <KV label="MODEL" value={data.model ?? '—'} accentColor={data.accent} />
          <KV label="TEMP" value={data.temperature?.toFixed(2) ?? '—'} accentColor={data.accent} />
          <KV label="MAX" value={data.max_tokens ? `${data.max_tokens.toLocaleString()}` : '—'} accentColor={data.accent} />
          {data.context_window !== undefined && (
            <KV label="CTX" value={`${(data.context_window / 1000).toFixed(0)}k`} accentColor={data.accent} />
          )}
        </div>
      ) : (
        <div
          className="flex-1 text-[9px] leading-snug font-mono overflow-auto whitespace-pre-wrap"
          style={{
            color: '#1F1E1B',
            scrollbarWidth: 'thin',
          }}
        >
          {data.prompt || '(empty — no system prompt)'}
        </div>
      )}
    </div>
  );
});

/** Compact key-value row inside InfoNode. */
function KV({ label, value, accentColor }: { label: string; value: string; accentColor: string }) {
  return (
    <div className="flex items-center gap-1 overflow-hidden">
      <span
        className="text-[8px] font-bold uppercase tracking-wider flex-shrink-0"
        style={{ color: accentColor, minWidth: 32 }}
      >
        {label}
      </span>
      <span className="font-mono font-medium truncate" style={{ color: '#1F1E1B' }}>
        {value}
      </span>
    </div>
  );
}

InfoNode.displayName = 'InfoNode';
export default InfoNode;
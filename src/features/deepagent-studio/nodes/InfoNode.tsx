/**
 * InfoNode — a thematic "property" node displayed on the canvas and linked
 * to the Main Agent via an edge. Used for LLM and Prompt properties.
 *
 * Unlike ToolNode (a small pill), InfoNode is a proper card showing key
 * details inline so the user can see them at a glance without opening.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

export type InfoKind = 'llm' | 'prompt';

interface Data {
  kind: InfoKind;
  label: string;             // e.g. "LLM" or "Prompt"
  /** LLM-specific */
  model?: string;
  temperature?: number;
  max_tokens?: number;
  /** Prompt-specific */
  prompt?: string;
  /** Theme colors */
  bg: string;
  accent: string;
  border: string;
}

const InfoNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#10b981' : data.border;
  return (
    <div
      className="rounded-xl px-3 py-2 shadow-md relative h-full w-full"
      style={{
        backgroundColor: data.bg,
        border: `2px solid ${borderColor}`,
        color: 'var(--color-text-primary)',
        minWidth: 180,
        minHeight: 80,
      }}
    >
      <NodeResizer
        color={data.accent}
        isVisible={selected}
        minWidth={180}
        minHeight={80}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 6, height: 6, borderRadius: 2 }}
      />

      <Handle type="target" position={Position.Top} style={{ background: data.accent, opacity: 0 }} />

      {/* Header */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-sm" style={{ color: data.accent }}>
          {data.kind === 'llm' ? '🤖' : '📜'}
        </span>
        <div
          className="text-[10px] uppercase tracking-widest font-bold"
          style={{ color: data.accent }}
        >
          {data.label}
        </div>
      </div>

      {/* Body */}
      {data.kind === 'llm' ? (
        <div className="space-y-0.5 text-[10px] overflow-auto" style={{ maxHeight: 'calc(100% - 26px)' }}>
          <div className="font-mono font-semibold truncate" title={data.model} style={{ color: 'var(--color-text-primary)' }}>
            {data.model}
          </div>
          <div style={{ color: 'var(--color-text-muted)' }}>
            <span className="font-mono">{data.temperature?.toFixed(2)}</span>
            <span className="mx-1">·</span>
            <span className="font-mono">{data.max_tokens?.toLocaleString() ?? '—'}t</span>
          </div>
        </div>
      ) : (
        <div
          className="text-[10px] leading-snug font-mono overflow-auto whitespace-pre-wrap"
          style={{
            color: 'var(--color-text-primary)',
            maxHeight: 'calc(100% - 26px)',
            opacity: 0.85,
          }}
        >
          {data.prompt?.slice(0, 200) ?? '(empty)'}
          {(data.prompt?.length ?? 0) > 200 && '…'}
        </div>
      )}
    </div>
  );
});

InfoNode.displayName = 'InfoNode';
export default InfoNode;
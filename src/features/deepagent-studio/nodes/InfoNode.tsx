/**
 * InfoNode — compact themed card displayed on the canvas, linked to the
 * Main Agent via an edge. Used for LLM and Prompt properties.
 *
 * Smaller and denser — shows full content (scrollable for long prompts).
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

export type InfoKind = 'llm' | 'prompt';

interface Data {
  kind: InfoKind;
  label: string;
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
      className="rounded-lg px-2 py-1.5 shadow-sm relative h-full w-full flex flex-col"
      style={{
        backgroundColor: data.bg,
        border: `1.5px solid ${borderColor}`,
        color: 'var(--color-text-primary)',
        minWidth: 160,
        minHeight: 80,
      }}
    >
      <NodeResizer
        color={data.accent}
        isVisible={selected}
        minWidth={160}
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
          className="text-[8px] uppercase tracking-widest font-bold"
          style={{ color: data.accent }}
        >
          {data.label}
        </div>
      </div>

      {/* Body */}
      {data.kind === 'llm' ? (
        <div className="flex-1 flex flex-col justify-center gap-1 text-[9px] overflow-hidden">
          <div className="font-mono font-bold truncate" title={data.model} style={{ color: 'var(--color-text-primary)' }}>
            {data.model}
          </div>
          <div className="flex items-center gap-2" style={{ color: 'var(--color-text-muted)' }}>
            <span className="flex items-center gap-0.5">
              <span style={{ color: data.accent }}>🌡</span>
              <span className="font-mono">{data.temperature?.toFixed(2)}</span>
            </span>
            <span className="flex items-center gap-0.5">
              <span style={{ color: data.accent }}>📏</span>
              <span className="font-mono">{((data.max_tokens ?? 0) / 1000).toFixed(1)}k</span>
            </span>
          </div>
        </div>
      ) : (
        <div
          className="flex-1 text-[9px] leading-snug font-mono overflow-auto whitespace-pre-wrap"
          style={{
            color: 'var(--color-text-primary)',
            opacity: 0.9,
            scrollbarWidth: 'thin',
          }}
        >
          {data.prompt || '(empty — no system prompt)'}
        </div>
      )}
    </div>
  );
});

InfoNode.displayName = 'InfoNode';
export default InfoNode;
/**
 * MainAgentNode — center node of the DeepAgent visualization.
 * Now a simple identifier card. Property nodes (LLM, Prompt) live on the
 * canvas as separate InfoNodes linked by edges.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

interface Data {
  label: string;
  model: string;
  description?: string;
}

const MainAgentNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#10b981' : 'var(--color-primary)';
  return (
    <div
      className="rounded-2xl px-4 py-4 shadow-lg relative h-full w-full flex flex-col items-center justify-center text-center"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        border: `2px solid ${borderColor}`,
        minWidth: 220,
        minHeight: 160,
        color: 'var(--color-text-primary)',
      }}
    >
      <NodeResizer
        color="var(--color-primary)"
        isVisible={selected}
        minWidth={220}
        minHeight={160}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 8, height: 8, borderRadius: 2 }}
      />

      {/* Handles — connect LLM, Prompt, Tool, Sub-agent nodes */}
      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--color-primary)', opacity: 0 }} />
      <Handle type="source" position={Position.Left} id="left" style={{ background: '#60a5fa', opacity: 0 }} />
      <Handle type="source" position={Position.Right} id="right" style={{ background: '#c084fc', opacity: 0 }} />
      <Handle type="target" position={Position.Top} style={{ background: 'var(--color-primary)', opacity: 0 }} />

      {/* Icon */}
      <span
        className="inline-flex items-center justify-center rounded-2xl text-2xl flex-shrink-0 mb-2"
        style={{ width: 48, height: 48, backgroundColor: 'var(--color-primary)', color: '#fff' }}
      >
        🤖
      </span>

      {/* Name + Main badge */}
      <div className="flex items-center gap-1.5 mb-0.5">
        <div className="text-base font-bold truncate">{data.label}</div>
        <span
          className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase"
          style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          ★ Main
        </span>
      </div>

      <div className="text-[10px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
        DeepAgent · {data.model}
      </div>

      {data.description && (
        <div className="text-[10px] mt-1 px-2 text-center" style={{ color: 'var(--color-text-muted)' }}>
          {data.description.slice(0, 60)}{data.description.length > 60 ? '…' : ''}
        </div>
      )}
    </div>
  );
});

MainAgentNode.displayName = 'MainAgentNode';
export default MainAgentNode;
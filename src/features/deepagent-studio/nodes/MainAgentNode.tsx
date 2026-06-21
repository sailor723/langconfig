/**
 * MainAgentNode — compact center card. Properties live as separate
 * InfoNodes (LLM left, Prompt right, Tools bottom, Sub-agents ring).
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
      className="rounded-xl px-2 py-2 shadow-md relative h-full w-full flex flex-col items-center justify-center text-center"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        border: `2px solid ${borderColor}`,
        minWidth: 160,
        minHeight: 110,
        color: 'var(--color-text-primary)',
      }}
    >
      <NodeResizer
        color="var(--color-primary)"
        isVisible={selected}
        minWidth={160}
        minHeight={110}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 6, height: 6, borderRadius: 2 }}
      />

      {/* Handles — left for LLM, right for Prompt, bottom for Tools/Subs, top for incoming */}
      <Handle type="source" position={Position.Left} id="llm-out" style={{ background: '#60a5fa', opacity: 0 }} />
      <Handle type="source" position={Position.Right} id="prompt-out" style={{ background: '#c084fc', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--color-primary)', opacity: 0 }} />
      <Handle type="target" position={Position.Top} style={{ background: 'var(--color-primary)', opacity: 0 }} />

      {/* Icon */}
      <span
        className="inline-flex items-center justify-center rounded-lg text-base flex-shrink-0 mb-1"
        style={{ width: 28, height: 28, backgroundColor: 'var(--color-primary)', color: '#fff' }}
      >
        🤖
      </span>

      {/* Name + Main badge */}
      <div className="flex items-center gap-1 mb-0.5">
        <div className="text-[11px] font-bold truncate">{data.label}</div>
        <span
          className="text-[7px] px-1 py-px rounded font-bold uppercase"
          style={{ backgroundColor: 'var(--color-primary)', color: '#fff' }}
        >
          ★ Main
        </span>
      </div>

      <div className="text-[8px] font-mono" style={{ color: 'var(--color-text-muted)' }}>
        {data.model}
      </div>
    </div>
  );
});

MainAgentNode.displayName = 'MainAgentNode';
export default MainAgentNode;
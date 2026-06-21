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
  const borderColor = selected ? '#A85A2E' : '#D97757';
  return (
    <div
      className="rounded-xl px-2 py-2 shadow-md relative h-full w-full flex flex-col items-center justify-center text-center"
      style={{
        backgroundColor: '#D97757',
        border: `2px solid ${borderColor}`,
        minWidth: 160,
        minHeight: 110,
        color: '#FFFFFF',
      }}
    >
      <NodeResizer
        color="#A85A2E"
        isVisible={selected}
        minWidth={160}
        minHeight={110}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 6, height: 6, borderRadius: 2 }}
      />

      {/* Handles — left for LLM, right for Prompt, bottom for Tools/Subs, top for incoming */}
      <Handle type="source" position={Position.Left} id="llm-out" style={{ background: '#C75F3D', opacity: 0 }} />
      <Handle type="source" position={Position.Right} id="prompt-out" style={{ background: '#A85A2E', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} id="tools-out" style={{ background: '#D97757', opacity: 0 }} />
      <Handle type="target" position={Position.Top} style={{ background: '#D97757', opacity: 0 }} />

      {/* Icon */}
      <span
        className="inline-flex items-center justify-center rounded-lg text-base flex-shrink-0 mb-1"
        style={{ width: 28, height: 28, backgroundColor: '#FFFFFF', color: '#D97757' }}
      >
        🤖
      </span>

      {/* Name + Main badge */}
      <div className="flex items-center gap-1 mb-0.5">
        <div className="text-[11px] font-bold truncate" style={{ color: '#FFFFFF' }}>{data.label}</div>
        <span
          className="text-[7px] px-1 py-px rounded font-bold uppercase"
          style={{ backgroundColor: '#FFFFFF', color: '#D97757' }}
        >
          ★ Main
        </span>
      </div>

      <div className="text-[8px] font-mono" style={{ color: '#FAF9F5', opacity: 0.85 }}>
        {data.model}
      </div>

      {data.description && (
        <div
          className="text-[8px] mt-1 px-1 text-center"
          style={{
            color: '#FAF9F5',
            opacity: 0.85,
            maxHeight: 32,
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
          }}
          title={data.description}
        >
          {data.description}
        </div>
      )}
    </div>
  );
});

MainAgentNode.displayName = 'MainAgentNode';
export default MainAgentNode;
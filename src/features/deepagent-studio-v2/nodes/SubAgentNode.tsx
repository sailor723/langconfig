/**
 * SubAgentNode — pill-shaped glass node with blue accent.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

interface Data {
  label: string;
  description?: string;
  skill_type?: string;
}

const SubAgentNode = memo(({ data, selected }: NodeProps<Data>) => {
  return (
    <div
      className="rounded-xl px-3 py-2 text-center transition-all"
      style={{
        background: selected
          ? 'linear-gradient(135deg, rgba(0, 109, 221, 0.35) 0%, rgba(127, 200, 255, 0.2) 100%)'
          : 'linear-gradient(135deg, rgba(0, 109, 221, 0.18) 0%, rgba(127, 200, 255, 0.08) 100%)',
        border: `1px solid ${selected ? '#7FC8FF' : 'rgba(0, 109, 221, 0.5)'}`,
        backdropFilter: 'blur(8px)',
        minWidth: 140,
        color: '#F2FAFF',
        pointerEvents: 'all',
        cursor: 'grab',
        boxShadow: selected
          ? '0 0 14px rgba(127, 200, 255, 0.4)'
          : '0 2px 8px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(127, 200, 255, 0.1)',
      }}
    >
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />

      {/* Skill-type tag */}
      <div
        className="text-[9px] uppercase tracking-wider mb-1 font-bold"
        style={{ color: '#7FC8FF' }}
      >
        {data.skill_type || 'Skill'}
      </div>

      {/* Name */}
      <div className="text-[13px] font-semibold truncate" style={{ color: '#F2FAFF' }}>
        {data.label}
      </div>

      {data.description && (
        <div
          className="text-[10px] mt-1 leading-tight"
          style={{
            color: '#99D3FF',
            maxWidth: 130,
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

SubAgentNode.displayName = 'SubAgentNode';
export default SubAgentNode;

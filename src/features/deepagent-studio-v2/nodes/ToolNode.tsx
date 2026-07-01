/**
 * ToolNode — small chip with tool icon.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

interface Data {
  label: string;
  tool_type?: string;
}

const ToolNode = memo(({ data, selected }: NodeProps<Data>) => {
  const icon = data.tool_type === 'native' ? '⚙️' : '🔧';
  return (
    <div
      className="rounded-md px-2 py-1 text-center inline-flex items-center gap-1.5"
      style={{
        background: selected
          ? 'rgba(127, 200, 255, 0.18)'
          : 'rgba(13, 19, 34, 0.85)',
        border: `1px solid ${selected ? '#7FC8FF' : 'rgba(0, 109, 221, 0.4)'}`,
        backdropFilter: 'blur(6px)',
        color: '#F2FAFF',
        pointerEvents: 'all',
        cursor: 'grab',
        boxShadow: selected
          ? '0 0 10px rgba(127, 200, 255, 0.3)'
          : '0 2px 6px rgba(0, 0, 0, 0.4)',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <span style={{ fontSize: 13 }}>{icon}</span>
      <span className="text-[12px] font-medium">{data.label}</span>
    </div>
  );
});

ToolNode.displayName = 'ToolNode';
export default ToolNode;

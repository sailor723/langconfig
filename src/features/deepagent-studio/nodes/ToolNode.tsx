/**
 * ToolNode — small pill showing a native tool the agent has access to.
 * Displayed around the main agent when there are no sub-agents.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

interface Data {
  label: string;
  description?: string;
}

const ToolNode = memo(({ data, selected }: NodeProps<Data>) => {
  const borderColor = selected ? '#10b981' : 'rgba(59,130,246,0.5)';
  return (
    <div
      className="rounded-full px-3 py-1.5 shadow-sm relative"
      style={{
        backgroundColor: 'rgba(59,130,246,0.12)',
        border: `1.5px solid ${borderColor}`,
        color: '#93c5fd',
        fontFamily: 'monospace',
        fontSize: 11,
        whiteSpace: 'nowrap',
      }}
    >
      <NodeResizer
        color="#3b82f6"
        isVisible={selected}
        minWidth={80}
        minHeight={28}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 6, height: 6, borderRadius: 2 }}
      />
      <Handle type="target" position={Position.Top} style={{ background: '#3b82f6', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#3b82f6', opacity: 0 }} />
      <span>🔧 {data.label}</span>
    </div>
  );
});

ToolNode.displayName = 'ToolNode';
export default ToolNode;
/**
 * SubAgentNode — circular node representing a sub-agent.
 * Lights up during execution when the Skill Router selects it.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';
import type { ExecutionStatus } from '../types';

interface Data {
  id?: string;
  label: string;
  description: string;
  source: 'skill' | 'user' | 'generated';
  tools: string[];
  instructions_preview?: string;
  status: ExecutionStatus;
}

const SubAgentNode = memo(({ id, data, selected }: NodeProps<Data>) => {
  const statusColor: Record<ExecutionStatus, string> = {
    idle: '#C8B6A6',
    running: '#3b82f6',
    success: '#10b981',
    error: '#ef4444',
  };

  const borderColor = selected
    ? '#A85A2E'
    : statusColor[data.status] ?? '#C8B6A6';

  const isActive = data.status === 'running';

  return (
    <div
      className="rounded-xl px-3 py-2 shadow-md relative h-full w-full"
      style={{
        backgroundColor: '#FAF9F5',
        border: `2px solid ${borderColor}`,
        minWidth: 160,
        minHeight: 100,
        color: '#1F1E1B',
        animation: isActive ? 'da-pulse 1.2s ease-in-out infinite' : 'none',
      }}
    >
      <NodeResizer
        color="#C75F3D"
        isVisible={selected}
        minWidth={160}
        minHeight={100}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 7, height: 7, borderRadius: 2 }}
      />

      <Handle type="target" position={Position.Top} style={{ background: '#C75F3D', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#C75F3D', opacity: 0 }} />

      {/* Sub-Agent badge — node IS a sub-agent, skill is just a property */}
      <div className="flex items-center justify-between mb-1">
        <span
          className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase"
          style={{
            backgroundColor: '#F5E6DC',
            color: '#A85A2E',
            border: '1px solid #D97757',
          }}
        >
          🤖 sub-agent
        </span>
        {isActive && (
          <span className="text-[9px] animate-pulse" style={{ color: '#3b82f6' }}>
            ⚡ running
          </span>
        )}
      </div>

      {/* Name */}
      <div className="text-xs font-semibold truncate" title={data.label} style={{ color: '#1F1E1B' }}>
        {data.label}
      </div>

      {/* Skill property (inline tag — shows which skill this sub-agent is backed by) */}
      {data.source === 'skill' && (
        <div
          className="text-[9px] mt-1 px-1.5 py-0.5 rounded truncate font-mono flex items-center gap-1"
          style={{
            backgroundColor: 'rgba(168,90,46,0.10)',
            color: '#A85A2E',
            border: '1px dashed #D97757',
          }}
          title={`Backed by skill: ${id}`}
        >
          <span>🎯</span>
          <span className="truncate">skill: {id}</span>
        </div>
      )}
      {data.source === 'user' && (
        <div
          className="text-[9px] mt-1 px-1.5 py-0.5 rounded truncate font-mono flex items-center gap-1"
          style={{
            backgroundColor: 'rgba(168,90,46,0.05)',
            color: '#5C5A55',
            border: '1px dashed #C8B6A6',
          }}
        >
          <span>👤</span>
          <span className="truncate">user-defined</span>
        </div>
      )}

      {/* Description */}
      {data.description && (
        <div
          className="text-[10px] mt-1 leading-snug"
          style={{
            color: '#5C5A55',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
          }}
          title={data.description}
        >
          {data.description}
        </div>
      )}

      {/* Tools count */}
      {data.tools && data.tools.length > 0 && (
        <div className="text-[9px] mt-1" style={{ color: '#A85A2E' }}>
          🔧 {data.tools.length} tool{data.tools.length > 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
});

SubAgentNode.displayName = 'SubAgentNode';
export default SubAgentNode;
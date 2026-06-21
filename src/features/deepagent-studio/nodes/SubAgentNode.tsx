/**
 * SubAgentNode — circular node representing a sub-agent.
 * Lights up during execution when the Skill Router selects it.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';
import type { ExecutionStatus } from '../types';

interface Data {
  label: string;
  description: string;
  source: 'skill' | 'user' | 'generated';
  tools: string[];
  instructions_preview?: string;
  status: ExecutionStatus;
}

const SubAgentNode = memo(({ data, selected }: NodeProps<Data>) => {
  const statusColor: Record<ExecutionStatus, string> = {
    idle: 'var(--color-border)',
    running: '#3b82f6',     // blue, will be animated
    success: '#10b981',     // green
    error: '#ef4444',       // red
  };

  const borderColor = selected
    ? '#10b981'
    : statusColor[data.status] ?? 'var(--color-border)';

  const isActive = data.status === 'running';

  return (
    <div
      className="rounded-xl px-3 py-2 shadow-md relative h-full w-full"
      style={{
        backgroundColor: 'var(--color-panel-dark)',
        border: `2px solid ${borderColor}`,
        minWidth: 160,
        minHeight: 100,
        color: 'var(--color-text-primary)',
        animation: isActive ? 'da-pulse 1.2s ease-in-out infinite' : 'none',
      }}
    >
      {/* Resize handles (only visible when selected) */}
      <NodeResizer
        color="var(--color-primary)"
        isVisible={selected}
        minWidth={160}
        minHeight={100}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 7, height: 7, borderRadius: 2 }}
      />

      {/* Handles */}
      <Handle type="target" position={Position.Top} style={{ background: 'var(--color-primary)', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--color-primary)', opacity: 0 }} />

      {/* Source badge */}
      <div className="flex items-center justify-between mb-1">
        <span
          className="text-[9px] px-1.5 py-0.5 rounded font-bold uppercase"
          style={{
            backgroundColor: data.source === 'skill' ? 'rgba(99,102,241,0.15)' : 'rgba(245,158,11,0.15)',
            color: data.source === 'skill' ? '#a5b4fc' : '#fbbf24',
          }}
        >
          {data.source === 'skill' ? '📚 skill' : '👤 user'}
        </span>
        {isActive && (
          <span className="text-[9px] animate-pulse" style={{ color: '#3b82f6' }}>
            ⚡ running
          </span>
        )}
      </div>

      {/* Name */}
      <div className="text-xs font-semibold truncate" title={data.label}>
        {data.label}
      </div>

      {/* Description — fills available height */}
      {data.description && (
        <div
          className="text-[10px] mt-1 leading-snug overflow-auto"
          style={{
            color: 'var(--color-text-muted)',
            maxHeight: 'calc(100% - 60px)',
          }}
          title={data.description}
        >
          {data.description}
        </div>
      )}

      {/* Tools count */}
      {data.tools && data.tools.length > 0 && (
        <div className="text-[9px] mt-1" style={{ color: 'var(--color-text-muted)' }}>
          🔧 {data.tools.length} tool{data.tools.length > 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
});

SubAgentNode.displayName = 'SubAgentNode';
export default SubAgentNode;
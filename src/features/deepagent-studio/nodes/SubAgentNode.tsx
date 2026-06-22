/**
 * SubAgentNode — large info card for a sub-agent. Shows all properties
 * (skill backing, model, description, prompt preview, tools count) inline.
 * Clicking the body opens a popup with full skill details.
 */

import { memo } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';
import type { ExecutionStatus } from '../types';

interface Data {
  id?: string;
  label: string;
  description: string;
  source: 'skill' | 'user' | 'generated';
  model?: string;
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

  /** Open the SubAgentDetail modal — dispatched as window event. */
  const openDetail = (e: React.MouseEvent) => {
    e.stopPropagation();
    window.dispatchEvent(new CustomEvent('da:open-subagent-detail', {
      detail: {
        id,
        label: data.label,
        description: data.description,
        source: data.source,
        model: data.model,
        tools: data.tools,
        instructions_preview: data.instructions_preview,
        status: data.status,
      },
    }));
  };

  const promptPreview = data.instructions_preview ?? '';

  return (
    <div
      onClick={openDetail}
      className="rounded-xl px-3 py-2 shadow-md relative h-full w-full cursor-pointer hover:shadow-lg transition-shadow"
      style={{
        backgroundColor: '#FAF9F5',
        border: `2px solid ${borderColor}`,
        minWidth: 240,
        minHeight: 180,
        color: '#1F1E1B',
        animation: isActive ? 'da-pulse 1.2s ease-in-out infinite' : 'none',
      }}
    >
      <NodeResizer
        color="#C75F3D"
        isVisible={selected}
        minWidth={240}
        minHeight={180}
        lineStyle={{ borderWidth: 1, opacity: 0.4 }}
        handleStyle={{ width: 8, height: 8, borderRadius: 2 }}
      />

      <Handle type="target" position={Position.Top} style={{ background: '#C75F3D', opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#C75F3D', opacity: 0 }} />

      {/* Top row: sub-agent badge + running indicator */}
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
        {!isActive && (
          <span className="text-[8px] opacity-60" style={{ color: '#A85A2E' }}>
            click ↗
          </span>
        )}
      </div>

      {/* Name */}
      <div className="text-sm font-semibold truncate" title={data.label} style={{ color: '#1F1E1B' }}>
        {data.label}
      </div>

      {/* Skill property (inline tag) */}
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
          className="text-[10px] mt-1.5 leading-snug"
          style={{
            color: '#5C5A55',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
          }}
          title={data.description}
        >
          {data.description}
        </div>
      )}

      {/* KEY/VALUE properties (model, prompt, tools) */}
      <div className="mt-1.5 flex flex-col gap-0.5">
        {data.model && (
          <KV label="MODEL" value={data.model} />
        )}
        <KV label="PROMPT" value={promptPreview ? `${promptPreview.slice(0, 60)}${promptPreview.length > 60 ? '…' : ''}` : '(empty)'} />
        <KV label="TOOLS" value={data.tools?.length ? `${data.tools.length} bound` : '0'} />
      </div>
    </div>
  );
});

/** Compact key/value row inside SubAgentNode. */
function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-1 overflow-hidden">
      <span
        className="text-[8px] font-bold uppercase tracking-wider flex-shrink-0"
        style={{ color: '#A85A2E', minWidth: 38 }}
      >
        {label}
      </span>
      <span
        className="font-mono text-[9px] truncate"
        style={{ color: '#1F1E1B' }}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}

SubAgentNode.displayName = 'SubAgentNode';
export default SubAgentNode;
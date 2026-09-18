/**
 * MainAgentNode — central glowing core (LangChain aesthetic).
 * Pulses with a soft blue glow. Electric gradient ring.
 */

import { memo, useState, useRef } from 'react';
import { Handle, Position, NodeProps, NodeResizer } from 'reactflow';

interface Data {
  label: string;
  model: string;
  description?: string;
  system_prompt?: string;
}

const MainAgentNode = memo(({ data, selected }: NodeProps<Data>) => {
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const handleMouseEnter = () => {
    tooltipTimer.current = setTimeout(() => setShowTooltip(true), 600);
  };
  const handleMouseLeave = () => {
    clearTimeout(tooltipTimer.current);
    setShowTooltip(false);
  };

  return (
    <div
      className="rounded-2xl px-3 py-3 relative flex flex-col items-center justify-center text-center"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        background: 'linear-gradient(135deg, #161F34 0%, #0D1322 100%)',
        border: `2px solid ${selected ? '#7FC8FF' : '#006DDD'}`,
        width: 200,
        height: 140,
        minWidth: 180,
        minHeight: 120,
        color: '#F2FAFF',
        pointerEvents: 'all',
        cursor: 'grab',
        boxShadow: selected
          ? '0 0 24px rgba(127, 200, 255, 0.6), inset 0 0 12px rgba(127, 200, 255, 0.15)'
          : '0 0 16px rgba(0, 109, 221, 0.4), inset 0 0 8px rgba(127, 200, 255, 0.1)',
        animation: 'pulse-glow 3s ease-in-out infinite',
      }}
    >
      <NodeResizer
        color="#7FC8FF"
        isVisible={selected}
        minWidth={180}
        minHeight={120}
        lineStyle={{ borderWidth: 1, opacity: 0.5 }}
        handleStyle={{ width: 6, height: 6, borderRadius: 2, backgroundColor: '#7FC8FF' }}
      />

      {/* Handles — invisible but functional */}
      <Handle type="source" position={Position.Left} id="llm-out" style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} id="prompt-out" style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} id="tools-out" style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />

      {/* Brain icon with gradient bg */}
      <span
        className="inline-flex items-center justify-center rounded-lg text-base flex-shrink-0 mb-1.5"
        style={{
          width: 42,
          height: 42,
          background: 'linear-gradient(135deg, #006DDD 0%, #7FC8FF 100%)',
          color: '#FFFFFF',
          fontSize: 24,
        }}
      >
        🧠
      </span>

      {/* Name + Main badge */}
      <div className="flex items-center gap-1.5 mb-0.5">
        <div className="text-[17px] font-semibold truncate" style={{ color: '#F2FAFF' }}>{data.label}</div>
        <span
          className="text-[11px] px-2 py-0.5 rounded font-bold uppercase tracking-wider"
          style={{
            background: 'linear-gradient(90deg, #006DDD, #7FC8FF)',
            color: '#F2FAFF',
          }}
        >
          Main
        </span>
      </div>

      <div
        className="text-[14px] font-mono mt-0.5 px-2 py-1 rounded"
        style={{
          color: '#99D3FF',
          backgroundColor: 'rgba(0, 109, 221, 0.15)',
        }}
      >
        {data.model}
      </div>

      {data.description && (
        <div
          className="text-[13px] mt-1.5 px-1.5 text-center leading-tight"
          style={{
            color: '#99D3FF',
            maxHeight: 36,
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

      {/* Hover tooltip — shows description and system prompt */}
      {showTooltip && (data.description || data.system_prompt) && (
        <div
          className="absolute z-50 px-3 py-2 rounded-lg text-xs shadow-2xl"
          style={{
            background: '#0D1322',
            border: '1px solid rgba(0, 109, 221, 0.5)',
            color: '#F2FAFF',
            top: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginTop: 8,
            minWidth: 200,
            maxWidth: 300,
            pointerEvents: 'none',
          }}
        >
          {data.description && <div className="mb-1">{data.description}</div>}
          {data.system_prompt && (
            <div className="text-[10px] leading-tight" style={{ color: '#99D3FF' }}>
              {data.system_prompt.slice(0, 200)}
              {data.system_prompt.length > 200 ? '…' : ''}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

MainAgentNode.displayName = 'MainAgentNode';
export default MainAgentNode;

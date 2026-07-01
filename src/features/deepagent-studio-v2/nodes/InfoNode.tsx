/**
 * InfoNode — property display with expandable content (for system prompt).
 * Press Escape to collapse if expanded.
 */

import { memo, useState, useEffect, useCallback } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

interface Data {
  label: string;
  value: string;
  icon?: string;
  description?: string;
}

const InfoNode = memo(({ data, selected }: NodeProps<Data>) => {
  const [expanded, setExpanded] = useState(false);
  const isLong = (data.value?.length || 0) > 60;
  const displayValue = expanded ? data.value : (data.value?.slice(0, 60) + (isLong ? '…' : ''));

  // Collapse on Escape
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape' && expanded) {
        setExpanded(false);
      }
    },
    [expanded]
  );

  useEffect(() => {
    if (!expanded) return;
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [expanded, handleKeyDown]);

  return (
    <div
      className="rounded-lg text-left transition-all"
      style={{
        background: selected
          ? 'linear-gradient(135deg, rgba(0, 109, 221, 0.2), rgba(127, 200, 255, 0.1))'
          : 'rgba(22, 31, 52, 0.85)',
        border: `1px solid ${selected ? '#7FC8FF' : 'rgba(0, 109, 221, 0.35)'}`,
        backdropFilter: 'blur(6px)',
        color: '#F2FAFF',
        width: expanded ? 420 : 'auto',
        minWidth: 180,
        maxWidth: 480,
        pointerEvents: 'all',
        cursor: 'grab',
        boxShadow: '0 2px 6px rgba(0, 0, 0, 0.3)',
      }}
    >
      <Handle type="source" position={Position.Right} id="info-out" style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />

      <div className="px-2.5 py-1.5">
        <div
          className="text-[13px] uppercase tracking-wider mb-0.5 font-bold flex items-center gap-1"
          style={{ color: '#7FC8FF' }}
        >
          {data.icon && <span>{data.icon}</span>}
          <span>{data.label}</span>
        </div>
        {data.description && (
          <div
            className="text-[10px] mb-1"
            style={{ color: '#99D3FF' }}
            title={data.description}
          >
            {data.description}
          </div>
        )}
        <div
          className="text-[15px] font-medium"
          style={{ color: '#F2FAFF', whiteSpace: expanded ? 'pre-wrap' : 'nowrap', overflow: 'hidden', textOverflow: expanded ? 'clip' : 'ellipsis' }}
          title={data.value}
        >
          {displayValue}
        </div>
      </div>

      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="block w-full text-center text-[12px] py-1 transition-colors"
          style={{
            color: '#7FC8FF',
            background: 'rgba(0, 109, 221, 0.1)',
            borderTop: '1px solid rgba(0, 109, 221, 0.25)',
            cursor: 'pointer',
          }}
        >
          {expanded ? '▲ Collapse (Esc)' : '▼ View full'}
        </button>
      )}
    </div>
  );
});

InfoNode.displayName = 'InfoNode';
export default InfoNode;
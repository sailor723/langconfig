/**
 * SubAgentNode — pill-shaped glass node with prompt button and hover tooltip.
 */

import { memo, useState, useRef, useEffect } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

interface Data {
  label: string;
  description?: string;
  skill_type?: string;
  prompt?: string;
  tags?: string[];
  triggers?: string[];
  allowed_tools?: string[];
  version?: string;
  author?: string;
}

const SubAgentNode = memo(({ data }: NodeProps<Data>) => {
  const [showTooltip, setShowTooltip] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const tooltipTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const handleMouseEnter = () => {
    tooltipTimer.current = setTimeout(() => setShowTooltip(true), 600);
  };
  const handleMouseLeave = () => {
    clearTimeout(tooltipTimer.current);
    setShowTooltip(false);
  };

  // Close prompt on Escape
  useEffect(() => {
    if (!showPrompt) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowPrompt(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showPrompt]);

  // Lock body scroll when prompt modal is open — also block wheel from reaching ReactFlow
  const wheelBlockerRef = useRef<((e: WheelEvent) => void) | null>(null);
  useEffect(() => {
    if (showPrompt) {
      document.body.style.overflow = 'hidden';
      const blocker = (e: WheelEvent) => {
        const modal = document.querySelector('[data-modal="skill-prompt"]');
        if (modal && !modal.contains(e.target as Node)) {
          e.preventDefault();
          e.stopPropagation();
        }
      };
      wheelBlockerRef.current = blocker;
      window.addEventListener('wheel', blocker, { passive: false, capture: true });
    }
    return () => {
      document.body.style.overflow = '';
      if (wheelBlockerRef.current) {
        window.removeEventListener('wheel', wheelBlockerRef.current, { capture: true } as EventListenerOptions);
      }
    };
  }, [showPrompt]);

  return (
    <div
      className="relative"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div
        className="rounded-xl px-3 py-2 text-center transition-all"
        style={{
          background: 'linear-gradient(135deg, rgba(0, 109, 221, 0.18) 0%, rgba(127, 200, 255, 0.08) 100%)',
          border: '1px solid rgba(0, 109, 221, 0.5)',
          backdropFilter: 'blur(8px)',
          minWidth: 170,
          color: '#F2FAFF',
          pointerEvents: 'all',
          cursor: 'grab',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(127, 200, 255, 0.1)',
        }}
      >
        <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />

        {/* Skill-type tag */}
        <div
          className="text-[11px] uppercase tracking-wider mb-1 font-bold flex items-center justify-center gap-1"
          style={{ color: '#7FC8FF' }}
        >
          {data.skill_type || 'Skill'}
          {data.prompt && (
            <span
              className="inline-flex items-center justify-center rounded w-4 h-4 cursor-pointer transition-colors"
              style={{ color: '#99D3FF', fontSize: 11 }}
              onClick={(e) => {
                e.stopPropagation();
                setShowPrompt(!showPrompt);
              }}
              title="View prompt"
            >
              📜
            </span>
          )}
        </div>

        {/* Name */}
        <div
          className="text-[16px] font-semibold truncate"
          style={{ color: '#F2FAFF' }}
          title={data.label}
        >
          {data.label}
        </div>

        {data.description && (
          <div
            className="text-[13px] mt-1 leading-tight"
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

      {/* Hover tooltip */}
      {showTooltip && !showPrompt && (data.description || data.prompt) && (
        <div
          className="absolute z-50 px-3 py-2 rounded-lg text-xs shadow-2xl"
          style={{
            background: '#0D1322',
            border: '1px solid rgba(0, 109, 221, 0.5)',
            color: '#F2FAFF',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: 8,
            minWidth: 180,
            maxWidth: 260,
            pointerEvents: 'none',
          }}
        >
          {data.description && <div className="mb-1">{data.description}</div>}
          {data.prompt && (
            <div className="text-[10px]" style={{ color: '#99D3FF' }}>
              {data.prompt.slice(0, 120)}
              {data.prompt.length > 120 ? '…' : ''}
            </div>
          )}
        </div>
      )}

      {/* Prompt modal */}
      {showPrompt && data.prompt && (
        <>
          <div
            className="fixed inset-0 z-50"
            style={{ background: 'rgba(0, 0, 0, 0.6)' }}
            onClick={() => setShowPrompt(false)}
            onWheel={(e) => e.stopPropagation()}
          />
          <div
            data-modal="skill-prompt"
            className="fixed z-50 rounded-xl shadow-2xl xwide-scrollbar"
            style={{
              background: '#0D1322',
              border: '1px solid rgba(0, 109, 221, 0.5)',
              color: '#F2FAFF',
              top: '15%',
              left: '15%',
              right: '15%',
              bottom: '15%',
              minWidth: 360,
              minHeight: 600,
              resize: 'both',
              overflow: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
          >
            <div className="p-4 pb-0">
              <div className="flex items-center justify-between mb-2">
                <div className="text-sm font-semibold" style={{ color: '#7FC8FF' }}>
                  {data.label} Prompt
                </div>
                <button
                  onClick={() => setShowPrompt(false)}
                  className="p-1 rounded hover:bg-white/10"
                  style={{ color: '#99D3FF' }}
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="px-4 pb-4">
              <div className="text-[15px] whitespace-pre-wrap leading-relaxed" style={{ color: '#F2FAFF' }}>
                {data.prompt}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
});

SubAgentNode.displayName = 'SubAgentNode';
export default SubAgentNode;

/**
 * InfoNode — property display with click-to-open modal for full content.
 * Press Escape to close the modal.
 */

import { memo, useState, useEffect, useCallback, useRef } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

interface Data {
  label: string;
  value: string;
  icon?: string;
  description?: string;
}

const InfoNode = memo(({ data, selected }: NodeProps<Data>) => {
  const [showModal, setShowModal] = useState(false);
  const isLong = (data.value?.length || 0) > 60;

  // Close modal on Escape
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape' && showModal) {
        setShowModal(false);
      }
    },
    [showModal]
  );

  useEffect(() => {
    if (!showModal) return;
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showModal, handleKeyDown]);

  // Lock body scroll when modal is open — also block wheel from reaching ReactFlow canvas
  const wheelBlockerRef = useRef<((e: WheelEvent) => void) | null>(null);
  useEffect(() => {
    if (showModal) {
      // Capture wheel at window level before ReactFlow sees it
      const blocker = (e: WheelEvent) => {
        const modal = document.querySelector('[data-modal="info-node"]');
        // Allow wheel if the target is inside the modal or sidebar
        if (modal && modal.contains(e.target as Node)) return;
        const sidebar = (e.target as HTMLElement)?.closest?.('[class*="detail-panel"]');
        if (sidebar) return;
        // Allow wheel if the target is NOT inside the ReactFlow canvas
        const flowPane = (e.target as HTMLElement)?.closest?.('.react-flow__pane');
        if (!flowPane) return;
        // Block wheel on the ReactFlow canvas when modal is open
        e.preventDefault();
        e.stopPropagation();
      };
      wheelBlockerRef.current = blocker;
      window.addEventListener('wheel', blocker, { passive: false, capture: true });
    }
    return () => {
      if (wheelBlockerRef.current) {
        window.removeEventListener('wheel', wheelBlockerRef.current, { capture: true } as EventListenerOptions);
      }
    };
  }, [showModal]);

  return (
    <>
      <div
        className="rounded-lg text-left transition-all"
        style={{
          background: selected
            ? 'linear-gradient(135deg, rgba(0, 109, 221, 0.2), rgba(127, 200, 255, 0.1))'
            : 'rgba(22, 31, 52, 0.85)',
          border: `1px solid ${selected ? '#7FC8FF' : 'rgba(0, 109, 221, 0.35)'}`,
          backdropFilter: 'blur(6px)',
          color: '#F2FAFF',
          width: 'auto',
          minWidth: 180,
          maxWidth: 480,
          pointerEvents: 'all',
          cursor: 'pointer',
          boxShadow: '0 2px 6px rgba(0, 0, 0, 0.3)',
        }}
        onClick={() => setShowModal(true)}
        title="Click to view full content"
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
            style={{
              color: '#F2FAFF',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
            title={data.value}
          >
            {data.value?.slice(0, 60)}
            {isLong ? '…' : ''}
          </div>
        </div>

        {isLong && (
          <div
            className="block w-full text-center text-[10px] py-1 rounded-b-lg"
            style={{
              color: '#7FC8FF',
              background: 'rgba(0, 109, 221, 0.1)',
              borderTop: '1px solid rgba(0, 109, 221, 0.25)',
            }}
          >
            👁️ 点击查看完整内容
          </div>
        )}
      </div>

      {/* Full content modal */}
      {showModal && (
        <>
          <div
            className="fixed inset-0 z-50"
            style={{ background: 'rgba(0, 0, 0, 0.6)' }}
            onClick={() => setShowModal(false)}
            onWheel={(e) => e.stopPropagation()}
          />
          <div
            data-modal="info-node"
            className="fixed z-50 rounded-xl shadow-2xl xwide-scrollbar"
            style={{
              background: '#0D1322',
              border: '1px solid rgba(0, 109, 221, 0.5)',
              color: '#F2FAFF',
              top: '10%',
              left: '10%',
              right: '10%',
              bottom: '10%',
              minWidth: 420,
              minHeight: 900,
              resize: 'both',
              overflow: 'auto',
            }}
            onClick={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
          >
            <div className="p-6 pb-0">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  {data.icon && <span style={{ fontSize: 20 }}>{data.icon}</span>}
                  <div>
                    <div className="text-sm font-semibold" style={{ color: '#7FC8FF' }}>
                      {data.label}
                    </div>
                    {data.description && (
                      <div className="text-[11px]" style={{ color: '#99D3FF' }}>
                        {data.description}
                      </div>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => setShowModal(false)}
                  className="p-1.5 rounded hover:bg-white/10"
                  style={{ color: '#99D3FF', fontSize: 16 }}
                >
                  ✕
                </button>
              </div>
            </div>
            <div className="px-6 pb-6">
              <div className="text-[15px] whitespace-pre-wrap leading-relaxed">
                {data.value || '(empty)'}
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
});

InfoNode.displayName = 'InfoNode';
export default InfoNode;

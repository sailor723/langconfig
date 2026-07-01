/**
 * ToolNode — small chip with tool icon. Click opens details.
 */

import { memo, useState, useEffect } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';

interface Data {
  label: string;
  description?: string;
  tool_type?: string;
  prompt?: string;
}

const ToolNode = memo(({ data }: NodeProps<Data>) => {
  const [showDetails, setShowDetails] = useState(false);
  const icon = data.tool_type === 'native' ? '⚙️' : '🔧';

  // Close on Escape
  useEffect(() => {
    if (!showDetails) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowDetails(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [showDetails]);

  const hasDetails = data.description || data.prompt;

  return (
    <>
      <div
        className="rounded-md px-2 py-1 text-center inline-flex items-center gap-1.5"
        style={{
          background: 'rgba(13, 19, 34, 0.85)',
          border: '1px solid rgba(0, 109, 221, 0.4)',
          backdropFilter: 'blur(6px)',
          color: '#F2FAFF',
          pointerEvents: 'all',
          cursor: hasDetails ? 'pointer' : 'grab',
          boxShadow: '0 2px 6px rgba(0, 0, 0, 0.4)',
        }}
        onClick={(e) => {
          if (hasDetails) {
            e.stopPropagation();
            setShowDetails(true);
          }
        }}
        title={hasDetails ? 'Click for details' : data.label}
      >
        <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
        <span style={{ fontSize: 16 }}>{icon}</span>
        <span className="text-[15px] font-medium">{data.label}</span>
      </div>

      {/* Details modal */}
      {showDetails && hasDetails && (
        <>
          <div
            className="fixed inset-0 z-50"
            style={{ background: 'rgba(0, 0, 0, 0.6)' }}
            onClick={() => setShowDetails(false)}
          />
          <div
            className="fixed z-50 p-4 rounded-xl shadow-2xl max-w-lg max-h-[60vh] overflow-y-auto"
            style={{
              background: '#0D1322',
              border: '1px solid rgba(0, 109, 221, 0.5)',
              color: '#F2FAFF',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
              minWidth: 320,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span style={{ fontSize: 18 }}>{icon}</span>
                <span className="text-base font-semibold" style={{ color: '#F2FAFF' }}>
                  {data.label}
                </span>
                <span
                  className="text-[9px] uppercase px-2 py-0.5 rounded font-bold"
                  style={{
                    background: 'linear-gradient(90deg, #006DDD, #7FC8FF)',
                    color: '#F2FAFF',
                  }}
                >
                  {data.tool_type || 'tool'}
                </span>
              </div>
              <button
                onClick={() => setShowDetails(false)}
                className="p-1 rounded hover:bg-white/10"
                style={{ color: '#99D3FF' }}
              >
                ✕
              </button>
            </div>

            {data.description && (
              <div className="mb-3">
                <div className="text-[10px] uppercase tracking-wider mb-1 font-bold" style={{ color: '#7FC8FF' }}>Description</div>
                <div className="text-[13px]">{data.description}</div>
              </div>
            )}

            {data.prompt && (
              <div>
                <div className="text-[10px] uppercase tracking-wider mb-1 font-bold" style={{ color: '#7FC8FF' }}>Prompt</div>
                <div className="text-[12px] whitespace-pre-wrap leading-relaxed">{data.prompt}</div>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
});

ToolNode.displayName = 'ToolNode';
export default ToolNode;

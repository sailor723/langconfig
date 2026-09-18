/**
 * HitlInterruptModal — Overlay for Human-in-the-Loop approval requests.
 */
import { AlertTriangle } from 'lucide-react';
import type { InterruptData } from '../types/chat';

interface HitlInterruptModalProps {
  pendingInterrupt: InterruptData;
  isResuming: boolean;
  onResume: (action: 'approve' | 'reject' | 'edit' | 'respond', value?: string) => void;
}

export default function HitlInterruptModal({
  pendingInterrupt,
  isResuming,
  onResume,
}: HitlInterruptModalProps) {
  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-[100]"
      onClick={() => {}}
    >
      <div
        className="bg-white dark:bg-panel-dark rounded-xl w-full max-w-lg shadow-2xl border"
        style={{ borderColor: 'var(--color-border-dark)' }}
        onClick={e => e.stopPropagation()}
      >
        <div className="px-5 py-3 rounded-t-xl flex items-center gap-3" style={{ backgroundColor: '#f59e0b' }}>
          <AlertTriangle className="w-5 h-5 text-white flex-shrink-0" />
          <div>
            <h3 className="text-base font-semibold text-white">Human Approval Required</h3>
            <p className="text-xs text-white/80 mt-0.5">
              An agent action needs your approval before proceeding
            </p>
          </div>
        </div>

        <div className="p-5 space-y-4">
          {pendingInterrupt.action_requests?.map((req, i) => (
            <div key={i} className="p-3 rounded-lg border" style={{
              borderColor: 'var(--color-border-dark)',
              backgroundColor: 'var(--color-background-light)'
            }}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                  {req.name}
                </span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200">
                  Tool Call
                </span>
              </div>
              <div className="text-xs space-y-1" style={{ color: 'var(--color-text-secondary)' }}>
                {req.description && <p className="italic">{req.description}</p>}
                {req.args && Object.keys(req.args).length > 0 && (
                  <pre className="mt-1 p-2 rounded text-xs font-mono overflow-x-auto" style={{
                    backgroundColor: 'var(--color-background)',
                    color: 'var(--color-text-primary)',
                    maxHeight: '120px'
                  }}>
                    {JSON.stringify(req.args, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          ))}

          {(!pendingInterrupt.action_requests || pendingInterrupt.action_requests.length === 0) && (
            <div className="p-3 rounded-lg border" style={{
              borderColor: 'var(--color-border-dark)',
              backgroundColor: 'var(--color-background-light)'
            }}>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Agent paused before executing actions.
              </p>
              {pendingInterrupt.tool_calls && pendingInterrupt.tool_calls.length > 0 && (
                <pre className="mt-2 p-2 rounded text-xs font-mono overflow-x-auto" style={{
                  backgroundColor: 'var(--color-background)',
                  color: 'var(--color-text-primary)',
                  maxHeight: '120px'
                }}>
                  {JSON.stringify(pendingInterrupt.tool_calls, null, 2)}
                </pre>
              )}
              {pendingInterrupt.next_nodes && (
                <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>
                  Next nodes: {pendingInterrupt.next_nodes.join(', ')}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t flex items-center justify-end gap-2" style={{
          borderColor: 'var(--color-border-dark)'
        }}>
          <button
            onClick={() => onResume('reject')}
            disabled={isResuming}
            className="px-4 py-2 rounded-lg text-sm font-medium border transition-colors"
            style={{
              borderColor: 'var(--color-border-dark)',
              color: 'var(--color-text-primary)',
              backgroundColor: 'var(--color-background-light)'
            }}
          >
            Reject
          </button>
          {pendingInterrupt.review_configs?.[0]?.allowed_decisions?.includes('edit') && (
            <button
              onClick={() => onResume('edit')}
              disabled={isResuming}
              className="px-4 py-2 rounded-lg text-sm font-medium border transition-colors"
              style={{
                borderColor: 'var(--color-border-dark)',
                color: 'var(--color-text-primary)',
                backgroundColor: 'var(--color-background-light)'
              }}
            >
              Edit
            </button>
          )}
          <button
            onClick={() => onResume('approve')}
            disabled={isResuming}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ backgroundColor: '#16a34a' }}
          >
            {isResuming ? 'Resuming...' : 'Approve'}
          </button>
        </div>
      </div>
    </div>
  );
}

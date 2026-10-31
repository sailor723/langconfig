/**
 * HitlApprovalPanel — the composer-takeover approval prompt.
 *
 * It borrows DeepSeek Harness's shape (packages/client/ui-conversation
 * ApprovalPanel): while a tool call waits for review, this card takes the
 * composer's slot instead of floating over the transcript, so the buttons sit
 * where the user's hands already are and never scroll away.
 *
 * Two decisions, one shot: allow (this call only) or reject. LangChain's
 * middleware also understands `edit` and `respond`; neither is offered here on
 * purpose — editing a call's arguments makes the model re-plan and often retry,
 * and `respond` only means "I am this tool", which no button can express. The
 * endpoint still accepts them for automation.
 */
import type { InterruptData } from '../types/chat';
import { COMPOSER_MAX_WIDTH } from './CodexMessageInput';

interface HitlApprovalPanelProps {
  pendingInterrupt: InterruptData;
  isResuming: boolean;
  onResume: (action: 'approve' | 'reject' | 'edit' | 'respond', value?: string) => void;
  /** Set once the reviewer answered; the card stays until the run resumes. */
  onDismiss?: () => void;
}

export default function HitlApprovalPanel({
  pendingInterrupt,
  isResuming,
  onResume,
}: HitlApprovalPanelProps) {
  const requests = pendingInterrupt.action_requests ?? [];
  const allowed = pendingInterrupt.review_configs?.[0]?.allowed_decisions ?? ['approve', 'reject'];
  const canApprove = allowed.includes('approve');
  const canReject = allowed.includes('reject');

  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        maxWidth: COMPOSER_MAX_WIDTH,
        margin: '0 auto',
        border: '1px solid var(--color-border-dark)',
        backgroundColor: 'var(--color-background-light)',
        boxShadow: '0 2px 10px rgba(0,0,0,0.08)',
      }}
    >
      {/* Amber strip: this is a state, not a message. */}
      <div
        className="flex items-center gap-2 px-4 py-2.5"
        style={{ backgroundColor: 'rgba(245, 158, 11, 0.14)', color: '#b45309' }}
      >
        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: '#f59e0b' }} />
        <span className="text-xs font-semibold">等待你批准 · 工具还没执行</span>
      </div>

      {/* Scroll region: the proposed arguments are unbounded text. The actions
          below stay outside it so they are always reachable. */}
      <div className="px-4 py-3 space-y-2" style={{ maxHeight: 220, overflowY: 'auto' }}>
        {requests.length === 0 && (
          <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            agent 在工具调用前停下了。
          </p>
        )}
        {requests.map((req, i) => (
          <div key={i} className="space-y-1">
            <p className="text-xs font-medium" style={{ color: 'var(--color-text-primary)' }}>
              {req.name}
              {requests.length > 1 ? `（${i + 1}/${requests.length}）` : ''}
            </p>
            <pre
              className="p-2 rounded text-xs font-mono overflow-x-auto"
              style={{
                backgroundColor: 'var(--color-input-background, #e5e7eb)',
                color: 'var(--color-text-primary)',
                margin: 0,
                maxHeight: 140,
              }}
            >
              {JSON.stringify(req.args, null, 2)}
            </pre>
          </div>
        ))}
      </div>

      <div className="px-4 py-2.5 flex items-center justify-end gap-2 border-t"
        style={{ borderColor: 'var(--color-border-dark)' }}>
        <span className="text-xs mr-auto" style={{ color: 'var(--color-text-muted)' }}>
          批准只对这一次有效
        </span>
        {canReject && (
          <button
            onClick={() =>
              onResume('reject', 'Reviewer rejected this tool call. Do not retry it unless asked.')
            }
            disabled={isResuming}
            className="px-3 py-1.5 rounded-lg text-xs font-medium border disabled:opacity-50"
            style={{ borderColor: 'var(--color-border-dark)', color: 'var(--color-text-primary)' }}
          >
            拒绝
          </button>
        )}
        {canApprove && (
          <button
            onClick={() => onResume('approve')}
            disabled={isResuming}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: '#16a34a' }}
          >
            {isResuming ? '执行中…' : '批准这一次'}
          </button>
        )}
      </div>
    </div>
  );
}

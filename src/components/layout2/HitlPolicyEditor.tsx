/**
 * HitlPolicyEditor — "which tool calls must be reviewed before they run".
 *
 * Sits in the Guardrails section of both agent editors (AgentEditor gets the
 * section for the first time; DeepAgentEditor already had one). The data is
 * `guardrails.interrupts`, the same object LangChain's HumanInTheLoopMiddleware
 * reads as `interrupt_on`:
 *
 *   { "write_file": { "allowed_decisions": ["approve", "reject"] },
 *     "delete": true }
 *
 * Only approve/reject are offered, matching the approval card: editing a call's
 * arguments makes the model re-plan, and `respond` means "I am this tool" —
 * neither belongs on a button. `true` (all decisions) is preserved if it is
 * already in the config; the editor just shows it as "批准/拒绝".
 */
import type { LayoutTokens } from './tokens';

export type InterruptOn = Record<
  string,
  boolean | { allowed_decisions?: string[]; when?: string }
>;

/** Predicates the backend knows by name (core/middleware/predicates.py). */
const WHEN_OPTIONS: Record<string, { value: string; label: string }[]> = {
  bash: [
    { value: '', label: '每条命令都要批' },
    { value: 'bash_may_mutate', label: '只读命令不批（ls / cat / grep …）' },
  ],
  write_file: [
    { value: '', label: '每次写都要批' },
    { value: 'writes_deliverable', label: '只批交付物（other/、skills/ 里的不批）' },
  ],
};

interface HitlPolicyEditorProps {
  /** ``HumanInTheLoopMiddleware(interrupt_on=...)`` — the documented shape. */
  value: InterruptOn | undefined;
  onChange: (next: InterruptOn) => void;
  /** Tool ids that are actually selected on this agent — nothing else is offered. */
  candidateTools: string[];
  t: LayoutTokens;
}

const DECISIONS = ['approve', 'reject'] as const;

/** Tools that change something outside the conversation; the bulk switch targets these. */
export const MUTATING_TOOLS = [
  'write_file',
  'edit_file',
  'delete',
  'bash',
  'python_execute',
  'sqlite_execute',
  'pg_execute',
];

export default function HitlPolicyEditor({ value, onChange, candidateTools, t }: HitlPolicyEditorProps) {
  const policy: InterruptOn = value ?? {};
  const gated = Object.keys(policy);
  const offered = Array.from(new Set([...candidateTools, ...gated])).sort();

  const gate = (tool: string, on: boolean) => {
    const next: InterruptOn = { ...policy };
    if (on) next[tool] = { allowed_decisions: [...DECISIONS] };
    else delete next[tool];
    onChange(next);
  };

  const gateAllMutating = () => {
    const next: InterruptOn = { ...policy };
    const present = MUTATING_TOOLS.filter(tool => offered.includes(tool));
    const allGated = present.length > 0 && present.every(tool => tool in next);
    for (const tool of present) {
      if (allGated) delete next[tool];
      else next[tool] = { allowed_decisions: [...DECISIONS] };
    }
    onChange(next);
  };

  const mutatingPresent = MUTATING_TOOLS.filter(tool => offered.includes(tool));
  const allMutatingGated = mutatingPresent.length > 0 && mutatingPresent.every(tool => tool in policy);

  const card = {
    border: `1px solid ${t.border}`,
    borderRadius: 6,
    padding: 10,
    marginTop: 8,
    background: t.bgSidebar,
  } as const;

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ color: t.textPrimary, fontSize: 12, fontWeight: 600 }}>
          需要人工批准的工具
        </div>
        {mutatingPresent.length > 0 && (
          <button
            onClick={gateAllMutating}
            style={{
              padding: '3px 10px',
              borderRadius: 12,
              cursor: 'pointer',
              border: `1px solid ${allMutatingGated ? t.accent : t.border}`,
              background: allMutatingGated ? `${t.accent}18` : 'transparent',
              color: allMutatingGated ? t.accent : t.textMuted,
              fontSize: 11,
              fontWeight: 500,
            }}
          >
            {allMutatingGated ? '全部会改东西的工具已拦' : '拦下所有会改东西的工具'}
          </button>
        )}
      </div>

      <div style={{ fontSize: 10, color: t.textMuted, marginTop: 4, lineHeight: '14px' }}>
        勾上的工具在调用前会停下来，等你在聊天里点「批准这一次」或「拒绝」。
        批准只对那一次生效；{`15`} 分钟不批按拒绝处理。
      </div>

      {offered.length === 0 ? (
        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 8 }}>
          先在 Tools 里勾选工具，这里才会出现可选项。
        </div>
      ) : (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 2 }}>
          {offered.map(tool => {
            const on = tool in policy;
            const allDecisions = on && policy[tool] === true;
            return (
              <label
                key={tool}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '4px 6px',
                  borderRadius: 4,
                  cursor: 'pointer',
                  background: on ? `${t.accent}0d` : 'transparent',
                }}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={e => gate(tool, e.target.checked)}
                  style={{ accentColor: t.accent, cursor: 'pointer' }}
                />
                <span style={{ fontFamily: 'monospace', fontSize: 11, color: t.textPrimary }}>
                  {tool}
                </span>
                {on && WHEN_OPTIONS[tool] && (
                  <select
                    value={
                      typeof policy[tool] === 'object'
                        ? ((policy[tool] as any).when ?? '')
                        : ''
                    }
                    onChange={e => {
                      const when = e.target.value;
                      const spec =
                        typeof policy[tool] === 'object'
                          ? { ...(policy[tool] as any) }
                          : { allowed_decisions: [...DECISIONS] };
                      if (when) spec.when = when;
                      else delete spec.when;
                      onChange({ ...policy, [tool]: spec });
                    }}
                    style={{
                      marginLeft: 8,
                      fontSize: 10,
                      background: t.bgContent,
                      color: t.textPrimary,
                      border: `1px solid ${t.border}`,
                      borderRadius: 4,
                      padding: '2px 4px',
                    }}
                  >
                    {WHEN_OPTIONS[tool].map(opt => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                )}
                {allDecisions && (
                  <span style={{ fontSize: 10, color: t.textMuted }}>
                    （配置里允许全部四种决策，界面只给批准/拒绝）
                  </span>
                )}
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

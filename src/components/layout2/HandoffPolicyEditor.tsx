/**
 * HandoffPolicyEditor — steps, the tools each step may use, and the edges
 * between them.
 *
 * LangChain's handoff pattern: one tool per target (`transfer_to_support`), and
 * middleware that swaps the system prompt and tool set when that tool is called.
 * This editor writes exactly the config the backend turns into that:
 *
 *   {"type": "handoff", "enabled": true, "config": {
 *      "state_field": "handoff_to",
 *      "default_step": "sales",
 *      "steps": {
 *        "sales": {"label": "售前", "description": "产品与报价",
 *                  "system_prompt": "...", "tools": ["web_search"],
 *                  "transfers": [{"to": "support", "description": "技术故障交给售后"}]}
 *      }}}
 *
 * The transfer tool is generated from the edge, so the sentence written here is
 * the routing decision the model reads — not a label nobody uses.
 */
import { useState } from 'react';
import type { LayoutTokens } from './tokens';

interface TransferEdge {
  to: string;
  description?: string;
  message?: string;
}

interface HandoffStep {
  label?: string;
  description?: string;
  system_prompt?: string;
  tools?: string[];
  transfers?: TransferEdge[];
}

export interface HandoffConfig {
  state_field?: string;
  default_step?: string;
  steps?: Record<string, HandoffStep>;
}

interface HandoffPolicyEditorProps {
  value: HandoffConfig | undefined;
  onChange: (next: HandoffConfig) => void;
  /** Tool ids selected on this agent — what a step can be granted. */
  candidateTools: string[];
  t: LayoutTokens;
}

const input = (t: LayoutTokens) => ({
  width: '100%',
  boxSizing: 'border-box' as const,
  padding: '5px 8px',
  fontSize: 11,
  background: t.bgContent,
  color: t.textPrimary,
  border: `1px solid ${t.border}`,
  borderRadius: 4,
  outline: 'none',
});

export default function HandoffPolicyEditor({
  value,
  onChange,
  candidateTools,
  t,
}: HandoffPolicyEditorProps) {
  const config: HandoffConfig = value ?? {};
  const steps = config.steps ?? {};
  const stepNames = Object.keys(steps);
  const [expanded, setExpanded] = useState<string | null>(stepNames[0] ?? null);

  const write = (next: HandoffConfig) => onChange(next);

  const patchStep = (name: string, patch: Partial<HandoffStep>) =>
    write({ ...config, steps: { ...steps, [name]: { ...steps[name], ...patch } } });

  const addStep = () => {
    let i = stepNames.length + 1;
    let name = `step_${i}`;
    while (steps[name]) name = `step_${++i}`;
    write({
      ...config,
      default_step: config.default_step || name,
      steps: { ...steps, [name]: { label: '', description: '', system_prompt: '', tools: [], transfers: [] } },
    });
    setExpanded(name);
  };

  const removeStep = (name: string) => {
    const next = { ...steps };
    delete next[name];
    for (const key of Object.keys(next)) {
      next[key] = {
        ...next[key],
        transfers: (next[key].transfers ?? []).filter(e => e.to !== name),
      };
    }
    write({
      ...config,
      steps: next,
      default_step: config.default_step === name ? Object.keys(next)[0] : config.default_step,
    });
  };

  const patchEdge = (name: string, index: number, patch: Partial<TransferEdge>) => {
    const edges = [...(steps[name].transfers ?? [])];
    edges[index] = { ...edges[index], ...patch };
    patchStep(name, { transfers: edges });
  };

  const card = {
    border: `1px solid ${t.border}`,
    borderRadius: 6,
    padding: 8,
    marginTop: 8,
    background: t.bgSidebar,
  } as const;

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ color: t.textPrimary, fontSize: 12, fontWeight: 600 }}>
          转交（handoff）
        </div>
        <button
          onClick={addStep}
          style={{
            padding: '3px 10px', borderRadius: 12, cursor: 'pointer',
            border: `1px dashed ${t.accent}`, background: 'transparent',
            color: t.accent, fontSize: 11, fontWeight: 500,
          }}
        >
          + 添加步骤
        </button>
      </div>

      <div style={{ fontSize: 10, color: t.textMuted, marginTop: 4, lineHeight: '14px' }}>
        每个「转交」会自动生成一个 <code>transfer_to_&lt;目标&gt;</code> 工具（只带 reason 参数）；
        模型调它之后，agent 换成目标步骤的提示词与工具继续回答。
        一个步骤可以转给多个目标；不写转交就没有转交工具。
      </div>

      {stepNames.length === 0 && (
        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 8 }}>
          还没有步骤。先「+ 添加步骤」。
        </div>
      )}

      {stepNames.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
          <span style={{ fontSize: 11, color: t.textMuted }}>起始步骤</span>
          <select
            value={config.default_step ?? stepNames[0]}
            onChange={e => write({ ...config, default_step: e.target.value })}
            style={{ ...input(t), width: 160 }}
          >
            {stepNames.map(n => (
              <option key={n} value={n}>{steps[n].label ? `${steps[n].label}（${n}）` : n}</option>
            ))}
          </select>
        </div>
      )}

      {stepNames.map(name => {
        const step = steps[name];
        const open = expanded === name;
        const granted = new Set(step.tools ?? []);
        return (
          <div key={name} style={{ ...card, background: t.bgContent, marginTop: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                onClick={() => setExpanded(open ? null : name)}
                style={{
                  flex: 1, textAlign: 'left', background: 'transparent', border: 'none',
                  cursor: 'pointer', color: t.textPrimary, fontSize: 12, fontWeight: 600,
                  fontFamily: 'monospace',
                }}
              >
                {open ? '▾' : '▸'} {name}
                {step.label ? ` · ${step.label}` : ''}
              </button>
              {config.default_step === name && (
                <span style={{ fontSize: 10, color: t.accent }}>起始</span>
              )}
              <button
                onClick={() => removeStep(name)}
                style={{ border: 'none', background: 'transparent', cursor: 'pointer',
                         color: t.textMuted, fontSize: 11 }}
              >
                删除
              </button>
            </div>

            {open && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <input
                  value={step.label ?? ''}
                  onChange={e => patchStep(name, { label: e.target.value })}
                  placeholder="显示名（如 售后支持）"
                  style={input(t)}
                />
                <input
                  value={step.description ?? ''}
                  onChange={e => patchStep(name, { description: e.target.value })}
                  placeholder="这一步负责什么（一句话）"
                  style={input(t)}
                />
                <textarea
                  value={step.system_prompt ?? ''}
                  onChange={e => patchStep(name, { system_prompt: e.target.value })}
                  placeholder="这一步的 system prompt"
                  rows={4}
                  style={{ ...input(t), fontFamily: 'inherit', resize: 'vertical' }}
                />

                <div style={{ fontSize: 11, color: t.textMuted }}>这一步可用的工具</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {candidateTools.length === 0 && (
                    <span style={{ fontSize: 10, color: t.textMuted }}>（先在 Tools 里勾选工具）</span>
                  )}
                  {candidateTools.map(tool => (
                    <label
                      key={tool}
                      style={{
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        fontSize: 10, fontFamily: 'monospace',
                        padding: '2px 6px', borderRadius: 4,
                        border: `1px solid ${granted.has(tool) ? t.accent : t.border}`,
                        color: granted.has(tool) ? t.accent : t.textMuted,
                        cursor: 'pointer',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={granted.has(tool)}
                        onChange={e => {
                          const nextTools = new Set(granted);
                          if (e.target.checked) nextTools.add(tool);
                          else nextTools.delete(tool);
                          patchStep(name, { tools: [...nextTools] });
                        }}
                        style={{ accentColor: t.accent, cursor: 'pointer' }}
                      />
                      {tool}
                    </label>
                  ))}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                  <span style={{ fontSize: 11, color: t.textMuted }}>转交</span>
                  <button
                    onClick={() => patchStep(name, {
                      transfers: [...(step.transfers ?? []), { to: '', description: '' }],
                    })}
                    style={{
                      padding: '2px 8px', borderRadius: 10, cursor: 'pointer',
                      border: `1px dashed ${t.accent}`, background: 'transparent',
                      color: t.accent, fontSize: 10,
                    }}
                  >
                    + 转到某个步骤
                  </button>
                </div>

                {(step.transfers ?? []).map((edge, i) => (
                  <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                    <select
                      value={edge.to}
                      onChange={e => patchEdge(name, i, { to: e.target.value })}
                      style={{ ...input(t), width: 130 }}
                    >
                      <option value="">（选择目标）</option>
                      {stepNames.filter(n => n !== name).map(n => (
                        <option key={n} value={n}>{steps[n].label ? `${steps[n].label}（${n}）` : n}</option>
                      ))}
                    </select>
                    <input
                      value={edge.description ?? ''}
                      onChange={e => patchEdge(name, i, { description: e.target.value })}
                      placeholder="什么时候该转给它（模型按这句判断）"
                      style={{ ...input(t), flex: 1 }}
                    />
                    <button
                      onClick={() => patchStep(name, {
                        transfers: (step.transfers ?? []).filter((_, idx) => idx !== i),
                      })}
                      style={{ border: 'none', background: 'transparent', cursor: 'pointer',
                               color: t.textMuted, fontSize: 11 }}
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

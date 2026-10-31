/**
 * HandoffPolicyEditor — 谁 → 谁 的转交关系图。
 *
 * 配置形态（后端据此生成 `transfer_to_<to>` 工具，中间件按 state 换提示词/工具）：
 *
 *   {"type": "handoff", "enabled": true, "config": {
 *      "state_field": "handoff_to",
 *      "default_step": "sales",
 *      "steps": {"sales": {"label": "售前", "system_prompt": "...", "tools": [...],
 *                          "transfers": [{"to": "support", "description": "技术故障交给售后"}]}}}}
 *
 * 编辑器分两块：**角色**（说什么、能用什么工具）与**转交关系**（一行 = 从谁到谁 =
 * 一个生成的工具）。组件自持 draft 做即时反馈，父层的值只有在真的不同时才覆盖它。
 */
import { useEffect, useMemo, useState } from 'react';
import type { LayoutTokens } from './tokens';

interface TransferEdge { to: string; description?: string; message?: string }
interface HandoffStep {
  label?: string; description?: string; system_prompt?: string;
  tools?: string[]; transfers?: TransferEdge[];
}
export interface HandoffConfig {
  state_field?: string; default_step?: string; steps?: Record<string, HandoffStep>;
}
interface Props {
  value: HandoffConfig | undefined;
  onChange: (next: HandoffConfig) => void;
  candidateTools: string[];
  t: LayoutTokens;
  /**
   * 变化时强制用 value 重置草稿（例如“服务器配置载入完成”、切到另一个 agent）。
   * 内容比较会在用户输入过程中保留草稿，只有这个信号才代表“外面换了一份配置”。
   */
  resetKey?: string;
}

const box = (t: LayoutTokens) => ({
  width: '100%', boxSizing: 'border-box' as const, padding: '5px 8px', fontSize: 11,
  background: t.bgContent, color: t.textPrimary,
  border: `1px solid ${t.border}`, borderRadius: 4, outline: 'none' as const,
});

const smallBtn = (t: LayoutTokens, accent = false) => ({
  padding: '2px 8px', borderRadius: 10, cursor: 'pointer',
  border: `1px ${accent ? 'dashed' : 'solid'} ${accent ? t.accent : t.border}`,
  background: 'transparent', color: accent ? t.accent : t.textMuted, fontSize: 10,
});

export default function HandoffPolicyEditor({ value, onChange, candidateTools, t, resetKey }: Props) {
  const [draft, setDraft] = useState<HandoffConfig>(value ?? {});
  const incoming = useMemo(() => JSON.stringify(value ?? {}), [value]);
  useEffect(() => {
    setDraft(prev => (JSON.stringify(prev) === incoming ? prev : JSON.parse(incoming)));
  }, [incoming]);

  // 服务器配置到位（或换了 agent）时无条件重置：此时屏幕上的草稿不是用户正在写的东西。
  useEffect(() => {
    setDraft(value ?? {});
  }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const steps = draft.steps ?? {};
  const stepNames = Object.keys(steps);
  const edges = useMemo(
    () => stepNames.flatMap(from => (steps[from].transfers ?? []).map((edge, index) => ({ from, index, edge }))),
    [steps, stepNames],
  );

  const commit = (next: HandoffConfig) => { setDraft(next); onChange(next); };
  const patchStep = (name: string, patch: Partial<HandoffStep>) =>
    commit({ ...draft, steps: { ...steps, [name]: { ...steps[name], ...patch } } });

  const addStep = () => {
    let i = stepNames.length + 1;
    let name = `step_${i}`;
    while (steps[name]) name = `step_${++i}`;
    commit({
      ...draft,
      state_field: draft.state_field || 'handoff_to',
      default_step: draft.default_step || name,
      steps: { ...steps, [name]: { label: '', description: '', system_prompt: '', tools: [], transfers: [] } },
    });
  };

  const renameStep = (from: string, raw: string) => {
    const to = raw.trim();
    if (!to || to === from) return;
    // The key becomes the tool suffix (`transfer_to_<key>`), and tool names are
    // restricted to [A-Za-z0-9_-] by the model APIs — a Chinese key would make
    // the generated tool unloadable. The Chinese name belongs in `label`.
    if (!/^[A-Za-z0-9_-]{1,40}$/.test(to)) return;
    if (steps[to]) return;
    const next: Record<string, HandoffStep> = {};
    for (const key of stepNames) {
      const step = steps[key];
      const renamed = key === from ? to : key;
      next[renamed] = {
        ...step,
        transfers: (step.transfers ?? []).map(e => (e.to === from ? { ...e, to } : e)),
      };
    }
    commit({
      ...draft,
      steps: next,
      default_step: draft.default_step === from ? to : draft.default_step,
    });
  };

  const removeStep = (name: string) => {
    const next: Record<string, HandoffStep> = {};
    for (const key of stepNames) {
      if (key === name) continue;
      const step = steps[key];
      next[key] = { ...step, transfers: (step.transfers ?? []).filter(e => e.to !== name) };
    }
    commit({
      ...draft, steps: next,
      default_step: draft.default_step === name ? Object.keys(next)[0] : draft.default_step,
    });
  };

  const addEdge = () => {
    const from = stepNames[0];
    if (!from) return;
    const to = stepNames.find(n => n !== from) ?? '';
    const step = steps[from];
    commit({ ...draft, steps: { ...steps, [from]: { ...step, transfers: [...(step.transfers ?? []), { to, description: '' }] } } });
  };

  const moveEdge = (from: string, index: number, to: string) => {
    const list = [...(steps[from].transfers ?? [])];
    list[index] = { ...list[index], to };
    commit({ ...draft, steps: { ...steps, [from]: { ...steps[from], transfers: list } } });
  };

  const patchEdge = (from: string, index: number, patch: Partial<TransferEdge>) => {
    const list = [...(steps[from].transfers ?? [])];
    list[index] = { ...list[index], ...patch };
    commit({ ...draft, steps: { ...steps, [from]: { ...steps[from], transfers: list } } });
  };

  const removeEdge = (from: string, index: number) => {
    commit({
      ...draft,
      steps: { ...steps, [from]: { ...steps[from], transfers: (steps[from].transfers ?? []).filter((_, i) => i !== index) } },
    });
  };

  const rebaseEdge = (from: string, index: number, target: string) => {
    if (target === from) return;
    const moved = steps[from].transfers?.[index];
    if (!moved) return;
    const fromStep = steps[from];
    const toStep = steps[target];
    commit({
      ...draft,
      steps: {
        ...steps,
        [from]: { ...fromStep, transfers: (fromStep.transfers ?? []).filter((_, i) => i !== index) },
        [target]: { ...toStep, transfers: [...(toStep.transfers ?? []), moved] },
      },
    });
  };

  const card = { border: `1px solid ${t.border}`, borderRadius: 6, padding: 8, marginTop: 8, background: t.bgSidebar } as const;

  return (
    <div style={card}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ color: t.textPrimary, fontSize: 12, fontWeight: 600 }}>转交（handoff）</div>
        <button type="button" onClick={addStep} style={smallBtn(t, true)}>+ 添加角色</button>
      </div>

      <div style={{ fontSize: 10, color: t.textMuted, marginTop: 4, lineHeight: '15px' }}>
        左边写显示名（中文即可），等宽那格是<b>键名</b> —— 工具名会叫
        <code> transfer_to_&lt;键名&gt;</code>，模型接口只接受英文/数字/下划线。
        <br />
        一条转交关系生成一个工具 <code>transfer_to_&lt;目标&gt;</code>（只有 reason 参数）。
        模型调用后 agent 换成目标角色的提示词与工具继续回答；一个角色可以转给多个目标。
      </div>

      {stepNames.length === 0 ? (
        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 8 }}>
          还没有角色。先「+ 添加角色」，再在下面加“谁 → 谁”。
        </div>
      ) : (
        <>
          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 10, marginBottom: 4 }}>角色</div>
          {stepNames.map(name => {
            const step = steps[name];
            const granted = new Set(step.tools ?? []);
            return (
              <div key={name} style={{ ...card, background: t.bgContent }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <input
                    value={step.label ?? ''}
                    onChange={e => patchStep(name, { label: e.target.value })}
                    placeholder={name}
                    style={{ ...box(t), flex: 1, fontWeight: 600 }}
                  />
                  <input
                    defaultValue={name}
                    key={`key-${name}`}
                    onBlur={e => {
                      if (e.target.value.trim() !== name) renameStep(name, e.target.value);
                    }}
                    onKeyDown={e => {
                      if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                    }}
                    title="键名（工具名会是 transfer_to_<键名>，只能用英文/数字/下划线）；中文名写到左边的显示名"
                    style={{ ...box(t), width: 110, fontFamily: 'monospace', fontSize: 10 }}
                  />
                  {draft.default_step === name && <span style={{ fontSize: 10, color: t.accent }}>起始</span>}
                  <button type="button" onClick={() => removeStep(name)} style={smallBtn(t)}>删除</button>
                </div>
                <input
                  value={step.description ?? ''}
                  onChange={e => patchStep(name, { description: e.target.value })}
                  placeholder="这一步负责什么（一句话）"
                  style={{ ...box(t), marginBottom: 6 }}
                />
                <textarea
                  value={step.system_prompt ?? ''}
                  onChange={e => patchStep(name, { system_prompt: e.target.value })}
                  placeholder="这一步的 system prompt"
                  rows={3}
                  style={{ ...box(t), fontFamily: 'inherit', resize: 'vertical' as const, marginBottom: 6 }}
                />
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {candidateTools.length === 0 && (
                    <span style={{ fontSize: 10, color: t.textMuted }}>（先在 Tools 页签勾选工具）</span>
                  )}
                  {candidateTools.map(tool => (
                    <label key={tool} style={{
                      display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10,
                      fontFamily: 'monospace', padding: '2px 6px', borderRadius: 4,
                      border: `1px solid ${granted.has(tool) ? t.accent : t.border}`,
                      color: granted.has(tool) ? t.accent : t.textMuted, cursor: 'pointer',
                    }}>
                      <input
                        type="checkbox"
                        checked={granted.has(tool)}
                        onChange={e => {
                          const nextTools = new Set(granted);
                          if (e.target.checked) nextTools.add(tool); else nextTools.delete(tool);
                          patchStep(name, { tools: [...nextTools] });
                        }}
                        style={{ accentColor: t.accent, cursor: 'pointer' }}
                      />
                      {tool}
                    </label>
                  ))}
                </div>
              </div>
            );
          })}

          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12 }}>
            <div style={{ color: t.textPrimary, fontSize: 12, fontWeight: 600 }}>谁 → 谁</div>
            <button type="button" onClick={addEdge} style={smallBtn(t, true)}>+ 添加转交关系</button>
          </div>

          {edges.length === 0 && (
            <div style={{ fontSize: 10, color: t.textMuted, marginTop: 4 }}>
              还没有转交关系：没有边就没有 transfer 工具，各角色只会自己回答。
            </div>
          )}

          {edges.map(({ from, index, edge }) => (
            <div key={`${from}-${index}`} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
              <select
                value={from}
                onChange={e => rebaseEdge(from, index, e.target.value)}
                style={{ ...box(t), width: 110 }}
              >
                {stepNames.map(n => <option key={n} value={n}>{steps[n].label || n}</option>)}
              </select>
              <span style={{ fontSize: 12, color: t.textMuted }}>→</span>
              <select
                value={edge.to}
                onChange={e => moveEdge(from, index, e.target.value)}
                style={{ ...box(t), width: 110 }}
              >
                <option value="">（选择目标）</option>
                {stepNames.filter(n => n !== from).map(n => (
                  <option key={n} value={n}>{steps[n].label || n}</option>
                ))}
              </select>
              <input
                value={edge.description ?? ''}
                onChange={e => patchEdge(from, index, { description: e.target.value })}
                placeholder="什么时候该转过去（模型按这句判断）"
                style={{ ...box(t), flex: 1 }}
              />
              <button type="button" onClick={() => removeEdge(from, index)} style={smallBtn(t)}>×</button>
            </div>
          ))}

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
            <span style={{ fontSize: 11, color: t.textMuted }}>新对话从</span>
            <select
              value={draft.default_step ?? stepNames[0]}
              onChange={e => commit({ ...draft, default_step: e.target.value })}
              style={{ ...box(t), width: 150 }}
            >
              {stepNames.map(n => <option key={n} value={n}>{steps[n].label || n}</option>)}
            </select>
            <span style={{ fontSize: 11, color: t.textMuted }}>开始</span>
          </div>
        </>
      )}
    </div>
  );
}

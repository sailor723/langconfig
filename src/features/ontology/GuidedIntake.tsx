/**
 * GuidedIntake — one business question at a time, then a summary the user verifies BEFORE anything runs.
 *
 * A survey form asks nine fields at once and gets nine half-answers. A person describing a number thinks
 * in a sequence: what do I call it → what does it answer → how is it worked out → what is one row →
 * what is in scope → what do I want to see it by. So this asks exactly that, one step at a time, with
 * an example per step and a "why we ask" line, and it never shows a second question before the previous
 * one is answered or skipped on purpose.
 *
 * The last step is not a question: it is the SUMMARY — the answers restated as sentences the user can
 * disagree with, each with a way back to the step that produced it. Only 「确认，开始」 moves on, and
 * that is what starts the agent (the metric chat asks for an interpretation first; a build job starts
 * with the confirmed brief).
 *
 * Nothing here is technical: steps carry business words, examples and choices. The translation to
 * declarations happens on the agent's side (references/user-intake.md).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Pencil } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';

export interface IntakeStep {
  /** answer key */
  id: string;
  /** the business question, as it would be asked out loud */
  question: string;
  /** one line of why it matters — the user should see the consequence, not the field name */
  why?: string;
  /** an example answer in the user's own words */
  example?: string;
  /** one-line input (default) or a multi-line one */
  multiline?: boolean;
  /** offered answers; the user may still type their own */
  choices?: string[];
  /** skipping is allowed and means "we will ask you" — never "pick a default" */
  optional?: boolean;
  /** shown in the summary when unanswered */
  unansweredNote?: string;
}

export interface GuidedIntakeProps {
  title: string;
  intro?: string;
  steps: IntakeStep[];
  /** a tutorial sample's answers: every step filled, starting on the summary */
  prefill?: Record<string, string> | null;
  /** rendered at the top of the overlay — a caller's own strip (the tutorial samples) lives here,
   *  because this component is absolutely positioned over the whole panel and would cover it */
  header?: React.ReactNode;
  /** label of the final action, e.g. 「确认，先给我解读」 */
  confirmLabel: string;
  /** sentence under the summary explaining what happens after the confirmation */
  afterNote?: string;
  onConfirm: (answers: Record<string, string>) => void;
  onCancel: () => void;
}

export default function GuidedIntake({
  title, intro, steps, confirmLabel, afterNote, prefill, header, onConfirm, onCancel,
}: GuidedIntakeProps) {
  const t = useLayoutTokens();
  const [answers, setAnswers] = useState<Record<string, string>>(prefill || {});
  const [at, setAt] = useState(0);           // 0..steps.length-1 are questions, steps.length is the summary

  // A sample fills the answers INTO the steps and walks from the first question, so the user SEES each
  // answer in the input and presses 下一步 through them. (It used to jump straight to the summary, which
  // hid the answers the sample had filled — the thing worth reading.) The object identity is the
  // trigger: the panel memoises it, so selecting the same sample twice does not reset a step the user
  // is reading.
  const prefillRef = useRef<Record<string, string> | null>(null);
  useEffect(() => {
    if (!prefill || prefill === prefillRef.current) return;
    prefillRef.current = prefill;
    setAnswers({ ...prefill });
    setAt(0);
  }, [prefill]);
  const onSummary = at >= steps.length;
  const step = steps[Math.min(at, steps.length - 1)];
  const value = answers[step?.id ?? ''] ?? '';
  const answered = useMemo(
    () => steps.filter(s => (answers[s.id] || '').trim()).length, [answers, steps]);
  const canAdvance = !step ? true : step.optional || !!value.trim();
  const requiredLeft = steps.filter(s => !s.optional && !(answers[s.id] || '').trim()).length;

  const set = (id: string, v: string) => setAnswers(prev => ({ ...prev, [id]: v }));

  const fieldStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 8,
    fontSize: 13, lineHeight: 1.6, fontFamily: 'inherit', outline: 'none',
    border: `1px solid ${t.border}`, background: t.bgInput || 'transparent', color: t.textPrimary,
  };
  const chip = (active: boolean): React.CSSProperties => ({
    fontSize: 11.5, padding: '4px 9px', borderRadius: 999, cursor: 'pointer',
    border: `1px solid ${active ? t.accent : t.border}`,
    background: active ? `${t.accent}14` : 'transparent',
    color: active ? t.accent : t.textPrimary,
  });

  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 20, background: t.bgSidebar,
      display: 'flex', flexDirection: 'column', minHeight: 0,
    }}>
      {/* header: title + progress dots */}
      <div style={{ padding: '9px 12px 7px', borderBottom: `1px solid ${t.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>{title}</span>
          <button
            onClick={onCancel}
            style={{ marginLeft: 'auto', background: 'none', border: 'none', color: t.textDim, cursor: 'pointer', fontSize: 11.5 }}
          >
            取消
          </button>
        </div>
        <div style={{ display: 'flex', gap: 4, marginTop: 7, alignItems: 'center' }}>
          {steps.map((s, i) => {
            const done = !!(answers[s.id] || '').trim();
            const here = i === at;
            return (
              <button
                key={s.id}
                onClick={() => setAt(i)}
                title={s.question}
                style={{
                  width: here ? 22 : 8, height: 8, borderRadius: 999, border: 'none', padding: 0,
                  cursor: 'pointer',
                  background: here ? t.accent : done ? `${t.accent}88` : t.border,
                  transition: 'width .12s',
                }}
              />
            );
          })}
          <button
            onClick={() => setAt(steps.length)}
            title="看摘要并确认"
            style={{
              marginLeft: 2, fontSize: 10.5, padding: '1px 7px', borderRadius: 999, cursor: 'pointer',
              border: `1px solid ${onSummary ? t.accent : t.border}`,
              background: onSummary ? `${t.accent}14` : 'transparent',
              color: onSummary ? t.accent : t.textDim,
            }}
          >
            摘要
          </button>
          <span style={{ marginLeft: 'auto', fontSize: 10.5, color: t.textDim }}>
            {onSummary ? `${answered}/${steps.length} 已回答` : `${at + 1}/${steps.length}`}
          </span>
        </div>
      </div>

      {header && (
        <div style={{ borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>{header}</div>
      )}

      {/* body: one question, or the summary */}
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 12px' }}>
        {!onSummary && step && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {at === 0 && intro && (
              <div style={{ fontSize: 11.5, lineHeight: 1.6, color: t.textDim }}>{intro}</div>
            )}
            {prefill && at === 0 && (
              <div style={{
                fontSize: 10.5, lineHeight: 1.6, padding: '5px 8px', borderRadius: 6,
                border: `1px solid ${t.accent}55`, background: `${t.accent}10`, color: t.textPrimary,
              }}>
                样例已填入：下面每一问都有答案，点「下一步」逐个核对即可（想直接看结论就点右上角「摘要」）。
                任何一项都能改。
              </div>
            )}
            <div style={{ fontSize: 13.5, fontWeight: 600, lineHeight: 1.5 }}>{step.question}</div>
            {step.why && <div style={{ fontSize: 11, lineHeight: 1.55, color: t.textDim }}>{step.why}</div>}
            {step.choices?.length ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, margin: '2px 0 4px' }}>
                {step.choices.map(c => (
                  <button key={c} onClick={() => set(step.id, c)} style={chip(value === c)}>{c}</button>
                ))}
              </div>
            ) : null}
            {step.multiline ? (
              <textarea
                value={value}
                onChange={e => set(step.id, e.target.value)}
                rows={5}
                placeholder={step.example || ''}
                style={{ ...fieldStyle, resize: 'vertical' }}
                autoFocus
              />
            ) : (
              <input
                value={value}
                onChange={e => set(step.id, e.target.value)}
                placeholder={step.example || ''}
                style={fieldStyle}
                autoFocus
              />
            )}
            <div style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.6 }}>
              {step.optional
                ? '可以留空 —— 留空的意思是「由 agent 回来问你」，不是「随便挑一个默认值」。'
                : '这一项会改变这个数的含义，所以它是必答的；不确定就把你的理解写下来，agent 会先给解读让你确认。'}
            </div>
          </div>
        )}

        {onSummary && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>请核对：我理解你要的是这样</div>
            <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.6 }}>
              下面是你要的业务的复述。有错就点右侧的笔回去改——确认之后 agent 才会开始。
            </div>
            {steps.map((s, i) => {
              const a = (answers[s.id] || '').trim();
              return (
                <div key={s.id} style={{ borderBottom: `1px solid ${t.border}66`, paddingBottom: 5 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                    <span style={{ fontSize: 10.5, color: t.textDim }}>{s.question.replace(/？$/, '')}</span>
                    <button
                      onClick={() => setAt(i)}
                      title="修改这一项"
                      style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}
                    >
                      <Pencil size={10} />
                    </button>
                  </div>
                  <div style={{ fontSize: 12.5, lineHeight: 1.6, color: a ? t.textPrimary : t.textDim }}>
                    {a || (s.unansweredNote || (s.optional ? '（没答，agent 会先问你）' : '（未答）'))}
                  </div>
                </div>
              );
            })}
            {afterNote && (
              <div style={{ fontSize: 11, lineHeight: 1.6, color: t.textDim, marginTop: 2 }}>{afterNote}</div>
            )}
            {requiredLeft > 0 && (
              <div style={{ fontSize: 11.5, color: '#b3261e' }}>
                还有 {requiredLeft} 项必答没填（点上面的笔回去补）。
              </div>
            )}
          </div>
        )}
      </div>

      {/* footer: step navigation / confirm */}
      <div style={{ padding: '8px 12px', borderTop: `1px solid ${t.border}`, display: 'flex', alignItems: 'center', gap: 6 }}>
        {!onSummary ? (
          <>
            <button
              onClick={() => setAt(Math.max(0, at - 1))}
              disabled={at === 0}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11.5, padding: '5px 9px',
                borderRadius: 7, border: `1px solid ${t.border}`, background: 'transparent',
                color: t.textPrimary, cursor: at === 0 ? 'default' : 'pointer', opacity: at === 0 ? 0.4 : 1,
              }}
            >
              <ChevronLeft size={11} /> 上一步
            </button>
            <button
              onClick={() => setAt(at + 1)}
              disabled={!canAdvance}
              style={{
                marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 12,
                fontWeight: 600, padding: '5px 11px', borderRadius: 7, border: 'none',
                background: t.accent, color: '#fff', cursor: canAdvance ? 'pointer' : 'default',
                opacity: canAdvance ? 1 : 0.45,
              }}
            >
              {at + 1 === steps.length ? '看摘要' : '下一步'} <ChevronRight size={11} />
            </button>
            {!canAdvance && (
              <span style={{ fontSize: 10.5, color: t.textDim }}>这一项必答</span>
            )}
          </>
        ) : (
          <>
            <button
              onClick={() => setAt(steps.length - 1)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 11.5, padding: '5px 9px',
                borderRadius: 7, border: `1px solid ${t.border}`, background: 'transparent',
                color: t.textPrimary, cursor: 'pointer',
              }}
            >
              <ChevronLeft size={11} /> 回去看看
            </button>
            <button
              onClick={() => onConfirm(answers)}
              disabled={requiredLeft > 0}
              style={{
                marginLeft: 'auto', fontSize: 12.5, fontWeight: 600, padding: '6px 13px',
                borderRadius: 8, border: 'none', background: t.accent, color: '#fff',
                cursor: requiredLeft > 0 ? 'default' : 'pointer', opacity: requiredLeft > 0 ? 0.45 : 1,
              }}
            >
              {confirmLabel}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

/** The metric the intake produces, as sentences the user reads before the agent runs. */
export const METRIC_STEPS: IntakeStep[] = [
  {
    id: 'name',
    question: '这个数你们平时叫什么？',
    why: '这是用户会打出来的那句话，会成为它的 label；问「多少钱」和问「运费收入」是两个数。',
    example: '每千公里破损箱数',
  },
  {
    id: 'question',
    question: '它会回答哪句话？',
    why: '一句话，像你自己会问的那样。它决定了这个数存在的理由。',
    example: '每跑一千公里会破多少箱？',
  },
  {
    id: 'arithmetic',
    question: '它是怎么算出来的？用你的话说。',
    why: '不用写 SQL。「一共多少 ÷ 一共多少，再乘 1000」这种说法就够；说不清算不出来就是还没定义好。',
    example: '一共破了多少箱 ÷ 一共跑了多少公里，再乘 1000',
    multiline: true,
  },
  {
    id: 'grain',
    question: '这个数里「一行」代表什么业务对象？',
    why: '颗粒度会改变数字本身：按每一趟车算和按每一家门店算，同一个问题会有两个答案。',
    example: '一次配送的一个站点（货损是记在站点上的）',
    choices: ['一趟车 / 一次配送', '一次配送里的一个站点', '一家门店', '一条线路', '一个司机', '一条投诉'],
  },
  {
    id: 'scope',
    question: '算哪些、不算哪些？',
    why: '范围也是一部分定义。想不到就说「全部」，但别让它替你缩小。',
    example: '全部',
    choices: ['全部', '只算已完成的配送', '排除测试门店', '只看某些区域'],
  },
  {
    id: 'dimensions',
    question: '要分维度看吗？',
    optional: true,
    why: '先要一个总数就留空。要分组的话，用业务上的说法——按线路版本、按车辆、按门店区域。',
    example: '按线路版本、按车辆（想看并线前后 / 哪台车）',
  },
  {
    id: 'unit',
    question: '单位是什么？',
    optional: true,
    why: '箱、元、次、%，或者「每千…」这种量级。',
    example: '箱',
    choices: ['箱', '元', '次', '件', '%', '每千'],
  },
  {
    id: 'expected',
    question: '你心里大概是多少？（用来校验，不是目标）',
    optional: true,
    why: '给个数量级就行。agent 算出来差太多，说明它理解的口径和你不一样——这是最便宜的检查。',
    example: '三十几箱',
  },
  {
    id: 'purpose',
    question: '谁会用它，拿它做什么决定？',
    optional: true,
    why: '这一句会写进定义里，让以后看到这个数的人知道它为什么存在。',
    example: '调度判断是不是某条线路或某台车在货损上要复查',
  },
];

/** The build the intake produces: what generation needs, in business words. */
export const BUILD_STEPS: IntakeStep[] = [
  {
    id: 'data',
    question: '这份本体要为哪份数据服务？',
    why: '每份数据配一个构建助手；这里只显示可选的数据名称，不需要你选 agent 或路径。',
    example: '',
  },
  {
    id: 'oneRow',
    question: '这份数据里「一行」是什么？（最大那张表的一次记录）',
    why: '一切数字的颗粒度都由它决定。答错了，后面每个数都会跟着错。',
    example: '一次配送',
  },
  {
    id: 'questions',
    question: '用户会怎么问这些数据？几句原话，一行一句。',
    why: '问题决定需要哪些指标——不是「能算什么」，而是「有人真的会问什么」。',
    example: '这个月运费多少？\n哪条线路超载最多？\n哪些站点准时率低？\n并线之后破损有变化吗？',
    multiline: true,
  },
  {
    id: 'decisions',
    question: '这些数字支撑什么决定？',
    why: '决定筛选真正的指标；没有决定的数字是装饰。',
    example: '该不该加一趟车 / 哪条线路要复查 / 哪个司机要培训',
    multiline: true,
  },
  {
    id: 'timeRange',
    question: '「最近 30 天」在这份数据里有意义吗？',
    why: '数据是近期的，可以按「最近 N 天」看；是历史归档的，问「最近 30 天」会得到空的——这时应该拒绝而不是悄悄缩小。',
    example: '数据是最近三个月 / 历史上到去年 / 按财年',
    choices: ['数据是最近几个月（可以按最近 N 天）', '历史数据（按财年/季度，不要用「最近 N 天」）'],
  },
  {
    id: 'writes',
    question: '有谁会改这份数据吗？（写入）',
    optional: true,
    why: '有写入就要有审计；没有就说「只读」，这也是一个需要被记录的决定。',
    example: '只读 / 调度会改派单',
    choices: ['只读', '有写入（调度/客服会改）'],
  },
  {
    id: 'excluded',
    question: '有什么先不算在内？',
    optional: true,
    why: '排除项也是定义的一部分：测试门店、停用线路、未生效的合同。',
    example: '测试门店、已停用线路',
  },
];

/**
 * MetricEditorPanel — the metric editor as a PANEL, with the chat inside it.
 *
 * The intuition that produced this file: *a conversation alone is the wrong shape for standardized
 * input*. Some things a person wants to say are free-form ("为什么这个数这么高"), and some are
 * structured and must not be re-typed every time ("这个数的『一行』是一次配送的一个站点"). So the rail
 * holds a panel with four sections over one ontology:
 *
 *   新增指标   guided, one business question at a time → a summary to verify → the agent interprets
 *               first, and only after that confirmation does it change anything
 *   当前指标   the metric you clicked in the grid, restated in business fields (叫什么 / 怎么算 /
 *              一行 / 范围 / 维度 / 单位) each editable in place, plus the declaration, the compiled SQL,
 *              the number and the guard's notes
 *   对话       the same streaming chat as before — where the agent asks back and reports
 *   提案       staged publishes with diff / which numbers move / apply
 *
 * The two halves share one conversation: composing from a field sends into it, so the transcript shows
 * exactly what was asked. Nothing in the panel talks to a database, and nothing here writes SQL.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight, CheckCheck, Loader2, MessageSquare, Pencil, Plus, Sigma, X,
} from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useLayoutTokens } from '../../components/layout2/tokens';
import type { MetricCard } from './ontologyStore';
import { mono, Quiet, SUCCESS, WARN } from './ui';
import GuidedIntake, { METRIC_STEPS } from './GuidedIntake';
import MetricEditorChat from './MetricEditorChat';

type Tab = 'new' | 'metric' | 'chat' | 'proposals';

interface Proposal {
  id: string;
  actor: string | null;
  note: string | null;
  created_at: string | null;
  files: string[];
  new_refusals: string[];
  carried_refusals: string[];
  gates_ok: boolean | null;
  gates_fails: string[];
  gates_not_run: string[];
  compile: { metrics?: number; compiled?: number };
}

interface Props {
  ontologyKey: string;
  cards: MetricCard[] | null;
  metricName: string | null;
  onSelectMetric: (name: string) => void;
  onApplied?: () => void;
  onClose?: () => void;
}

/** The business fields of one metric, and how to restate them for the user. */
const BUSINESS_FIELDS: Array<{
  id: string;
  label: string;
  get: (c: MetricCard) => string;
  hint: string;
}> = [
  { id: 'label', label: '叫什么', get: c => c.label || '', hint: '用户打出来的那句话' },
  {
    id: 'arithmetic', label: '怎么算',
    get: c => (c.numerator && c.denominator
      ? `${c.numerator} ÷ ${c.denominator}${c.scale ? ` × ${c.scale}` : ''}`
      : `${c.aggregate || '—'}${c.formula ? ` of ${c.formula}` : ''}`),
    hint: '聚合 + 算的是哪个字段，或分子÷分母',
  },
  { id: 'grain', label: '一行代表', get: c => (c.grain ? `:${c.grain}` : '—'), hint: '颗粒度：这个数按什么数' },
  { id: 'where', label: '算哪些', get: c => (c.where ? `:${c.where}` : '全部'), hint: '范围（定义类）' },
  {
    id: 'groupBy', label: '分维度',
    get: c => ((c.groupBy || []).length ? (c.groupBy || []).map(g => `:${g}`).join(' · ') : '不分维度'),
    hint: '按什么分组看',
  },
  { id: 'unit', label: '单位', get: c => c.unit || '—', hint: '箱 / 元 / 次 / %' },
];

export default function MetricEditorPanel({
  ontologyKey, cards, metricName, onSelectMetric, onApplied, onClose,
}: Props) {
  const t = useLayoutTokens();
  const [tab, setTab] = useState<Tab>('new');
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [chatReady, setChatReady] = useState<{ send: (s: string) => void; busy: () => boolean } | null>(null);
  // The two-phase rule: the intake asks the agent for an INTERPRETATION first, and only a
  // confirmation sends the implementation. `pending` holds the answers we are about to confirm.
  const [pending, setPending] = useState<Record<string, string> | null>(null);
  const [editing, setEditing] = useState<{ field: string; value: string } | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);

  const card = (cards || []).find(c => c.name === metricName) || null;

  const loadProposals = useCallback(async () => {
    if (!ontologyKey) return;
    try {
      const res: any = await apiClient.get(
        `/api/ontology/${encodeURIComponent(ontologyKey)}/proposals`);
      setProposals((res?.data?.proposals || []) as Proposal[]);
    } catch {
      setProposals([]);
    }
  }, [ontologyKey]);
  useEffect(() => { void loadProposals(); }, [loadProposals]);
  // Clicking a card is a request to LOOK at it — jump to that section instead of making the user
  // find the tab themselves.
  useEffect(() => { if (metricName) setTab('metric'); }, [metricName]);

  /** Composed by the panel from business answers; the chat appends its fixed handoff. */
  const composeNewMetric = (a: Record<string, string>) => {
    const line = (l: string, v?: string) => (v && v.trim() ? `- ${l}：${v.trim()}\n` : '');
    return [
      '【新增指标】（业务口径；先只给我你的解读，不要改任何文件）\n\n',
      line('用户会这么叫它', a.name),
      line('它会回答', a.question),
      line('怎么算（业务语言）', a.arithmetic),
      line('一行代表', a.grain),
      line('算哪些 / 不算哪些', a.scope),
      line('要看的维度', a.dimensions),
      line('单位 / 量级', a.unit),
      line('大概多少（用来校验，不是目标）', a.expected),
      line('谁用它做什么决定', a.purpose),
      '\n第一步只要解读，不要动手：告诉我你打算声明成什么——用业务话讲清楚分子/分母（或聚合+字段）、',
      '颗粒度、范围、维度，对应到本体的哪些对象，以及你预计的值和你会用哪条独立路线去核它。',
      '我确认之后你再改文件、验证、暂存。',
    ].join('');
  };

  const confirmImplementation = () => {
    setPending(null);
    chatReady?.send('解读确认，可以实施。按你上一条说的做：只改必要的一处声明，验证（编译、值与第二条独立路线、其余指标数字不变），然后 ontology_publish 暂存并报告。');
  };

  const composeFieldEdit = (field: string, from: string, to: string) => {
    return [
      `【改指标】${metricName} 的「${field}」`,
      `- 现在：${from}`,
      `- 改成：${to}`,
      '',
      '只改这一处；如果这一改会改变这个数的含义（颗粒度、范围、分子分母），先在回复里说明影响再动手。',
      '做完验证：其余指标的数字一个都不许变，然后 ontology_publish 暂存。',
    ].join('\n');
  };

  const send = (text: string) => {
    if (!chatReady) return;
    chatReady.send(text);
    setTab('chat');
  };

  const tabs: Array<{ id: Tab; label: string; icon: any; badge?: number }> = [
    { id: 'new', label: '新增', icon: Plus },
    { id: 'metric', label: '当前指标', icon: Sigma },
    { id: 'chat', label: '对话', icon: MessageSquare },
    { id: 'proposals', label: '提案', icon: CheckCheck, badge: proposals.length || undefined },
  ];

  return (
    <div style={{
      width: 420, flex: 'none', display: 'flex', flexDirection: 'column', minHeight: 0,
      borderLeft: `1px solid ${t.border}`, background: t.bgSidebar, position: 'relative',
    }}>
      {/* header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderBottom: `1px solid ${t.border}` }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>指标编辑</span>
        <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>
          {card ? card.name : ontologyKey}
        </span>
        {onClose && (
          <button
            onClick={onClose}
            title="收起"
            style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}
          >
            <X size={13} />
          </button>
        )}
      </div>

      {/* section tabs */}
      <div style={{ display: 'flex', gap: 2, padding: '6px 8px', borderBottom: `1px solid ${t.border}` }}>
        {tabs.map(({ id, label, icon: Icon, badge }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              onClick={() => setTab(id)}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5,
                padding: '4px 9px', borderRadius: 7, cursor: 'pointer',
                border: `1px solid ${active ? t.accent : 'transparent'}`,
                background: active ? `${t.accent}14` : 'transparent',
                color: active ? t.accent : t.textMuted, fontWeight: active ? 600 : 400,
              }}
            >
              <Icon size={11} /> {label}
              {badge ? <span style={{ fontSize: 10, color: active ? t.accent : t.textDim }}>{badge}</span> : null}
            </button>
          );
        })}
      </div>

      {/* 新增指标: guided, then a summary, then interpretation */}
      {tab === 'new' && (
        <GuidedIntake
          title="新增指标（一步一步来）"
          intro="我一次只问一件事。全部答完会给你一段摘要请你核对——确认之后 agent 先给你的解读，再动手。"
          steps={METRIC_STEPS}
          confirmLabel="确认，先给我解读"
          afterNote="确认后 agent 只做解读（不改文件）：它打算怎么算、落到哪些对象、预计多少、用哪条独立路线核。你确认解读之后，它才会改声明并暂存。"
          onConfirm={answers => {
            setPending(answers);
            send(composeNewMetric(answers));
          }}
          onCancel={() => setTab('chat')}
        />
      )}

      {/* 当前指标: the standardized view of one metric, editable in place */}
      {tab === 'metric' && (
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px 20px' }}>
          {!card && (
            <Quiet>
              在左边的指标卡片里点一个，这里会把它翻译成人话：叫什么、怎么算、一行代表什么、算哪些、
              分什么维度、单位，以及它的声明、编译出的 SQL 和刚才查到的数。改任何一项都发一条结构化的
              修改请求给 agent（它会先说明影响，再动手）。
            </Quiet>
          )}
          {card && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ ...mono, fontSize: 12.5, color: t.accent }}>{card.name}</span>
                <span style={{ marginLeft: 'auto', ...mono, fontSize: 12.5 }}>
                  {card.value === null || card.value === undefined ? '—' : String(card.value)}
                </span>
              </div>
              {BUSINESS_FIELDS.map(f => {
                const from = f.get(card);
                const isEditing = editing?.field === f.id;
                return (
                  <div key={f.id} style={{ borderBottom: `1px solid ${t.border}66`, paddingBottom: 5 }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                      <span style={{ fontSize: 10.5, color: t.textDim }}>{f.label}</span>
                      <button
                        onClick={() => setEditing(isEditing ? null : { field: f.id, value: from })}
                        title={`${f.hint}｜改这一项`}
                        style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}
                      >
                        <Pencil size={10} />
                      </button>
                    </div>
                    {!isEditing && (
                      <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>{from || '—'}</div>
                    )}
                    {isEditing && (
                      <div style={{ display: 'flex', gap: 5, marginTop: 3 }}>
                        <input
                          value={editing.value}
                          onChange={e => setEditing({ field: f.id, value: e.target.value })}
                          onKeyDown={e => {
                            if (e.key === 'Enter' && editing.value.trim()) {
                              send(composeFieldEdit(f.label, from, editing.value.trim()));
                              setEditing(null);
                            }
                          }}
                          placeholder={f.hint}
                          autoFocus
                          style={{
                            flex: 1, minWidth: 0, padding: '4px 7px', borderRadius: 6, fontSize: 12,
                            border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
                            color: t.textPrimary, outline: 'none', fontFamily: 'inherit',
                          }}
                        />
                        <button
                          onClick={() => {
                            if (editing.value.trim()) {
                              send(composeFieldEdit(f.label, from, editing.value.trim()));
                              setEditing(null);
                            }
                          }}
                          style={{
                            fontSize: 11.5, padding: '4px 9px', borderRadius: 6, border: 'none',
                            background: t.accent, color: '#fff', cursor: 'pointer',
                          }}
                        >
                          发送改动
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
              {card.sql && (
                <div>
                  <div style={{ fontSize: 10.5, color: t.textDim, marginBottom: 2 }}>编译出的 SQL（由声明生成，不是我写的）</div>
                  <pre style={{
                    margin: 0, padding: '6px 7px', borderRadius: 6, fontSize: 9.5,
                    fontFamily: 'ui-monospace, Menlo, monospace', lineHeight: 1.55,
                    background: t.bgInput || 'rgba(127,127,127,0.08)', color: t.textPrimary,
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 180, overflow: 'auto',
                  }}>{card.sql}</pre>
                </div>
              )}
              {(card.guard_notes || []).length > 0 && (
                <div style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.6 }}>
                  护栏：{(card.guard_notes || []).join(' · ')}
                </div>
              )}
              {card.error && (
                <div style={{ fontSize: 11.5, color: WARN, lineHeight: 1.6 }}>
                  这个指标按名拒绝：{card.error}
                  <div style={{ color: t.textDim, marginTop: 3 }}>
                    拒绝不是失败，是还缺一条声明。点上方任一项去改，或在对话里问它缺什么。
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 对话: the streaming conversation, always the thing that talks to the agent */}
      <div
        ref={chatRef}
        style={{ flex: 1, minHeight: 0, display: tab === 'chat' ? 'flex' : 'none', flexDirection: 'column' }}
      >
        <MetricEditorChat
          ontologyKey={ontologyKey}
          onApplied={onApplied}
          hideIntake
          hideProposals
          onReady={setChatReady}
        />
      </div>

      {/* 提案: staged publishes, with what they change and what they move */}
      {tab === 'proposals' && (
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px 20px' }}>
          {proposals.length === 0 && (
            <Quiet>
              没有待处理的提案。agent 每次改动的结果是「已暂存」，出现在这里；你点 apply 它才会装进本体，
              指标卡片随之刷出新数。
            </Quiet>
          )}
          {proposals.map(p => (
            <ProposalCard key={p.id} proposal={p} onApplied={() => { void loadProposals(); onApplied?.(); }} />
          ))}
        </div>
      )}

      {/* the phase-1 → phase-2 confirmation, when an interpretation is expected */}
      {pending && tab === 'chat' && (
        <div style={{
          padding: '8px 12px', borderTop: `1px solid ${t.border}`, display: 'flex', gap: 6, alignItems: 'center',
        }}>
          <button
            onClick={confirmImplementation}
            style={{
              fontSize: 11.5, fontWeight: 600, padding: '5px 11px', borderRadius: 7, border: 'none',
              background: t.accent, color: '#fff', cursor: 'pointer',
            }}
          >
            解读确认，开始实施
          </button>
          <span style={{ fontSize: 10.5, color: t.textDim, flex: 1 }}>
            先读它的解读：口径对不对。读错就点「回去看看」改答案。
          </span>
          <button
            onClick={() => { setPending(null); setTab('new'); }}
            style={{ fontSize: 10.5, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer' }}
          >
            回去改
          </button>
        </div>
      )}
    </div>
  );
}

/** One staged publish: what it touches, what it moves, and the apply that changes the number. */
function ProposalCard({ proposal, onApplied }: { proposal: Proposal; onApplied: () => void }) {
  const t = useLayoutTokens();
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [diff, setDiff] = useState<any>(undefined);
  const [values, setValues] = useState<any>(undefined);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const loadDiff = async () => {
    if (diff !== undefined) return;
    try {
      const res: any = await apiClient.get(`/api/ontology/publish/${proposal.id}/diff`);
      setDiff(res?.data || null);
    } catch { setDiff(null); }
  };
  const loadValues = async () => {
    if (values !== undefined) return;
    try {
      const res: any = await apiClient.get(`/api/ontology/publish/${proposal.id}/values`, { timeout: 300000 });
      setValues(res?.data || null);
    } catch (e: any) { setValues({ error: e?.response?.data?.detail || e?.message }); }
  };

  const apply = async () => {
    setBusy(true); setMsg(null);
    try {
      await apiClient.post(`/api/ontology/publish/${proposal.id}/apply`, { confirmed: true });
      setMsg({ ok: true, text: `已上线 ${proposal.id}，指标卡片会显示新数字` });
      setArmed(false);
      onApplied();
    } catch (e: any) {
      const status = e?.response?.status;
      setMsg({
        ok: false,
        text: status === 403
          ? `你的帐号没有 ontology_editor 角色，不能 apply：${e?.response?.data?.detail}`
          : `apply 失败：${e?.response?.data?.detail || e?.message}`,
      });
    } finally { setBusy(false); }
  };

  const changed = (diff?.changed || []) as string[];
  return (
    <div style={{ border: `1px solid ${t.border}`, borderRadius: 9, padding: '8px 10px', marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>{proposal.id}</span>
        <span style={{ fontSize: 10.5, color: t.textDim }}>{proposal.actor || 'agent'}</span>
        <span style={{ marginLeft: 'auto', fontSize: 10.5, color: proposal.gates_ok ? SUCCESS : WARN }}>
          检查 {proposal.gates_ok ? '全通过' : '有失败'}
        </span>
      </div>
      {proposal.note && (
        <div style={{ fontSize: 11.5, lineHeight: 1.55, marginTop: 2 }}>{proposal.note}</div>
      )}
      <div style={{ fontSize: 10.5, color: t.textDim, marginTop: 2 }}>
        动了 {proposal.files?.length || 0} 个文件 · {proposal.compile?.compiled ?? '?'}/{proposal.compile?.metrics ?? '?'} 个指标
        {proposal.new_refusals?.length ? ` · 新拒绝：${proposal.new_refusals.join(', ')}` : ''}
      </div>
      {proposal.gates_not_run?.length ? (
        <div style={{ fontSize: 10, color: t.textDim }}>未跑：{proposal.gates_not_run.join(' · ')}</div>
      ) : null}
      <div style={{ display: 'flex', gap: 8, marginTop: 5, fontSize: 10.5 }}>
        <button
          onClick={() => void loadDiff()}
          style={{ background: 'none', border: 'none', color: t.textMuted, cursor: 'pointer', padding: 0 }}
        >
          {changed.length ? `改了哪些：${changed.join('、')}` : '改了哪些？'}
        </button>
        <button
          onClick={() => void loadValues()}
          style={{ background: 'none', border: 'none', color: t.textMuted, cursor: 'pointer', padding: 0 }}
        >
          哪些数字会变？
        </button>
      </div>
      {values !== undefined && (
        <div style={{ fontSize: 10.5, ...mono, marginTop: 3, lineHeight: 1.6 }}>
          {values?.ok === false
            ? <span style={{ color: WARN }}>{values.error || '算不出对比'}</span>
            : (values?.changed || []).length === 0
              ? <span style={{ color: t.textDim }}>一个数字都不变（{values?.unchanged || 0} 个指标核对过）</span>
              : (values.changed || []).map((c: any) => (
                <div key={c.metric}>
                  <span style={{ color: WARN }}>{c.metric}</span> {String(c.before ?? '—')} → <b>{String(c.after ?? '—')}</b>
                  {/* a GROUP BY metric has rows, not one number: say how many */}
                  {c.after_rows !== undefined && c.after_rows !== null
                    ? <span style={{ color: t.textDim }}>（{c.before_rows ?? 0} → {c.after_rows} 行）</span>
                    : null}
                </div>
              ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
        {armed ? (
          <>
            <button
              onClick={() => void apply()}
              disabled={busy}
              style={{
                fontSize: 11.5, fontWeight: 600, padding: '4px 10px', borderRadius: 6, border: 'none',
                background: t.accent, color: '#fff', cursor: 'pointer',
              }}
            >
              {busy ? <Loader2 size={11} /> : '确认上线'}
            </button>
            <button
              onClick={() => setArmed(false)}
              style={{ fontSize: 10.5, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer' }}
            >
              取消
            </button>
          </>
        ) : (
          <button
            onClick={() => setArmed(true)}
            disabled={!!(proposal.new_refusals?.length || proposal.gates_fails?.length)}
            style={{
              fontSize: 11.5, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
              border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary,
            }}
          >
            <CheckCheck size={11} /> 上线…
          </button>
        )}
        <a
          href="/settings?section=ontology"
          style={{ fontSize: 10.5, color: t.textDim, marginLeft: 'auto', display: 'inline-flex', gap: 2, alignItems: 'center' }}
        >
          详细对比 <ArrowUpRight size={10} />
        </a>
      </div>
      {msg && <div style={{ fontSize: 11, marginTop: 4, color: msg.ok ? SUCCESS : '#b3261e' }}>{msg.text}</div>}
    </div>
  );
}

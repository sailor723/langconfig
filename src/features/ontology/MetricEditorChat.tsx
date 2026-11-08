/**
 * MetricEditorChat — the metric editor's chat, in the Ontology browser's Metrics tab.
 *
 * Same shape as the Knowledge / Analysis chats (streamed tokens, a tool trace, one continuing
 * session, a stop button), with one difference that matters: the agent behind it is the ontology
 * editor, so a conversation can END IN A CHANGE. Everything it proposes arrives as a staged
 * publish, and the panel shows that proposal with the files it would touch, the gates it ran and
 * the apply button — "set result" is that button, and the metric cards behind this panel refresh
 * with the new numbers the moment it lands.
 *
 * Two deliberate limits:
 *  - the panel never talks to the database and never types SQL. It streams a turn and renders the
 *    proposal the publish channel produced;
 *  - applying is a two-step confirmation (a publish changes what a number MEANS for everyone), and
 *    the backend refuses it without the ontology_editor role — the error is shown, not swallowed.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUpRight, CheckCheck, Loader2, Send, Square, Wrench, X,
} from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { streamChatEvents } from '../chat/utils/streamChatEvents';
import { useProject } from '../../contexts/ProjectContext';
import { mono, Quiet, SUCCESS, WARN } from './ui';
import RunningLight, { RunningBar } from './RunningLight';

interface ToolStep { name: string; done: boolean; detail?: string }
interface Turn {
  role: 'user' | 'assistant';
  content: string;
  tools?: ToolStep[];
}
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
  compile: { metrics?: number; compiled?: number; refused?: unknown[] };
}

/**
 * The intake form — what a USER can answer.
 *
 * A person asking for a metric knows the business: the phrase they use, the question it answers, how
 * it is worked out in words, what one row of the business is, what is in scope, what they want to
 * group by. They do not know tables, columns, joins, `:grain`, TTL or SPARQL, so the form never asks
 * for any of it — the agent derives the declarations. (backend/skills/builtin/edit-ontology-metrics/
 * references/user-intake.md is the contract on the other side of this form.)
 *
 * Blank stays blank: grain and scope change what the number MEANS, so an unanswered one is a
 * question the agent must ask in business words, not a default it may pick.
 */
interface IntakeState {
  name: string;
  question: string;
  arithmetic: string;
  grain: string;
  scope: string;
  dimensions: string;
  unit: string;
  expected: string;
  purpose: string;
  notes: string;
}

const EMPTY_INTAKE: IntakeState = {
  name: '', question: '', arithmetic: '', grain: '', scope: '全部', dimensions: '',
  unit: '', expected: '', purpose: '', notes: '',
};

const INTAKE_EXAMPLE: IntakeState = {
  name: '每千公里破损箱数',
  question: '每跑一千公里会破多少箱？',
  arithmetic: '一共破了多少箱 ÷ 一共跑了多少公里，再乘 1000',
  grain: '一次配送的一个站点（货损是记在站点上的）',
  scope: '全部',
  dimensions: '',
  unit: '箱',
  expected: '三十几箱',
  purpose: '判断是不是某条线路或某台车在货损上要复查',
  notes: '',
};

/** What the USER wrote — business only. This is what the textarea holds and what they can edit. */
function composeBusiness(i: IntakeState): string {
  const line = (label: string, value: string) =>
    value.trim() ? `- ${label}：${value.trim()}\n` : '';
  return [
    '【新增指标】\n\n',
    line('用户会这么叫它', i.name),
    line('它会回答', i.question),
    line('怎么算（业务语言）', i.arithmetic),
    line('一行代表', i.grain),
    line('算哪些 / 不算哪些', i.scope),
    line('要看的维度', i.dimensions),
    line('单位 / 量级', i.unit),
    line('大概多少（用来校验，不是目标）', i.expected),
    line('谁用它做什么决定', i.purpose),
    line('其他约定', i.notes),
  ].join('');
}

/** The fixed handoff appended at send time. Shown to the user in a collapsible note, never typed. */
function composeHandoff(key: string): string {
  return [
    '\n（以下是平台附给 agent 的固定说明，不是用户输入）',
    `ontology_key=${key}`,
    '把它翻译成声明：对象与属性从已声明的本体里取，:aggregate / :formula（或 :numerator+:denominator+:scale）/ ',
    ':grain / :universe / :where / :groupBy 由你决定，JOIN 由编译器从 :references 推导 —— 不要向我问表名、列名或 TTL。',
    '任何会改变这个数含义而上面没答的点（颗粒度、范围、阈值、维度），先问我，不要自己定。',
    '开始前先 ontology_open(ontology_key="' + key + '", overwrite=true) 取一份与已安装本体一致的副本——',
    '旧副本会把别人后来的改动悄悄回退（已经发生过一次：label 被旧副本发布会退）。',
    '做完按 edit-ontology-metrics 验证：编译；值与你自己写的第二条独立路线一致；其余指标的数字一个都不许变。',
    '然后 ontology_publish 暂存，include 只点名你改过的文件；报告里写：值多少、独立路线是什么、哪些门禁 NOT RUN。',
  ].join('\n');
}

const fieldStyle = (t: any): React.CSSProperties => ({
  width: '100%', boxSizing: 'border-box', padding: '5px 7px', borderRadius: 6, fontSize: 11.5,
  border: `1px solid ${t.border}`, background: t.bgInput || 'transparent', color: t.textPrimary,
  outline: 'none', fontFamily: 'inherit', lineHeight: 1.5,
});

const FIELD_HELP: Array<[keyof IntakeState, string, string]> = [
  ['name', '它叫什么', '你平时怎么问它'],
  ['question', '回答什么问题', '一句话，像你会问的那样'],
  ['arithmetic', '怎么算', '用你自己的话说：多少 ÷ 多少，再乘多少'],
  ['grain', '一行代表什么', '一次配送的一个站点 / 一趟车 / 一家门店 …'],
  ['scope', '算哪些、不算哪些', '全部；或什么排除在外'],
  ['dimensions', '要分维度看吗', '按线路版本、按车辆、按门店区域 …（可空）'],
  ['unit', '单位', '箱、元、次、%'],
  ['expected', '大概多少', '用来校验，不是目标'],
  ['purpose', '谁用它做什么决定', '可选'],
  ['notes', '其他约定', '可选'],
];

function IntakeForm({ ontologyKey, onClose, onCompose }: {
  ontologyKey: string;
  onClose: () => void;
  onCompose: (text: string) => void;
}) {
  const t = useLayoutTokens();
  const [v, setV] = useState<IntakeState>(EMPTY_INTAKE);
  const set = (k: keyof IntakeState) => (e: any) => setV(prev => ({ ...prev, [k]: e.target.value }));
  const ready = v.name.trim() && v.question.trim() && v.arithmetic.trim();

  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 20, background: t.bgSidebar,
      display: 'flex', flexDirection: 'column', minHeight: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', borderBottom: `1px solid ${t.border}` }}>
        <span style={{ fontSize: 12.5, fontWeight: 600 }}>新增指标（用业务语言填）</span>
        <button onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}>
          <X size={13} />
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.6 }}>
          不用写 SQL、不用管表名和列。说清楚<b>它叫什么、回答什么、怎么算、一行是什么</b>就够了；
          其余由 agent 从已声明的本体里翻译。「一行代表什么」和「算哪些」会改变数字含义，没想好就留空，
          它会用业务话回来问你。
        </div>
        {FIELD_HELP.map(([k, label, help]) => (
          <label key={k} style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 11, color: t.textDim }}>
            <span>{label}{['name', 'question', 'arithmetic'].includes(k) ? ' *' : ''}</span>
            <input value={v[k]} onChange={set(k)} placeholder={help} style={fieldStyle(t)} />
          </label>
        ))}
        <button
          onClick={() => setV(INTAKE_EXAMPLE)}
          style={{
            alignSelf: 'flex-start', fontSize: 11, padding: '4px 9px', borderRadius: 6,
            border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted, cursor: 'pointer',
          }}
        >
          填一个示例（每千公里破损箱数）
        </button>
      </div>
      <div style={{ padding: '8px 12px', borderTop: `1px solid ${t.border}`, display: 'flex', gap: 6 }}>
        <button
          onClick={() => onCompose(composeBusiness(v))}
          disabled={!ready}
          style={{
            fontSize: 12, fontWeight: 600, padding: '6px 12px', borderRadius: 7, border: 'none',
            background: t.accent, color: '#fff', cursor: ready ? 'pointer' : 'default',
            opacity: ready ? 1 : 0.45,
          }}
        >
          生成请求（可以先看再发）
        </button>
        <span style={{ fontSize: 10.5, color: t.textDim, alignSelf: 'center' }}>
          {'它叫什么 / 回答什么 / 怎么算 是必填'}
        </span>
      </div>
    </div>
  );
}

interface Props {
  /** The ontology this panel edits (settings profile key). */
  ontologyKey: string;
  /** Called after a publish is applied, so the metric cards can re-read their numbers. */
  onApplied?: () => void;
  onClose?: () => void;
  /** A parent (the panel) owns the intake form, so this component is the conversation only. */
  hideIntake?: boolean;
  /** The parent renders the proposals in its own section instead. */
  hideProposals?: boolean;
  /** Receives a sender so the panel can put a composed message into the conversation. */
  onReady?: (api: { send: (text: string) => void; busy: () => boolean }) => void;
  /** Busy changes, so a parent can disable (and explain) its own actions instead of dropping them. */
  onStatus?: (status: { busy: boolean; queued: number }) => void;
}

export default function MetricEditorChat({ ontologyKey, onApplied, onClose, hideIntake, hideProposals, onReady, onStatus }: Props) {
  const t = useLayoutTokens();
  const { activeProjectId } = useProject();
  const projectId = activeProjectId ?? 1;
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [armed, setArmed] = useState<string | null>(null);
  const [applying, setApplying] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  // The business-language intake form (see references/user-intake.md): it collects what a person
  // actually knows, and shows the composed request before anything is sent.
  const [intakeOpen, setIntakeOpen] = useState(false);
  // Sends that arrive while a turn is running used to be DROPPED (`if (busy) return`), which is
  // exactly what "I approved and nothing happened" looks like from the outside. They queue now.
  const queueRef = useRef<string[]>([]);
  const [queued, setQueued] = useState(0);
  const [lastSentAt, setLastSentAt] = useState<string>('');
  const [runningSince, setRunningSince] = useState<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sessionKey = `langconfig.ontology.editor.${ontologyKey}`;
  const sessionId = (() => {
    try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; }
  })();

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

  // Continue the same conversation across a reload; the history is the server's, not local state.
  useEffect(() => {
    void loadProposals();
    const sid = (() => { try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; } })();
    if (!sid) return;
    void (async () => {
      try {
        const res: any = await apiClient.get(`/api/chat/${sid}/history`);
        const msgs: any[] = res?.data?.messages || [];
        setTurns(msgs
          .filter(m => m.role === 'user' || m.role === 'assistant')
          .slice(-20)
          .map(m => ({
            role: m.role as 'user' | 'assistant',
            // the bound key is part of the stored message; show the sentence, not the preamble
            content: String(m.content || '').replace(/^\[ontology_key=[^\]]+\][^\n]*\n\n/, ''),
          })));
      } catch {
        /* a dead session is not an error: the next send opens a new one */
      }
    })();
  }, [loadProposals, sessionKey]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, proposals]);

  const stop = () => {
    const sid = (() => { try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; } })();
    abortRef.current?.abort();
    if (sid) void apiClient.post(`/api/chat/${sid}/stop`, {}).catch(() => undefined);
    setBusy(false);
  };

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    await sendText(text);
  };

  const sendText = async (text: string) => {
    if (!text.trim()) return;
    if (busy) {
      queueRef.current.push(text);
      setQueued(queueRef.current.length);
      return;
    }
    setError(null);
    setNotice(null);
    setLastSentAt(new Date().toLocaleTimeString());
    setRunningSince(Date.now());
    setBusy(true);
    setTurns(prev => [...prev, { role: 'user', content: text },
                             { role: 'assistant', content: '', tools: [] }]);

    const patchLast = (fn: (turn: Turn) => Turn) =>
      setTurns(prev => {
        const next = [...prev];
        const idx = next.length - 1;
        if (idx >= 0) next[idx] = fn(next[idx]);
        return next;
      });

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const body: Record<string, unknown> = {
        message: text + composeHandoff(ontologyKey),
        project_id: projectId,
      };
      const sid = (() => { try { return localStorage.getItem(sessionKey) || ''; } catch { return ''; } })();
      if (sid) body.session_id = sid;

      for await (const ev of streamChatEvents(
        `/api/ontology/${encodeURIComponent(ontologyKey)}/ask-editor/stream`, body, ctrl.signal)) {
        if (ev.type === 'session' && ev.session_id) {
          try { localStorage.setItem(sessionKey, String(ev.session_id)); } catch { /* private mode */ }
        } else if (ev.type === 'chunk') {
          patchLast(turn => ({ ...turn, content: turn.content + String(ev.content || '') }));
        } else if (ev.type === 'tool_start') {
          patchLast(turn => ({ ...turn, tools: [...(turn.tools || []),
            { name: String(ev.tool_name || 'tool'), done: false }] }));
        } else if (ev.type === 'tool_end') {
          patchLast(turn => {
            const tools = [...(turn.tools || [])];
            const i = tools.map(x => x.name).lastIndexOf(String(ev.tool_name || 'tool'));
            if (i >= 0) tools[i] = { ...tools[i], done: true };
            return { ...turn, tools };
          });
        } else if (ev.type === 'complete') {
          patchLast(turn => ({ ...turn, content: String(ev.content || turn.content) }));
        } else if (ev.type === 'stopped') {
          patchLast(turn => ({ ...turn, content: turn.content + '\n\n(stopped)' }));
        } else if (ev.type === 'error') {
          setError(String(ev.message || 'the turn failed'));
        }
      }
      await loadProposals();
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        patchLast(turn => ({ ...turn, content: turn.content + '\n\n(stopped)' }));
      } else {
        // A key that is being BUILT answers 404 with the builder's name — show that sentence, not
      // a bare 'load failed': it is the difference between a bug and an unfinished build.
      setError(String(err?.response?.data?.detail || err?.message || err));
      }
    } finally {
      abortRef.current = null;
      setBusy(false);
      setRunningSince(null);
      if (queueRef.current.length) {
        // one turn at a time: the next composed message starts after this one, never beside it
        const next = queueRef.current.shift();
        setQueued(queueRef.current.length);
        if (next) setTimeout(() => void sendText(next), 0);
      }
    }
  };

  // The panel composes a message (from the guided intake or a field edit) and hands it here, so the
  // conversation is still the one thing that talks to the agent.
  useEffect(() => {
    onReady?.({ send: (t: string) => void sendText(t), busy: () => busy });
  }, [onReady, busy]);
  useEffect(() => {
    onStatus?.({ busy, queued });
  }, [onStatus, busy, queued]);

  const apply = async (id: string) => {
    setApplying(id);
    setNotice(null);
    try {
      await apiClient.post(`/api/ontology/publish/${id}/apply`, { confirmed: true });
      setNotice({ ok: true, text: `applied ${id} — the cards behind this panel now show the new numbers` });
      setArmed(null);
      await loadProposals();
      onApplied?.();
    } catch (e: any) {
      const status = e?.response?.status;
      const detail = e?.response?.data?.detail || e?.message || 'apply failed';
      setNotice({
        ok: false,
        text: status === 403
          ? `你的帐号没有 ontology_editor 角色，不能 apply：${detail}`
          : `apply failed: ${detail}`,
      });
    } finally {
      setApplying(null);
    }
  };

  const discard = async (id: string) => {
    setNotice(null);
    try {
      await apiClient.post(`/api/ontology/publish/${id}/discard`, {});
      setNotice({ ok: true, text: `discarded ${id} — the installed ontology was never touched` });
      await loadProposals();
    } catch (e: any) {
      setNotice({ ok: false, text: `discard failed: ${e?.response?.data?.detail || e?.message}` });
    }
  };

  return (
    <div style={{
      width: 400, flex: 'none', display: 'flex', flexDirection: 'column', minHeight: 0,
      borderLeft: `1px solid ${t.border}`, background: t.bgSidebar, position: 'relative',
    }}>
      {intakeOpen && !hideIntake && (
        <IntakeForm
          ontologyKey={ontologyKey}
          onClose={() => setIntakeOpen(false)}
          onCompose={text => {
            // the user reads the composed request before it is sent — the form exists to collect
            // business words, not to hide a prompt
            setInput(text);
            setIntakeOpen(false);
          }}
        />
      )}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px',
        borderBottom: `1px solid ${t.border}`, flexShrink: 0,
      }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: t.textPrimary }}>Metric editor chat</span>
        <span style={{ ...mono, fontSize: 10.5, color: t.textDim }}>{ontologyKey}</span>
        {!hideIntake && (
          <button
            onClick={() => setIntakeOpen(true)}
            title="按业务口径描述一个新指标，agent 负责翻译成声明"
            style={{
              marginLeft: 'auto', fontSize: 11, padding: '3px 8px', borderRadius: 6,
              border: `1px solid ${t.border}`, background: 'transparent', color: t.textMuted, cursor: 'pointer',
            }}
          >
            + 新增指标
          </button>
        )}
        {onClose && (
          <button
            onClick={onClose}
            title="close the editor chat"
            style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}
          >
            <X size={13} />
          </button>
        )}
      </div>

      {/* conversation */}
      <div ref={scrollRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px' }}>
        {turns.length === 0 && (
          <Quiet>
            Ask for a change in your own words — “把 onTimeStops 的说明补清楚”、“加一条必须被拒的样本”.
            The agent opens a copy, edits one declaration, verifies the number and stages a
            proposal; applying it here is what changes the metric.
          </Quiet>
        )}
        {turns.map((turn, i) => (
          <div key={i} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 10.5, color: t.textDim, marginBottom: 2 }}>
              {turn.role === 'user' ? 'you' : 'editor'}
            </div>
            {turn.content && (
              <div style={{
                fontSize: 12, lineHeight: 1.65, whiteSpace: 'pre-wrap', color: t.textPrimary,
                padding: turn.role === 'user' ? '6px 8px' : '0',
                borderRadius: 7,
                background: turn.role === 'user' ? (t.bgInput || 'rgba(127,127,127,0.08)') : 'transparent',
              }}>
                {turn.content}
              </div>
            )}
            {(turn.tools || []).length > 0 && (
              <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
                {(turn.tools || []).map((tool, j) => (
                  <div key={j} style={{ ...mono, fontSize: 10, color: t.textDim }}>
                    <Wrench size={9} /> {tool.name} {tool.done ? '✓' : '…'}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <RunningBar running />
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: t.textDim }}>
              <RunningLight running label="agent 正在跑" startedAt={runningSince} />
              <span>取副本 → 改声明 → 验证 → 暂存{queued > 0 ? ` · 还有 ${queued} 条排队` : ''}</span>
            </div>
          </div>
        )}
        {error && <div style={{ fontSize: 11.5, color: '#b3261e', whiteSpace: 'pre-wrap' }}>{error}</div>}
      </div>

      {/* proposals: the "set result" half */}
      {!hideProposals && proposals.length > 0 && (
        <div style={{
          borderTop: `1px solid ${t.border}`, maxHeight: 260, overflowY: 'auto',
          padding: '8px 12px', flexShrink: 0,
        }}>
          <div style={{ fontSize: 10.5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim, marginBottom: 5 }}>
            staged proposals ({proposals.length})
          </div>
          {proposals.map(p => {
            const changed = (p.files || []).length;
            return (
              <div key={p.id} style={{ border: `1px solid ${t.border}`, borderRadius: 8, padding: '7px 8px', marginBottom: 6 }}>
                <div style={{ ...mono, fontSize: 10.5, color: t.textDim }}>{p.id} · {p.actor || 'agent'}</div>
                {p.note && <div style={{ fontSize: 11.5, color: t.textPrimary, lineHeight: 1.5 }}>{p.note}</div>}
                <div style={{ fontSize: 10.5, color: t.textDim, marginTop: 2 }}>
                  {changed} file(s) · {p.compile?.compiled ?? '?'}/{p.compile?.metrics ?? '?'} metrics ·{' '}
                  <span style={{ color: p.gates_ok ? SUCCESS : WARN }}>gates {p.gates_ok ? 'pass' : 'fail'}</span>
                  {p.new_refusals?.length ? ` · NEW refusals: ${p.new_refusals.join(', ')}` : ''}
                </div>
                {p.gates_not_run?.length ? (
                  <div style={{ fontSize: 10, color: t.textDim }}>NOT RUN: {p.gates_not_run.join(' · ')}</div>
                ) : null}
                <div style={{ display: 'flex', gap: 6, marginTop: 5, alignItems: 'center' }}>
                  {armed === p.id ? (
                    <>
                      <button
                        onClick={() => void apply(p.id)}
                        disabled={applying === p.id}
                        style={{
                          fontSize: 11.5, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                          border: 'none', background: t.accent, color: '#fff', fontWeight: 600,
                        }}
                      >
                        {applying === p.id ? 'applying…' : 'confirm apply'}
                      </button>
                      <button onClick={() => setArmed(null)} style={{ fontSize: 11, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer' }}>
                        cancel
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => setArmed(p.id)}
                      disabled={!!(p.new_refusals?.length || p.gates_fails?.length)}
                      style={{
                        fontSize: 11.5, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
                        border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary,
                      }}
                    >
                      <CheckCheck size={11} /> apply…
                    </button>
                  )}
                  <button onClick={() => void discard(p.id)} style={{ fontSize: 11, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer' }}>
                    discard
                  </button>
                  <a
                    href="/settings?section=apply"
                    style={{ fontSize: 10.5, color: t.textDim, marginLeft: 'auto', display: 'inline-flex', gap: 2, alignItems: 'center' }}
                  >
                    diff <ArrowUpRight size={10} />
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {notice && (
        <div style={{
          padding: '6px 12px', fontSize: 11.5, lineHeight: 1.5, flexShrink: 0,
          color: notice.ok ? SUCCESS : '#b3261e',
        }}>{notice.text}</div>
      )}

      {/* composer */}
      <div style={{ padding: '8px 12px 10px', borderTop: `1px solid ${t.border}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); }
            }}
            rows={2}
            placeholder="把 onTimeStops 的说明补清楚（Enter 发送，Shift+Enter 换行）"
            style={{
              flex: 1, minWidth: 0, resize: 'vertical', padding: '6px 8px', borderRadius: 7,
              fontSize: 12, lineHeight: 1.5, fontFamily: 'inherit',
              border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
              color: t.textPrimary, outline: 'none',
            }}
          />
          {busy ? (
            <button
              onClick={stop}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12,
                padding: '7px 10px', borderRadius: 7, cursor: 'pointer',
                border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary,
              }}
            >
              <Square size={11} /> stop
            </button>
          ) : (
            <button
              onClick={() => void send()}
              disabled={!input.trim()}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12,
                padding: '7px 12px', borderRadius: 7, cursor: input.trim() ? 'pointer' : 'default',
                border: 'none', background: t.accent, color: '#fff', opacity: input.trim() ? 1 : 0.45,
              }}
            >
              <Send size={11} /> send
            </button>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8, fontSize: 10, color: t.textDim, marginTop: 3, flexWrap: 'wrap' }}>
          <span>{busy ? '通道：agent 处理中' : '通道：就绪'}</span>
          <span>会话 {sessionId ? sessionId.slice(0, 8) : '（首条消息时新建）'}</span>
          {lastSentAt && <span>上次发送 {lastSentAt}</span>}
          {queued > 0 && <span style={{ color: WARN }}>排队 {queued}</span>}
        </div>
        <div style={{ fontSize: 10, color: t.textDim, marginTop: 4, lineHeight: 1.6 }}>
          你只需要说业务口径；发送时会附一段固定的技术说明（ontology_key、如何翻译成声明、怎么验证）。
          <details style={{ display: 'inline-block', marginLeft: 4 }}>
            <summary style={{ cursor: 'pointer' }}>看看那段</summary>
            <pre style={{ fontSize: 9.5, whiteSpace: 'pre-wrap', margin: '4px 0 0', color: t.textDim }}>
              {composeHandoff(ontologyKey)}
            </pre>
          </details>
        </div>
      </div>
    </div>
  );
}

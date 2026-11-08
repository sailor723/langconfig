/**
 * BuildOntologyDialog — step one: generate an ontology with an agent, off to the side.
 *
 * A build is minutes of real work (schema introspection, three declaration files, a profile, a
 * tutorial, the gate suite three or four times). It runs as a background task, so this dialog is a
 * *status window*, not a progress bar: an agent's steps are not proportional, so it shows the last
 * things that actually happened, plus cancel and retry. When the build finishes it says whether it
 * landed itself (gates green → auto-land, the rule for a first generation) and what is left for a
 * person to decide.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Paperclip, Play, RefreshCw, Square, X } from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useProject } from '../../contexts/ProjectContext';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { mono, Quiet, SUCCESS, WARN, INFO } from './ui';
import BuildChatPanel from './BuildChatPanel';
import RunningLight, { RunningBar } from './RunningLight';

/**
 * What the form asks, and what it must never ask.
 *
 * A person choosing "generate an ontology" knows WHICH DATA this is about and what they want to ask it.
 * They do not know agent ids, folder names, profile files or ports — so the form asks for the data (by
 * its business label, from the database catalogue), the questions they ask, the decisions the numbers
 * support, the time range, whether anything is written, and what is out of scope. Agent, ontology
 * folder and landing mechanics are derived or phrased in plain language.
 */
interface BuilderOption {
  agent_id: number;
  agent_name: string;
  datasource: string;
  ontology_key: string;
  business_label: string;
  database?: string | null;
  has_ontology: boolean;
}

interface BuildRow {
  task_id: number;
  status: string;
  ontology_key: string;
  agent_id: number;
  auto_land: boolean;
  created_at: string | null;
  staged_id: string | null;
  landed: boolean | null;
}
interface BuildStatus extends BuildRow {
  started_at?: string | null;
  completed_at?: string | null;
  progress?: string[];
  error?: string | null;
  result?: {
    answer?: string;
    staged_id?: string;
    landed?: boolean;
    no_delta?: boolean;
    delta?: { items?: number; changed?: number; questions?: number; unchanged?: number; path?: string };
    reason?: string;
    report?: {
      compile?: { metrics?: number; compiled?: number };
      gates_ok?: boolean;
      gates_fails?: string[];
      gates_not_run?: string[];
      new_refusals?: string[];
      carried_refusals?: string[];
      files?: string[];
    };
  } | null;
}

const inputStyle = (t: any): React.CSSProperties => ({
  height: 28, padding: '0 8px', borderRadius: 6, fontSize: 12,
  border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
  color: t.textPrimary, outline: 'none', fontFamily: 'inherit',
});

const textareaStyle = (t: any): React.CSSProperties => ({
  padding: '6px 8px', borderRadius: 6, fontSize: 12, lineHeight: 1.6,
  border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
  color: t.textPrimary, outline: 'none', resize: 'vertical', fontFamily: 'inherit',
});

interface Props {
  ontologyKey: string;
  onClose: () => void;
  onLanded?: () => void;
}

export default function BuildOntologyDialog({ ontologyKey, onClose, onLanded }: Props) {
  const t = useLayoutTokens();
  const { activeProjectId } = useProject();
  const projectId = activeProjectId ?? 1;
  const [options, setOptions] = useState<BuilderOption[]>([]);
  const [optionKey, setOptionKey] = useState<string>('');
  // the brief, as the four questions a person can actually answer
  const [oneRow, setOneRow] = useState('');
  const [questions, setQuestions] = useState('');
  const [decisions, setDecisions] = useState('');
  const [timeRange, setTimeRange] = useState('');
  const [writes, setWrites] = useState('');
  const [excluded, setExcluded] = useState('');
  const key = ontologyKey;
  // auto-land is the FIRST-GENERATION rule. Defaulting it to true for a key that already has an
  // installed ontology would let a rebuild replace verified declarations with a fresh generation
  // nobody read — so the default follows `has_ontology`, and the checkbox says which case you are in.
  const [mode, setMode] = useState<'job' | 'chat'>('chat');
  const [autoLand, setAutoLand] = useState(true);
  const [autoLandTouched, setAutoLandTouched] = useState(false);
  // The business material is usually a DOCUMENT (a brief, a decisions list, a KPI sheet), not three
  // lines typed into a textarea. Measured: the build that produced this platform's cold-chain ontology
  // started from a docx and a markdown file, and the one thing the form could not take was exactly
  // that. Files are uploaded to the build's own chat session, where the platform extracts their text
  // and copies them into the agent's workspace `upload/`, so the agent reads them the same way it
  // reads any other input.
  const [files, setFiles] = useState<File[]>([]);
  const [uploadNote, setUploadNote] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [status, setStatus] = useState<BuildStatus | null>(null);
  const [history, setHistory] = useState<BuildRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  // Which DATA can be built — business labels, and the agent is whatever the platform wired to it.
  useEffect(() => {
    void (async () => {
      try {
        const res: any = await apiClient.get('/api/ontology/builders');
        const rows: BuilderOption[] = (res?.data?.builders || []) as BuilderOption[];
        setOptions(rows);
        // Preselect ONLY the ontology the user is looking at. Never fall through to rows[0]:
        // measured twice — a build meant for one ontology ran against another (logistics) because a
        // silent default was "whatever the dropdown happens to list first". No choice is a better
        // default than the wrong choice; Start stays disabled until the user picks one.
        const matching = rows.find(r => r.ontology_key === ontologyKey);
        setOptionKey(prev => prev || matching?.ontology_key || '');
      } catch {
        setOptions([]);
      }
    })();
  }, [ontologyKey]);

  const loadHistory = useCallback(async () => {
    try {
      const res: any = await apiClient.get('/api/ontology/builds', { params: { key, limit: 5 } });
      setHistory((res?.data?.builds || []) as BuildRow[]);
    } catch {
      setHistory([]);
    }
  }, [key]);
  useEffect(() => { void loadHistory(); }, [loadHistory]);

  const poll = useCallback(async (id: number) => {
    try {
      const res: any = await apiClient.get(`/api/ontology/build/${id}`);
      const d = res?.data as BuildStatus;
      setStatus(d);
      if (d?.status === 'COMPLETED' || d?.status === 'FAILED' || d?.status === 'CANCELLED') {
        if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
        await loadHistory();
        if (d?.result?.landed) onLanded?.();
      }
    } catch (err: any) {
      setError(String(err?.response?.data?.detail || err?.message || err));
    }
  }, [loadHistory, onLanded]);

  useEffect(() => {
    if (taskId == null) return;
    void poll(taskId);
    pollRef.current = window.setInterval(() => void poll(taskId), 4000);
    return () => {
      if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [taskId, poll]);

  const chosen = options.find(o => o.ontology_key === optionKey) || null;
  const ready = !!chosen && (!!(oneRow.trim() || questions.trim()) || files.length > 0);
  useEffect(() => {
    if (!chosen || autoLandTouched) return;
    setAutoLand(!chosen.has_ontology);
  }, [chosen, autoLandTouched]);

  const start = async () => {
    if (!chosen || !ready) return;
    setBusy(true); setError(null); setStatus(null);
    // The brief is the business answers, in the user's own words. Nothing technical travels here:
    // the ontology folder and the agent come from the chosen data.
    const brief = [
      oneRow.trim() && `这份数据里"一行"是什么：${oneRow.trim()}`,
      questions.trim() && `用户会这么问：${questions.trim()}`,
      decisions.trim() && `这些数字支撑什么决定：${decisions.trim()}`,
      timeRange.trim() && `时间范围：${timeRange.trim()}`,
      writes.trim() && `有没有写入（谁改数据、要不要审计）：${writes.trim()}`,
      excluded.trim() && `先不算在内：${excluded.trim()}`,
    ].filter(Boolean).join('\n');
    try {
      let sessionId: string | null = null;
      if (files.length) {
        setUploadNote(`opening a session for ${files.length} document(s)…`);
        const started: any = await apiClient.post('/api/chat/start',
          { agent_id: chosen.agent_id, project_id: projectId });
        sessionId = started?.data?.session_id ?? null;
        if (!sessionId) throw new Error('the build could not open a session for its documents');
        const fd = new FormData();
        for (const f of files) fd.append('files', f, f.name);
        setUploadNote(`uploading ${files.length} document(s)…`);
        await apiClient.post(`/api/chat/${sessionId}/upload-multiple`, fd,
          { headers: { 'Content-Type': 'multipart/form-data' }, params: { project_id: projectId } });
        setUploadNote(`attached ${files.length} document(s) — their text is in the session the agent reads`);
      }
      const res: any = await apiClient.post('/api/ontology/build', {
        agent_id: chosen.agent_id,
        ontology_key: chosen.ontology_key,
        brief: files.length
          ? `${brief}\n\n随这次构建上传的文档：${files.map(f => f.name).join('、')}。业务口径以这些文档为准：文档没写的按 skill 的规则提问/按名拒绝，不要猜。`
          : brief,
        project_id: projectId,
        auto_land: autoLand,
        session_id: sessionId ?? undefined,
      });
      setTaskId(Number(res?.data?.task_id));
    } catch (err: any) {
      setError(String(err?.response?.data?.detail || err?.message || err));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (taskId == null) return;
    try {
      await apiClient.post(`/api/background-tasks/${taskId}/cancel`, {});
    } catch (err: any) {
      setError(String(err?.response?.data?.detail || err?.message || err));
    }
  };

  const running = status?.status === 'RUNNING' || status?.status === 'PENDING';
  const startedAtMs = status?.started_at ? Date.parse(status.started_at) : null;
  const result = status?.result;

  return (
    <div
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
      style={{
        position: 'fixed', inset: 0, zIndex: 60, background: 'rgba(0,0,0,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
      }}
    >
      <div style={{
        width: 720, maxWidth: '96vw', maxHeight: '88vh', overflowY: 'auto',
        background: t.bgSidebar, color: t.textPrimary, borderRadius: 12,
        border: `1px solid ${t.border}`, padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 15, fontWeight: 600 }}>Generate / rebuild an ontology</span>
          <span style={{ fontSize: 11.5, color: t.textDim }}>
            {(options.find(o => o.ontology_key === optionKey) || {}).business_label
              || (options.length ? '' : key || '')}
          </span>
          <button onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}>
            <X size={15} />
          </button>
        </div>
        <div style={{ fontSize: 12, lineHeight: 1.6, color: t.textDim }}>
          Runs as a background job: it survives this dialog, reports what step it reached, and can be
          cancelled. With <b>auto-land</b> on, a build whose gates are all green installs itself
          (that is the “first generation” case); anything that fails a gate stays staged for a person.
        </div>

        {/* Two modes, both needed: the job answers "generate it now"; the conversation carries S0 and
            the delta, which a single turn cannot (measured: such a turn ends with questions, nothing
            staged). Both use the same builder agent. */}
        {taskId == null && (
          <div style={{ display: 'flex', gap: 6 }}>
            {([['job', '一次性构建'], ['chat', '对话式构建（推荐）']] as const).map(([m, label]) => (
              <button key={m} onClick={() => setMode(m)}
                style={{ fontSize: 11.5, padding: '4px 10px', borderRadius: 7, cursor: 'pointer',
                         border: `1px solid ${mode === m ? t.accent : t.border}`,
                         background: mode === m ? `${t.accent}14` : 'transparent',
                         color: mode === m ? t.accent : t.textDim }}>
                {label}
              </button>
            ))}
          </div>
        )}

        {mode === 'chat' && chosen && (
          <div style={{ height: 520, border: `1px solid ${t.border}`, borderRadius: 10, overflow: 'hidden' }}>
            <BuildChatPanel ontologyKey={chosen.ontology_key} onClose={() => setMode('job')} />
          </div>
        )}

        {mode === 'job' && taskId == null && (
          <>
            {options.length === 0 ? (
              <div style={{ fontSize: 12, color: WARN, lineHeight: 1.6 }}>
                还没有可以为这份数据生成本体的助手。这是管理员的一次性配置（把一份数据接到一个
                「本体构建助手」上）；配好后这里只会显示可选的<b>数据名称</b>，不需要你选 agent 或路径。
              </div>
            ) : (
              <>
                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11.5, color: t.textDim }}>
                  这是哪份数据？
                  <select
                    value={optionKey}
                    onChange={e => setOptionKey(e.target.value)}
                    style={{
                      height: 30, borderRadius: 7, fontSize: 12, border: `1px solid ${t.border}`,
                      background: t.bgInput || 'transparent', color: t.textPrimary,
                    }}
                  >
                    <option value="">— 先选择一份数据 —</option>
                    {options.map(o => (
                      <option key={o.ontology_key} value={o.ontology_key}>
                        {o.business_label} · <b>{o.ontology_key}</b> · {o.has_ontology ? '已有本体（重建）' : '尚无本体（首次生成）'}
                      </option>
                    ))}
                  </select>
                </label>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11.5, color: t.textDim }}>
                    这份数据里「一行」是什么？<span style={{ color: WARN }}>（必填：这两个二选一）</span>
                    <input
                      value={oneRow}
                      onChange={e => setOneRow(e.target.value)}
                      placeholder="一次配送 / 一次门诊预约 / 一张订单"
                      style={inputStyle(t)}
                    />
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11.5, color: t.textDim }}>
                    时间范围（"最近 30 天"有意义吗）
                    <input
                      value={timeRange}
                      onChange={e => setTimeRange(e.target.value)}
                      placeholder="数据是最近三个月 / 历史数据保留到去年 / 按财年"
                      style={inputStyle(t)}
                    />
                  </label>
                </div>

                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11.5, color: t.textDim }}>
                  用户会怎么问这些数据？<span style={{ color: WARN }}>（必填：这两个二选一）</span>（几句原话，一行一句）
                  <textarea
                    value={questions}
                    onChange={e => setQuestions(e.target.value)}
                    rows={4}
                    placeholder="这个月运费多少？&#10;哪条线路超载最多？&#10;哪些站点准时率低？&#10;并线之后破损有变化吗？"
                    style={textareaStyle(t)}
                  />
                </label>

                <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11.5, color: t.textDim }}>
                  这些数字支撑什么决定？
                  <textarea
                    value={decisions}
                    onChange={e => setDecisions(e.target.value)}
                    rows={2}
                    placeholder="该不该加一趟车 / 哪条线路要复查 / 哪个司机要培训"
                    style={textareaStyle(t)}
                  />
                </label>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11.5, color: t.textDim }}>
                    有没有写入？（谁改数据、要不要留痕）
                    <input
                      value={writes}
                      onChange={e => setWrites(e.target.value)}
                      placeholder="只读 / 调度会改派单"
                      style={inputStyle(t)}
                    />
                  </label>
                  <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11.5, color: t.textDim }}>
                    先不算在内
                    <input
                      value={excluded}
                      onChange={e => setExcluded(e.target.value)}
                      placeholder="测试门店 / 已停用的线路"
                      style={inputStyle(t)}
                    />
                  </label>
                </div>

                {/* documents: the brief is usually one already written */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                  <span style={{ fontSize: 11.5, color: t.textDim }}>
                    或者直接给文档（可选：需求说明 / 决策清单 / KPI 表；pdf·docx·pptx·xlsx·md·txt·csv）
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <label style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5,
                      padding: '5px 10px', borderRadius: 8, cursor: 'pointer',
                      border: `1px solid ${t.border}`, color: t.textPrimary,
                    }}>
                      <Paperclip size={11} /> 选择文档
                      <input
                        type="file" multiple
                        accept=".pdf,.docx,.doc,.pptx,.xlsx,.xlsm,.md,.txt,.csv,.json"
                        style={{ display: 'none' }}
                        onChange={e => {
                          const picked = Array.from(e.target.files || []);
                          setFiles(prev => [...prev, ...picked]);
                          e.currentTarget.value = '';
                        }}
                      />
                    </label>
                    {files.map((f, i) => (
                      <span key={`${f.name}-${i}`} style={{
                        display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11,
                        padding: '3px 8px', borderRadius: 999, border: `1px solid ${t.border}`,
                        color: t.textPrimary, maxWidth: 260,
                      }}>
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                        <span style={{ color: t.textDim }}>{(f.size / 1024).toFixed(0)} KB</span>
                        <span
                          onClick={() => setFiles(prev => prev.filter((_, j) => j !== i))}
                          style={{ cursor: 'pointer', color: t.textDim }}>×</span>
                      </span>
                    ))}
                  </div>
                  <span style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.5 }}>
                    上传后平台会抽取文字放进这次构建的会话，并把文件复制到 agent 的 workspace upload/，它读文档的方式和读别的一样；
                    文档没写的口径它要提问或按名拒绝，不会自己编。
                  </span>
                </div>

                <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 12, lineHeight: 1.6 }}>
                  <input type="checkbox" checked={autoLand} style={{ marginTop: 3 }}
                    onChange={e => { setAutoLand(e.target.checked); setAutoLandTouched(true) }} />
                  <span>
                    检查全部通过就自动上线（<b>只对第一次生成</b>）
                    <span style={{ color: t.textDim }}>
                      {chosen?.has_ontology
                        ? ' — 这份数据已经有已装的本体，所以这里默认不勾：重建结果留在 Settings → Ontology 等你点 apply，不会替换已经验证过的声明。'
                        : ' — 这份数据还没有本体，第一次生成是新的声明；之后每次改动都要你确认。'}
                    </span>
                  </span>
                </label>

                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button
                    onClick={() => void start()}
                    disabled={busy || !ready}
                    title={ready ? 'start the background build' : '需要先填「一行是什么」或「用户会怎么问」'}
                    style={{
                      display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600,
                      padding: '7px 14px', borderRadius: 8, border: 'none',
                      cursor: busy || !ready ? 'not-allowed' : 'pointer',
                      background: t.accent, color: '#fff',
                      opacity: busy || !ready ? 0.5 : 1,
                    }}
                  >
                    <Play size={12} /> 开始生成
                  </button>
                  <span style={{ fontSize: 11, color: ready ? t.textDim : WARN, lineHeight: 1.5 }}>
                    {uploadNote && <>{uploadNote}<br /></>}
                    {!chosen
                      ? '先选一份数据。'
                      : ready
                        ? '它会在后台跑（可关闭这个窗口），只把业务口径翻译成声明'
                        : '还差一步：填「一行是什么」或「用户会怎么问」，或者上传一份文档——否则 agent 拿不到要建的对象和问题。'}
                  </span>
                </div>
              </>
            )}
          </>
        )}

        {taskId != null && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
              <b>task #{taskId}</b>
              <span style={{
                ...mono, fontSize: 11, padding: '1px 7px', borderRadius: 9,
                border: `1px solid ${t.border}`,
                color: running ? WARN : status?.status === 'COMPLETED' ? SUCCESS : t.textDim,
              }}>{status?.status || 'queued'}</span>
              {running && (
                <button
                  onClick={() => void cancel()}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5,
                    padding: '4px 10px', borderRadius: 7, border: `1px solid ${t.border}`,
                    background: 'transparent', color: t.textPrimary, cursor: 'pointer',
                  }}
                >
                  <Square size={10} /> cancel
                </button>
              )}
              <button
                onClick={() => { setTaskId(null); setStatus(null); }}
                style={{ marginLeft: 'auto', fontSize: 11.5, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer' }}
              >
                start another
              </button>
            </div>
            <RunningBar running={!!running} />
            <div style={{ fontSize: 11.5, color: t.textDim, lineHeight: 1.7 }}>
              {(status?.progress || []).length === 0 && (running
                ? <span><Loader2 size={11} /> waiting for the worker…</span>
                : <Quiet>no progress recorded</Quiet>)}
              {(status?.progress || []).map((line, i) => (
                <div key={i} style={{ ...mono, fontSize: 10.5 }}>· {line}</div>
              ))}
            </div>
            {status?.error && (
              <div style={{ fontSize: 12, color: '#b3261e', whiteSpace: 'pre-wrap' }}>{status.error}</div>
            )}
            {result && (
              <div style={{
                border: `1px solid ${t.border}`, borderRadius: 9, padding: '10px 12px',
                display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12, lineHeight: 1.65,
              }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                  <b style={{ color: result.landed ? SUCCESS : result.no_delta ? INFO
                              : result.staged_id ? WARN : t.textMuted }}>
                    {result.landed ? 'landed'
                      : result.no_delta ? 'no delta — nothing to rebuild'
                      : result.staged_id ? 'staged, waiting for a person'
                      : 'stopped before staging'}
                  </b>
                  {result.staged_id && <span style={{ ...mono, fontSize: 11, color: t.textDim }}>{result.staged_id}</span>}
                  {!result.staged_id && (
                    <span style={{ fontSize: 11, color: t.textDim }}>
                      一次构建回合通常停在 S0：它先核对数据、把口径问题列出来（下面 agent's report 里就是）。
                      回答这些问题再跑一次，或在本体编辑器里继续；没暂存 = 没有东西可装。
                    </span>
                  )}
                </div>
                {result.reason && <div style={{ color: t.textDim }}>{result.reason}</div>}
                {result.delta && (
                  <div style={{ ...mono, fontSize: 11, color: t.textDim }}>
                    delta: {result.delta.items} item(s) compared · {result.delta.changed} change(s) ·
                    {' '}{result.delta.questions} question(s)
                  </div>
                )}
                {result.report?.compile && (
                  <div style={{ ...mono, fontSize: 11, color: t.textDim }}>
                    metrics {result.report.compile.compiled}/{result.report.compile.metrics} compiled ·
                    gates {result.report.gates_ok ? 'pass' : 'fail'}
                    {result.report.new_refusals?.length ? ` · NEW refusals: ${result.report.new_refusals.join(', ')}` : ''}
                  </div>
                )}
                {!!result.report?.gates_not_run?.length && (
                  <div style={{ fontSize: 11, color: t.textDim }}>
                    NOT RUN: {result.report.gates_not_run.join(' · ')}
                  </div>
                )}
                {result.answer && (
                  <details>
                    <summary style={{ fontSize: 11.5, color: t.textDim, cursor: 'pointer' }}>agent's report</summary>
                    <div style={{ fontSize: 11.5, whiteSpace: 'pre-wrap', marginTop: 4 }}>{result.answer}</div>
                  </details>
                )}
              </div>
            )}
          </>
        )}

        {error && <div style={{ fontSize: 12, color: '#b3261e' }}>{error}</div>}

        {history.length > 0 && (
          <div>
            <div style={{ fontSize: 10.5, textTransform: 'uppercase', letterSpacing: 0.5, color: t.textDim, marginBottom: 4 }}>
              recent builds for {key || 'this ontology'}
            </div>
            {history.map(h => (
              <div key={h.task_id} style={{ ...mono, fontSize: 10.5, color: t.textDim, lineHeight: 1.7 }}>
                #{h.task_id} · {h.status} · {h.landed ? 'landed' : h.staged_id ? 'staged' : '—'}
                {h.created_at ? ` · ${new Date(h.created_at).toLocaleString()}` : ''}
              </div>
            ))}
            <button
              onClick={() => void loadHistory()}
              style={{ marginTop: 4, fontSize: 11, background: 'none', border: 'none', color: t.textDim, cursor: 'pointer', display: 'inline-flex', gap: 4, alignItems: 'center' }}
            >
              <RefreshCw size={10} /> refresh
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

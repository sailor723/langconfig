/**
 * BuildQuestionsPanel — the questions a build stopped on, answerable in one place.
 *
 * A build's `questions.json` was written into the agent's workspace and read by nothing: the agent's
 * prose said "I have nine questions", the UI showed that prose, and answering meant retyping them
 * into a fresh brief — which started a NEW session and threw away every measurement the agent had
 * taken to ask them precisely. This panel reads the artifact, shows each question beside the default
 * the agent proposed, and submits the answers through `/api/ontology/build` with the ORIGINAL
 * `session_id`, so the build continues instead of restarting.
 *
 * The second half answers "how do I resume task 12?": a build is ONE agent turn, so there is no
 * page of steps to page through — the agent itself walks S1..S8 inside that turn, and continuing
 * means sending another brief into the SAME session. That session id only ever existed in the task
 * row, so this panel now lists the recent builds per key with the session each owns and a 续跑
 * button. Without it the only way back into a finished turn was to reconstruct a curl call.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCheck, CornerDownLeft, FileWarning, History, Loader2, Play, RefreshCw } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { Btn, Card, mono, DANGER, SUCCESS, WARN } from './ui';
import apiClient from '../../lib/api-client';

interface Question {
  id: string;
  ask: string;
  options?: string[];
  default?: string;
  blocks?: string;
  evidence?: string;
}

interface PendingBuild {
  task_id: number;
  agent_id: number;
  ontology_key: string;
  status: string;
  session_id: string | null;
  created_at: string | null;
  questions: Question[];
  answered: number;
  missing_documents: string[];
}

interface RecentBuild {
  task_id: number;
  agent_id: number;
  ontology_key: string;
  status: string;
  session_id: string | null;
  landed: boolean;
  reason: string | null;
  created_at: string | null;
}

const RESUME_BRIEF = '继续上一轮会话：读完 work/<key>/ 里已有的 answers.json / truth.json / 声明文件，'
  + '从上次停下的那一步接着走（不要重做 S0，不要重测已有口径）。每完成一步先落盘再报一行；'
  + '发布只到 staged，等我确认再 apply。';

export default function BuildQuestionsPanel({ onSubmitted }: { onSubmitted?: () => void }) {
  const t = useLayoutTokens();
  const [builds, setBuilds] = useState<PendingBuild[] | null>(null);
  const [recent, setRecent] = useState<RecentBuild[]>([]);
  const [resuming, setResuming] = useState<number | null>(null);
  const [resumeMsg, setResumeMsg] = useState<{ id: number; ok: boolean; text: string } | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [uploads, setUploads] = useState<string[]>([]);
  const [uploadNote, setUploadNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBuilds(null);
    try {
      const res: any = await apiClient.get('/api/ontology/build/pending-answers');
      const rows = (res?.data?.builds || []) as PendingBuild[];
      setBuilds(rows);
      setRecent((res?.data?.recent || []) as RecentBuild[]);
      if (rows.length && !rows.some(b => b.task_id === activeId)) setActiveId(rows[0].task_id);
    } catch {
      setBuilds([]);
    }
  }, [activeId]);

  useEffect(() => { void load(); }, []);           // eslint-disable-line react-hooks/exhaustive-deps

  const active = useMemo(
    () => (builds || []).find(b => b.task_id === activeId) || null,
    [builds, activeId],
  );

  useEffect(() => {
    //每一题先把 agent 给的默认值填进去：默认值就是它的建议，改哪条改哪条
    if (!active) { setAnswers({}); return; }
    const seed: Record<string, string> = {};
    for (const q of active.questions) seed[q.id] = q.default || '';
    setAnswers(seed);
  }, [active?.task_id]);                            // eslint-disable-line react-hooks/exhaustive-deps

  const acceptAll = () => {
    if (!active) return;
    const seed: Record<string, string> = {};
    for (const q of active.questions) seed[q.id] = q.default || '';
    setAnswers(seed);
  };

  const uploadDocs = async (files: FileList | null) => {
    if (!active || !files || files.length === 0) return;
    setUploadNote(`正在上传 ${files.length} 个文档…`);
    try {
      let sessionId = active.session_id;
      if (!sessionId) {
        const started: any = await apiClient.post('/api/chat/start', { agent_id: active.agent_id });
        sessionId = started?.data?.session_id ?? null;
      }
      const fd = new FormData();
      for (const f of Array.from(files)) fd.append('files', f, f.name);
      await apiClient.post(`/api/chat/${sessionId}/upload-multiple`, fd,
        { params: { project_id: undefined } });
      const names = Array.from(files).map(f => f.name);
      setUploads(prev => [...new Set([...prev, ...names])]);
      setUploadNote(`已放入它的 upload/：${names.join('、')} · 提交时会告诉它文件已补传`);
    } catch (err: any) {
      setUploadNote(`上传失败：${String(err?.response?.data?.detail || err?.message || err)}`);
    }
  };

  const submit = async () => {
    if (!active) return;
    setBusy(true); setMsg(null);
    try {
      const brief = [
        `以下是 admin 对 ${active.questions.length} 个问题的书面回答（沿用上一轮会话的上下文，不要重做 S0）：`,
        ...active.questions.map(q => `${q.id}：${(answers[q.id] || '').trim() || `（按默认：${q.default || '无'}）`}`),
        '',
        uploads.length ? `文件已补传到你的 upload/：${uploads.join('、')}（之前的"读不到"作废，请重新读一遍）。` : '',
        '请按 skill 继续：把答案写进 work/' + active.ontology_key + '/answers.json（assumed:false），',
        '然后从 S1 接着走，每完成一步先落盘再报一行；发布只到 staged，不要 apply。',
      ].join('\n');
      const res: any = await apiClient.post('/api/ontology/build', {
        agent_id: active.agent_id,
        ontology_key: active.ontology_key,
        brief,
        session_id: active.session_id || undefined,
        auto_land: false,
      });
      setMsg({ ok: true, text: `已提交，续跑原会话 · task ${res?.data?.task_id}` });
      onSubmitted?.();
      await load();
    } catch (err: any) {
      setMsg({ ok: false, text: String(err?.response?.data?.detail || err?.message || err) });
    } finally {
      setBusy(false);
    }
  };

  const resume = async (r: RecentBuild) => {
    setResuming(r.task_id); setResumeMsg(null);
    try {
      const brief = RESUME_BRIEF.replace('<key>', r.ontology_key);
      const res: any = await apiClient.post('/api/ontology/build', {
        agent_id: r.agent_id,
        ontology_key: r.ontology_key,
        brief,
        session_id: r.session_id || undefined,
        auto_land: false,
      });
      setResumeMsg({ id: r.task_id, ok: true, text: `已续跑 → task ${res?.data?.task_id}` });
      onSubmitted?.();
      await load();
    } catch (err: any) {
      setResumeMsg({ id: r.task_id, ok: false,
                     text: String(err?.response?.data?.detail || err?.message || err) });
    } finally {
      setResuming(null);
    }
  };

  const recentList = recent.length > 0 && (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <History size={14} color={t.textMuted} />
          <span style={{ fontSize: 12.5, fontWeight: 600, color: t.textPrimary }}>最近的构建（可以接着跑）</span>
          <span style={{ fontSize: 11, color: t.textDim, marginLeft: 'auto' }}>
            一个构建＝一次对话回合，续跑＝把新指令发回同一条会话
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {recent.map(r => (
            <div key={r.task_id} style={{
              display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
              fontSize: 11.5, padding: '5px 8px', borderRadius: 7,
              border: `1px solid ${t.border}`, background: `${t.border}22`,
            }}>
              <code style={mono}>task {r.task_id}</code>
              <span style={{ color: t.textPrimary }}>{r.ontology_key}</span>
              <span style={{
                fontSize: 10.5, padding: '1px 6px', borderRadius: 999,
                color: r.status === 'COMPLETED' ? SUCCESS : r.status === 'RUNNING' ? t.accent : DANGER,
                border: `1px solid ${(r.status === 'COMPLETED' ? SUCCESS : r.status === 'RUNNING' ? t.accent : DANGER)}55`,
              }}>{r.status}{r.landed ? ' · 已落地' : ''}</span>
              <span style={{ color: t.textDim }}>
                会话 <code style={mono}>{r.session_id ? r.session_id.slice(0, 8) : '未记录'}</code>
              </span>
              {r.reason && <span style={{ color: t.textDim, maxWidth: 260,
                                          overflow: 'hidden', textOverflow: 'ellipsis',
                                          whiteSpace: 'nowrap' }} title={r.reason}>{r.reason}</span>}
              <button onClick={() => void resume(r)}
                      disabled={resuming !== null || r.status === 'RUNNING' || r.status === 'PENDING'}
                      title={r.status === 'RUNNING' || r.status === 'PENDING'
                        ? '这一回合还在跑，等它结束再续'
                        : r.session_id ? '发一条指令回到这条会话的下一个回合'
                                       : '这条任务没记会话，续跑会新开一条'}
                      style={{
                        marginLeft: 'auto', fontSize: 11, padding: '3px 9px', borderRadius: 6,
                        display: 'inline-flex', alignItems: 'center', gap: 4,
                        border: `1px solid ${t.border}`, background: 'transparent',
                        color: t.textPrimary,
                        cursor: resuming !== null ? 'default' : 'pointer',
                        opacity: r.status === 'RUNNING' || r.status === 'PENDING' ? 0.45 : 1,
                      }}>
                {resuming === r.task_id
                  ? <Loader2 size={11} className="animate-spin" />
                  : <Play size={11} />}
                续跑
              </button>
              {resumeMsg?.id === r.task_id && (
                <span style={{ fontSize: 11, color: resumeMsg.ok ? SUCCESS : DANGER }}>{resumeMsg.text}</span>
              )}
            </div>
          ))}
        </div>
      </Card>
    );

  if (builds === null) {
    return <Card><div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5, color: t.textMuted }}>
      <Loader2 size={13} className="animate-spin" /> 正在读各 agent 的 questions.json…
    </div></Card>;
  }

  if (!builds.length) {
    return <>{recentList}<Card>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <CheckCheck size={14} color={SUCCESS} />
        <span style={{ fontSize: 12.5, color: t.textPrimary }}>没有待回答的构建</span>
        <button onClick={() => void load()}
                style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 8px', borderRadius: 6,
                         border: `1px solid ${t.border}`, background: 'transparent',
                         color: t.textMuted, cursor: 'pointer' }}>
          <RefreshCw size={11} /> 刷新
        </button>
      </div>
      <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 6, lineHeight: 1.6 }}>
        一个构建如果停在问题上，它的 <code style={mono}>work/&lt;key&gt;/questions.json</code> 会出现在这里，
        可以当场作答并**续跑原会话**（不重来）。已经跑过的回合在下面的「最近的构建」里，点续跑就回到它自己的会话。
      </div>
    </Card></>;
  }

  return (<>
    {recentList}
    <Card style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <AlertTriangle size={14} color={WARN} />
        <span style={{ fontSize: 13, fontWeight: 600, color: t.textPrimary }}>
          {builds.length} 个构建在等你回答
        </span>
        <span style={{ fontSize: 11, color: t.textDim }}>
          答完直接续跑原会话，不重做 S0
        </span>
        <button onClick={() => void load()} disabled={busy}
                style={{ marginLeft: 'auto', fontSize: 11, padding: '3px 8px', borderRadius: 6,
                         border: `1px solid ${t.border}`, background: 'transparent',
                         color: t.textMuted, cursor: busy ? 'default' : 'pointer' }}>
          <RefreshCw size={11} /> 刷新
        </button>
      </div>

      {builds.length > 1 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {builds.map(b => (
            <button key={b.task_id} onClick={() => setActiveId(b.task_id)}
                    style={{
                      fontSize: 11.5, padding: '3px 9px', borderRadius: 999, cursor: 'pointer',
                      border: `1px solid ${b.task_id === activeId ? t.accent : t.border}`,
                      background: b.task_id === activeId ? `${t.accent}14` : 'transparent',
                      color: b.task_id === activeId ? t.accent : t.textMuted,
                    }}>
              {b.ontology_key} · {b.questions.length} 问
            </button>
          ))}
        </div>
      )}

      {active && (
        <>
          <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>
            <code style={mono}>{active.ontology_key}</code> · task {active.task_id} · 会话{' '}
            <code style={mono}>{String(active.session_id || '（无，将新开会话）').slice(0, 8)}</code>
            {active.answered > 0 && ` · 已答 ${active.answered}/${active.questions.length}`}
            {!active.session_id && ' · 这条任务没有记录会话，提交会新开一条'}
          </div>

          {active.missing_documents.length > 0 && (
            <div style={{
              fontSize: 11.5, lineHeight: 1.7, padding: '7px 10px', borderRadius: 8,
              border: `1px solid ${WARN}55`, background: `${WARN}12`, color: t.textPrimary,
            }}>
              <FileWarning size={12} style={{ verticalAlign: -2, marginRight: 4 }} />
              它说自己读不到这些文档：<b>{active.missing_documents.join('、')}</b>
              —— 答案里可以写「文件已补传」，或先上传再提交。
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {active.questions.map(q => (
              <div key={q.id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                <div style={{ fontSize: 12.5, color: t.textPrimary, lineHeight: 1.65 }}>
                  <b style={{ ...mono, color: t.accent }}>{q.id}</b> · {q.ask}
                </div>
                {q.options?.length ? (
                  <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.7 }}>
                    选项：{q.options.map((o, i) => `${i + 1}) ${o}`).join('　')}
                  </div>
                ) : null}
                <textarea
                  value={answers[q.id] ?? ''}
                  onChange={e => setAnswers(prev => ({ ...prev, [q.id]: e.target.value }))}
                  rows={2}
                  placeholder={q.default ? `默认：${q.default}` : '写下你的答案'}
                  style={{
                    width: '100%', boxSizing: 'border-box', resize: 'vertical',
                    fontSize: 12, lineHeight: 1.6, padding: '6px 8px', borderRadius: 7,
                    border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary,
                  }}
                />
                {q.blocks && (
                  <div style={{ fontSize: 10.5, color: t.textDim }}>它会影响：{q.blocks}</div>
                )}
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 11.5, padding: '5px 10px', borderRadius: 7,
                             border: `1px solid ${t.border}`, background: 'transparent',
                             color: t.textPrimary, cursor: busy ? 'default' : 'pointer',
                             display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <FileWarning size={11} /> 补传缺失文档
              <input type="file" multiple style={{ display: 'none' }}
                     onChange={e => void uploadDocs(e.target.files)} />
            </label>
            <button onClick={acceptAll} disabled={busy}
                    style={{ fontSize: 11.5, padding: '5px 10px', borderRadius: 7,
                             border: `1px solid ${t.border}`, background: 'transparent',
                             color: t.textPrimary, cursor: busy ? 'default' : 'pointer' }}>
              全部采用默认值
            </button>
            <Btn variant="primary" onClick={() => void submit()} disabled={busy}>
              {busy ? <Loader2 size={11} className="animate-spin" /> : <CornerDownLeft size={11} />}
              提交并续跑
            </Btn>
            {uploadNote && (
              <span style={{ fontSize: 11, color: t.textMuted }}>{uploadNote}</span>
            )}
            {msg && (
              <span style={{ fontSize: 11.5, color: msg.ok ? SUCCESS : DANGER }}>{msg.text}</span>
            )}
          </div>
        </>
      )}
    </Card>
  </>);
}

/**
 * BuildChatPanel — the conversational build, wired to the pinned-seed endpoint.
 *
 * The one-shot Build dialog cannot carry the part that needs a conversation: S0 is a set of questions
 * about the business, and a rebuild is "prove the delta, then ask only about the delta". Trying to do
 * that in one job turn ends with questions and nothing staged (measured twice).
 *
 * So this panel streams a turn against the SAME builder agent the job uses — the one that carries the
 * datasource — through `/api/ontology/{key}/build/ask/stream`. The difference from the ordinary chat
 * panel is the seed: `build/state` tells the panel what the conversation starts from (installed
 * declarations or "nothing yet", the documents in the agent's upload/, the answers already given, the
 * artifacts already on disk), and the backend puts that in the first message of the session, so the
 * operator does not have to restate it every time.
 *
 * It never installs anything: publishing stops at staged, and applying stays a human action.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, Paperclip, Send, Square, X } from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { streamChatEvents } from '../chat/utils/streamChatEvents';
import { useProject } from '../../contexts/ProjectContext';
import { mono, Quiet, SUCCESS, WARN } from './ui';

interface Turn { role: 'user' | 'assistant'; content: string; tools?: string[] }

interface Pinned {
  key: string;
  agent: { id: number; name: string };
  workspace: string | null;
  installed: boolean;
  metrics: number;
  objects: number;
  documents: string[];
  artifacts: Record<string, number>;
  answers: boolean;
  staged: { id: string; note?: string | null }[];
}

export default function BuildChatPanel({ ontologyKey, onClose }: {
  ontologyKey: string;
  onClose: () => void;
}) {
  const t = useLayoutTokens();
  const { activeProjectId } = useProject();
  const projectId = activeProjectId ?? 1;
  const [info, setInfo] = useState<Pinned | null>(null);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const sessionKey = `langconfig.build.session.${ontologyKey}`;

  const loadState = useCallback(async () => {
    try {
      const res: any = await apiClient.get(`/api/ontology/${encodeURIComponent(ontologyKey)}/build/state`);
      setInfo(res?.data as Pinned);
      setInfoError(null);
    } catch (e: any) {
      setInfoError(String(e?.response?.data?.detail || e?.message || e));
    }
  }, [ontologyKey]);
  useEffect(() => { void loadState(); }, [loadState]);

  /** Documents land in the agent's workspace `upload/`, which is exactly where the seed looks. */
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true); setError(null);
    try {
      let sid = '';
      try { sid = localStorage.getItem(sessionKey) || ''; } catch { /* private mode */ }
      if (!sid) {
        const started: any = await apiClient.post('/api/chat/start',
          { agent_id: info?.agent.id, project_id: projectId });
        sid = started?.data?.session_id || '';
        try { if (sid) localStorage.setItem(sessionKey, sid); } catch { /* ignore */ }
      }
      const fd = new FormData();
      for (const f of Array.from(files)) fd.append('files', f, f.name);
      await apiClient.post(`/api/chat/${sid}/upload-multiple`, fd,
        { headers: { 'Content-Type': 'multipart/form-data' }, params: { project_id: projectId } });
      await loadState();
    } catch (e: any) {
      setError(String(e?.response?.data?.detail || e?.message || e));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const send = async (text: string) => {
    const body = text.trim();
    if (!body || busy) return;
    setError(null); setBusy(true); setDraft('');
    setTurns(prev => [...prev, { role: 'user', content: body }, { role: 'assistant', content: '' }]);
    const patchLast = (fn: (t: Turn) => Turn) =>
      setTurns(prev => {
        const next = [...prev];
        const i = next.length - 1;
        if (i >= 0) next[i] = fn(next[i]);
        return next;
      });
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const payload: Record<string, unknown> = { message: body, project_id: projectId };
      let sid = '';
      try { sid = localStorage.getItem(sessionKey) || ''; } catch { /* private mode */ }
      if (sid) payload.session_id = sid;
      for await (const ev of streamChatEvents(
        `/api/ontology/${encodeURIComponent(ontologyKey)}/build/ask/stream`, payload, ctrl.signal)) {
        if (ev.type === 'session' && ev.session_id) {
          try { localStorage.setItem(sessionKey, String(ev.session_id)); } catch { /* ignore */ }
        } else if (ev.type === 'chunk') {
          patchLast(turn => ({ ...turn, content: turn.content + String(ev.content || '') }));
        } else if (ev.type === 'tool_start') {
          patchLast(turn => ({ ...turn, tools: [...(turn.tools || []), String(ev.tool_name || 'tool')] }));
        } else if (ev.type === 'complete') {
          patchLast(turn => ({ ...turn, content: String(ev.content || turn.content) }));
        } else if (ev.type === 'error') {
          setError(String(ev.message || 'the turn failed'));
        }
      }
      await loadState();
    } catch (e: any) {
      if (e?.name === 'AbortError') patchLast(turn => ({ ...turn, content: turn.content + '\n\n(stopped)' }));
      else setError(String(e?.message || e));
    } finally {
      abortRef.current = null; setBusy(false);
    }
  };

  const first = !turns.length;
  const suggestion = info && !info.installed
    ? '这是首次生成：先读 upload/ 里的文档，做 S0 —— 核对数据、列出需要业务确认的口径问题（每题给默认值和后果），落 questions.json / draft.json，先不要写 TTL。'
    : '这是重建：对照已装声明和 upload/ 里的新文档，先产出 delta.json（changed/added/removed/questions），没有 delta 就停下说 NO DELTA。';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 12px', borderBottom: `1px solid ${t.border}` }}>
        <b style={{ fontSize: 13 }}>对话式构建 · {ontologyKey}</b>
        {info && (
          <span style={{ ...mono, fontSize: 11, color: t.textDim }}>
            {info.agent.name} · {info.installed ? `已装 ${info.objects} 对象/${info.metrics} 指标（重建）` : '尚无本体（首次生成）'}
          </span>
        )}
        <button onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}>
          <X size={15} />
        </button>
      </div>

      {info && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '8px 12px', borderBottom: `1px solid ${t.border}`, fontSize: 11, color: t.textDim }}>
          <span>文档 {info.documents.filter(d => !d.startsWith('.')).length}</span>
          <span>· 产物 {Object.keys(info.artifacts).length}</span>
          <span>· 口径账本 {info.answers ? '有' : '无'}</span>
          <span>· 提案 {info.staged.length}</span>
          {info.documents.filter(d => !d.startsWith('.')).map(d => (
            <span key={d} style={{ ...mono, color: t.textPrimary }}>{d}</span>
          ))}
        </div>
      )}
      {infoError && <div style={{ padding: '8px 12px', color: WARN, fontSize: 12 }}>{infoError}</div>}

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        {first && (
          <Quiet>
            首条消息会自动带上 pinned 上下文（已装声明 / 文档清单 / 已答口径 / 已有产物），你不用重复交代。
            下面这句可以直接发，也可以改。
          </Quiet>
        )}
        {turns.map((turn, i) => (
          <div key={i} style={{ fontSize: 12.5, lineHeight: 1.65, color: t.textPrimary }}>
            <div style={{ fontSize: 10.5, color: turn.role === 'user' ? t.accent : t.textDim, marginBottom: 2 }}>
              {turn.role === 'user' ? '你' : info?.agent.name || 'builder'}
            </div>
            <div style={{ whiteSpace: 'pre-wrap' }}>{turn.content || (busy && i === turns.length - 1 ? '…' : '')}</div>
            {!!turn.tools?.length && (
              <div style={{ ...mono, fontSize: 10.5, color: t.textDim }}>{turn.tools.join(' · ')}</div>
            )}
          </div>
        ))}
      </div>

      {error && <div style={{ padding: '6px 12px', color: WARN, fontSize: 12 }}>{error}</div>}

      <div style={{ borderTop: `1px solid ${t.border}`, padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {first && suggestion && (
          <div style={{ fontSize: 11, color: t.textDim }}>
            建议：<span style={{ color: t.textPrimary }}>{suggestion}</span>
          </div>
        )}
        <div style={{ display: 'flex', gap: 6, alignItems: 'flex-end' }}>
          <textarea
            value={draft} onChange={e => setDraft(e.target.value)} rows={2}
            placeholder={first ? suggestion : '下一步做什么？例如「按默认值回答 Q1–Q4，然后做 S1」'}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void send(draft || suggestion); }}
            style={{ flex: 1, minWidth: 0, fontSize: 12.5, padding: 8, borderRadius: 8, resize: 'vertical',
                     border: `1px solid ${t.border}`, background: 'transparent', color: t.textPrimary, outline: 'none' }}
          />
          <label title="上传文档到 agent 的 upload/（pinned 上下文会看到它）"
                 style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5,
                          padding: '6px 9px', borderRadius: 7, cursor: 'pointer',
                          border: `1px solid ${t.border}`, color: t.textDim }}>
            {uploading ? <Loader2 size={12} className="animate-spin" /> : <Paperclip size={12} />}
            <input ref={fileRef} type="file" multiple style={{ display: 'none' }}
                   accept=".pdf,.docx,.doc,.pptx,.xlsx,.xlsm,.md,.txt,.csv,.json"
                   onChange={e => void upload(e.target.files)} />
          </label>
          {busy ? (
            <button onClick={() => abortRef.current?.abort()}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, padding: '6px 10px',
                             borderRadius: 7, border: `1px solid ${t.border}`, background: 'transparent', color: WARN, cursor: 'pointer' }}>
              <Square size={11} /> 停止
            </button>
          ) : (
            <button onClick={() => void send(draft || (first ? suggestion || '' : ''))}
                    disabled={!(draft.trim() || first)}
                    style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11.5, padding: '6px 10px',
                             borderRadius: 7, border: 'none', background: t.accent, color: '#fff',
                             cursor: (draft.trim() || first) ? 'pointer' : 'not-allowed', opacity: (draft.trim() || first) ? 1 : 0.5 }}>
              <Send size={11} /> 发送
            </button>
          )}
        </div>
        <div style={{ fontSize: 10.5, color: t.textDim }}>
          ⌘/Ctrl+Enter 发送 · 发布停在 staged，apply 由人在 Settings → Ontology 点
        </div>
      </div>
    </div>
  );
}

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
import { Loader2, Play, RefreshCw, Square, X } from 'lucide-react';
import apiClient from '../../lib/api-client';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { mono, Quiet, SUCCESS, WARN } from './ui';

interface BuilderAgent { id: number; name: string }
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
  progress?: string[];
  error?: string | null;
  result?: {
    answer?: string;
    staged_id?: string;
    landed?: boolean;
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

interface Props {
  ontologyKey: string;
  onClose: () => void;
  onLanded?: () => void;
}

export default function BuildOntologyDialog({ ontologyKey, onClose, onLanded }: Props) {
  const t = useLayoutTokens();
  const [agents, setAgents] = useState<BuilderAgent[]>([]);
  const [agentId, setAgentId] = useState<number | null>(null);
  const [key, setKey] = useState(ontologyKey);
  const [brief, setBrief] = useState('');
  const [autoLand, setAutoLand] = useState(true);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [status, setStatus] = useState<BuildStatus | null>(null);
  const [history, setHistory] = useState<BuildRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  // Which agents can build: the ones that carry the publish channel, i.e. the ontology builders.
  useEffect(() => {
    void (async () => {
      try {
        const res: any = await apiClient.get('/api/deepagents/');
        const rows: any[] = res?.data || [];
        const builders: BuilderAgent[] = rows
          .filter((r: any) => (r?.config?.native_tools || []).includes('ontology_publish'))
          .map((r: any) => ({ id: Number(r.id), name: String(r.name || `agent ${r.id}`) }));
        setAgents(builders);
        setAgentId(prev => prev ?? (builders[0]?.id ?? null));
      } catch {
        setAgents([]);
      }
    })();
  }, []);

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

  const start = async () => {
    if (!agentId || !key.trim() || !brief.trim()) return;
    setBusy(true); setError(null); setStatus(null);
    try {
      const res: any = await apiClient.post('/api/ontology/build', {
        agent_id: agentId,
        ontology_key: key.trim(),
        brief: brief.trim(),
        project_id: 1,
        auto_land: autoLand,
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
          <span style={{ ...mono, fontSize: 11, color: t.textDim }}>{key || '—'}</span>
          <button onClick={onClose} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: t.textDim }}>
            <X size={15} />
          </button>
        </div>
        <div style={{ fontSize: 12, lineHeight: 1.6, color: t.textDim }}>
          Runs as a background job: it survives this dialog, reports what step it reached, and can be
          cancelled. With <b>auto-land</b> on, a build whose gates are all green installs itself
          (that is the “first generation” case); anything that fails a gate stays staged for a person.
        </div>

        {taskId == null && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11.5, color: t.textDim }}>
                builder agent
                <select
                  value={agentId ?? ''}
                  onChange={e => setAgentId(Number(e.target.value))}
                  style={{
                    height: 30, borderRadius: 7, fontSize: 12, border: `1px solid ${t.border}`,
                    background: t.bgInput || 'transparent', color: t.textPrimary,
                  }}
                >
                  {agents.length === 0 && <option value="">(no agent carries ontology_publish)</option>}
                  {agents.map(a => <option key={a.id} value={a.id}>{a.name} · #{a.id}</option>)}
                </select>
              </label>
              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11.5, color: t.textDim }}>
                ontology key (folder under ontologies/)
                <input
                  value={key}
                  onChange={e => setKey(e.target.value)}
                  style={{
                    height: 30, padding: '0 8px', borderRadius: 7, fontSize: 12,
                    border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
                    color: t.textPrimary, fontFamily: 'ui-monospace, Menlo, monospace',
                  }}
                />
              </label>
            </div>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11.5, color: t.textDim }}>
              brief — objects, the questions users actually ask, the decisions the numbers support
              <textarea
                value={brief}
                onChange={e => setBrief(e.target.value)}
                rows={6}
                placeholder="例：abc_coldchain；对象是行程/站点/车辆/司机/门店；老板会问「这个月运费多少」「哪条线路超载」「哪些站点准时率低」；要支持「该不该加一趟车」的决定；数据是最近 90 天；没有任何写路径。"
                style={{
                  padding: '8px 10px', borderRadius: 8, fontSize: 12, lineHeight: 1.6,
                  border: `1px solid ${t.border}`, background: t.bgInput || 'transparent',
                  color: t.textPrimary, fontFamily: 'inherit', resize: 'vertical',
                }}
              />
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
              <input type="checkbox" checked={autoLand} onChange={e => setAutoLand(e.target.checked)} />
              land automatically when every gate is green
            </label>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button
                onClick={() => void start()}
                disabled={busy || !agentId || !key.trim() || !brief.trim()}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 600,
                  padding: '7px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
                  background: t.accent, color: '#fff',
                  opacity: busy || !agentId || !brief.trim() ? 0.5 : 1,
                }}
              >
                <Play size={12} /> start build
              </button>
              {agents.length === 0 && (
                <span style={{ fontSize: 11.5, color: WARN }}>
                  no DeepAgent carries <code style={mono}>ontology_publish</code> — the builders are
                  348/349, seeded by the ontology skill
                </span>
              )}
            </div>
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
                  <b style={{ color: result.landed ? SUCCESS : WARN }}>
                    {result.landed ? 'landed' : 'staged, waiting for a person'}
                  </b>
                  {result.staged_id && <span style={{ ...mono, fontSize: 11, color: t.textDim }}>{result.staged_id}</span>}
                </div>
                {result.reason && <div style={{ color: t.textDim }}>{result.reason}</div>}
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

/**
 * DashboardChat — the business question, next to the business numbers.
 *
 * This is the ontology's own question pipeline (`POST /api/ontology/{key}/ask` → the
 * `answer-ontology-question` skill → rules first, a model only when the rules are unsure), moved
 * onto the dashboard so a reader can go from "超载率 36.8%" to "那准时率呢" without leaving the page.
 *
 * Three rules it inherits rather than invents:
 *  · the answer is a NUMBER plus the SQL that produced it — never a paragraph about a number;
 *  · a refusal is an ANSWER (rendered green-less, in the compiler's own words), not an error;
 *  · nothing is computed here. `fmt` only formats what came back.
 *
 * Not yet: the question does not carry the dashboard's filter. Declared dimension filters land in
 * the next step; until they do, the footer says so instead of implying the answer is filtered.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CornerDownLeft, Loader2, Sigma, X } from 'lucide-react';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { Btn, DANGER, mono, SUCCESS, WARN } from './ui';
import apiClient from '../../lib/api-client';

interface AskResponse {
  ok: boolean;
  question?: string;
  answer?: string;
  refused?: string;
  metric?: string | null;
  value?: number | null;
  rows?: Array<{ key: string; value: number | null }> | null;
  sql?: string | null;
  source?: string;
  ms?: number;
  needs_confirmation?: boolean;
  guard?: { notes?: string[] };
}

interface Turn { q: string; res: AskResponse }

function fmt(v: number | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (unit === 'ratio') return `${(n * 100).toFixed(1)}%`;
  if (unit === 'money') return `¥${n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
  if (Math.abs(n - Math.round(n)) < 1e-9) return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (Math.abs(n) >= 1000) return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (Math.abs(n) >= 10) return n.toFixed(1);
  return n.toFixed(3);
}

export default function DashboardChat({
  ontologyKey, unitOf, height, onClose,
}: {
  ontologyKey: string | null;
  unitOf: (metric?: string | null) => { label?: string | null; unit?: string | null };
  height?: number | string;
  /** Closes the dock it lives in. The page's 对话 button opens it; this is the way back out. */
  onClose?: () => void;
}) {
  const t = useLayoutTokens();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openSql, setOpenSql] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [turns, busy]);

  const send = useCallback(async () => {
    const q = text.trim();
    if (!q || !ontologyKey || busy) return;
    setBusy(true); setError(null); setText('');
    try {
      const res: any = await apiClient.post(
        `/api/ontology/${encodeURIComponent(ontologyKey)}/ask`, { question: q }, { timeout: 180000 });
      const payload = (res?.data ?? res) as AskResponse;
      setTurns(prev => [...prev, { q, res: payload }]);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '问答失败');
      setTurns(prev => [...prev, { q, res: { ok: false, refused: String(err?.message || err) } }]);
    } finally {
      setBusy(false);
    }
  }, [text, ontologyKey, busy]);

  // THE SUGGESTIONS ARE THE ONTOLOGY'S OWN SAMPLES, not a list that lives in this component.
  //
  // Measured on the deployment: the hardcoded four were ['超载率是多少', '并线前后准时率变化',
  // '按车辆看每千站破损箱数', '责任未判定投诉数'] — the third one refused ("nothing declares a grouping
  // by ['车辆']") because no grouped declaration existed, and '并线前后准时率变化' refused for the same
  // reason. A dashboard that offers a question the ontology cannot answer teaches a user that the
  // ontology is broken. The samples the Query page shows are the gate-checked front door
  // (`check_samples.py` runs every one), so the dashboard reads the SAME list: one source, and a
  // question that appears in one place appears in the other.
  const [suggestions, setSuggestions] = useState<string[]>([]);
  useEffect(() => {
    if (!ontologyKey) { setSuggestions([]); return; }
    let cancelled = false;
    fetch(`/api/ontology/${encodeURIComponent(ontologyKey)}/wb/samples`)
      .then(r => (r.ok ? r.json() : { samples: [] }))
      .then(d => {
        if (cancelled) return;
        const list: string[] = Array.isArray(d?.samples) ? d.samples.filter((s: any) => typeof s === 'string') : [];
        // the menu is DECLARED samples + one question per declared metric (so a new metric shows up
        // here without anyone editing a list). Show a few of each: the authored examples first —
        // they are the gate-checked ones — then questions that exist because a metric exists.
        const n = Number(d?.declared_count ?? list.length);
        const authored = list.slice(0, Math.min(4, n));
        const derived = list.slice(n, n + 4);
        setSuggestions([...authored, ...derived].slice(0, 8));
      })
      .catch(() => { if (!cancelled) setSuggestions([]); });
    return () => { cancelled = true; };
  }, [ontologyKey]);

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: height || 'calc(100vh - 140px)',
      minHeight: 380, background: t.bgContent, border: `1px solid ${t.border}`, borderRadius: 10,
      overflow: 'hidden',
    }}>
      <div style={{ padding: '10px 12px 8px', borderBottom: `1px solid ${t.border}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Sigma size={13} color={t.accent} />
          <span style={{ fontSize: 12.5, fontWeight: 700, color: t.textPrimary }}>业务问答</span>
          <span style={{ marginLeft: 'auto', fontSize: 10.5, color: t.textDim }}>
            确定性口径 · 拒答即答案
          </span>
          {onClose && (
            <button onClick={onClose} title="收起问答（看板留在原地）"
                    style={{ border: 'none', background: 'transparent', cursor: 'pointer',
                             color: t.textMuted, display: 'inline-flex', padding: 2 }}>
              <X size={13} />
            </button>
          )}
        </div>
        <div style={{ fontSize: 10.5, color: t.textMuted, marginTop: 4, lineHeight: 1.5 }}>
          问的是这个本体声明的指标；答不出来会说出缺的是哪条声明。
        </div>
      </div>

      <div ref={listRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '10px 12px' }}>
        {turns.length === 0 && !busy && (
          <div style={{ display: 'grid', gap: 6 }}>
            <div style={{ fontSize: 11, color: t.textDim }}>
              {suggestions.length ? '这个本体自己给的例句（与 Query 页同一份 samples）：' : ''}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {suggestions.map(s => (
                <button
                  key={s}
                  onClick={() => setText(s)}
                  style={{
                    textAlign: 'left', padding: '5px 9px', borderRadius: 999, cursor: 'pointer',
                    border: `1px solid ${t.border}`, background: 'transparent',
                    color: t.textMuted, fontSize: 11.5, fontFamily: 'inherit',
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, i) => {
          const meta = unitOf(turn.res.metric);
          const rows = turn.res.rows || [];
          return (
            <div key={i} style={{ marginBottom: 12 }}>
              <div style={{
                fontSize: 11.5, color: t.textPrimary, background: `${t.accent}14`,
                border: `1px solid ${t.accent}33`, borderRadius: 8, padding: '6px 8px',
              }}>
                {turn.q}
              </div>
              <div style={{ marginTop: 6, fontSize: 11.5, lineHeight: 1.6 }}>
                {turn.res.ok ? (
                  <>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, ...mono }}>
                        {rows.length > 1
                          ? `${rows.length} 组`
                          : fmt(turn.res.value ?? rows[0]?.value, meta.unit)}
                      </span>
                      {turn.res.metric && (
                        <span style={{ fontSize: 10.5, color: t.textDim, ...mono }}>
                          :{turn.res.metric}
                        </span>
                      )}
                      {meta.label && <span style={{ fontSize: 10.5, color: t.textMuted }}>{meta.label}</span>}
                    </div>
                    {rows.length > 1 && (
                      <div style={{ marginTop: 4, display: 'grid', gap: 2 }}>
                        {rows.slice(0, 4).map(r => (
                          <div key={r.key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                            <span style={{ color: t.textMuted }}>{r.key}</span>
                            <span style={{ ...mono, color: t.textPrimary }}>{fmt(r.value, meta.unit)}</span>
                          </div>
                        ))}
                        {rows.length > 4 && (
                          <div style={{ fontSize: 10.5, color: t.textDim }}>… 共 {rows.length} 组</div>
                        )}
                      </div>
                    )}
                    {turn.res.sql && (
                      <div style={{ marginTop: 4 }}>
                        <button
                          onClick={() => setOpenSql(openSql === i ? null : i)}
                          style={{
                            border: 'none', background: 'transparent', padding: 0, cursor: 'pointer',
                            fontSize: 10.5, color: t.textMuted,
                          }}
                        >
                          口径{openSql === i ? ' ▲' : ' ▼'}
                        </button>
                        {openSql === i && (
                          <pre style={{
                            margin: '4px 0 0', padding: 6, borderRadius: 6, background: `${t.border}33`,
                            fontSize: 10, lineHeight: 1.45, color: t.textMuted, ...mono,
                            whiteSpace: 'pre-wrap', maxHeight: 140, overflow: 'auto',
                          }}>{turn.res.sql}</pre>
                        )}
                      </div>
                    )}
                    {turn.res.ms != null && (
                      <div style={{ fontSize: 10, color: t.textDim, marginTop: 2 }}>
                        {turn.res.ms} ms · {turn.res.source || 'template'}
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{ display: 'flex', gap: 5, color: DANGER }}>
                    <AlertTriangle size={12} style={{ flex: 'none', marginTop: 2 }} />
                    <span style={{ ...mono, fontSize: 10.5, lineHeight: 1.5 }}>
                      {turn.res.refused || '拒答'}
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {busy && (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11, color: t.textMuted }}>
            <Loader2 size={12} style={{ animation: 'lc-spin 1s linear infinite' }} />
            按声明匹配指标并编译…
          </div>
        )}
        {error && (
          <div style={{ fontSize: 11, color: WARN }}>{error}</div>
        )}
      </div>

      <div style={{ padding: 8, borderTop: `1px solid ${t.border}`, flexShrink: 0 }}>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); }
          }}
          placeholder={ontologyKey ? '用业务的话问这个本体…（Enter 发送）' : '先选一个本体'}
          disabled={!ontologyKey}
          rows={2}
          style={{
            width: '100%', resize: 'none', padding: '6px 8px', borderRadius: 8, fontSize: 11.5,
            border: `1px solid ${t.border}`, background: t.bgInput, color: t.textPrimary,
            fontFamily: 'inherit', outline: 'none',
          }}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6 }}>
          <span style={{ fontSize: 10, color: t.textDim }}>
            {text.trim() ? 'Enter 发送' : '不套用看板筛选（下一步才贯穿）'}
          </span>
          <span style={{ marginLeft: 'auto' }} />
          <Btn variant="primary" onClick={() => void send()} disabled={busy || !text.trim() || !ontologyKey}>
            {busy ? <Loader2 size={12} /> : <CornerDownLeft size={12} />}
            <span style={{ marginLeft: 4 }}>问</span>
          </Btn>
        </div>
      </div>
    </div>
  );
}

/**
 * OntologyDashboardPage — a dashboard that is a DECLARATION, rendered.
 *
 * Everything on this page comes from `GET /api/ontology/{key}/dashboard/panels`, which shells out to
 * the ontology's own compiler (`retail_graph/run_dashboard.py`). The page knows no metric name and
 * computes no rate: it reads `dashboard.json` (which panel, which declared metric, cut by what) and
 * draws what came back. Consequences worth stating, because they are the design:
 *
 *  · a panel whose metric refuses renders as a REFUSAL, in place, naming the missing declaration —
 *    the holes are part of the dashboard, not an empty state;
 *  · every panel can show its compiled SQL, the guard's report and the estimated plan rows ("口径");
 *  · nothing is filtered client-side to look better. Clicking a value highlights it and copies a
 *    question the ontology can actually answer — per-value filtering is NOT declared yet, and the
 *    page says so instead of faking it.
 *
 * Two of the panels are custom on purpose (see `dashboard.json` → `why_custom`):
 *   1. merge_slope     — absolute volume and rates on ONE version axis; four generic panels would
 *                        hide that they move together;
 *   2. dispatch_review — the panel whose declaration does not exist yet: it shows what IS measurable
 *                        (on-time vs overload per vehicle) next to what is missing (:DispatchDecision).
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { AlertTriangle, ArrowRight, BarChart3, Boxes, Copy, RefreshCw, Route, Sigma, Sparkles } from 'lucide-react';
import { useLayoutTokens } from '../components/layout2/tokens';
import { Btn, Card, Chip, Hero, PageShell, Section, mono, CYAN, DANGER, INFO, SUCCESS, VIOLET, WARN } from '../features/ontology/ui';
import { ontology, useOntology } from '../features/ontology/ontologyStore';
import DashboardChat from '../features/ontology/DashboardChat';
import { BubblePanel, ParallelPanel, SankeyPanel, TreemapPanel } from '../features/ontology/dashboardCharts';
import apiClient from '../lib/api-client';

// ── payload types (what run_dashboard.py returns) ─────────────────────────────────────────────
interface MetricResult {
  ok: boolean;
  metric: string;
  status: 'ok' | 'refused' | 'error' | 'missing_declaration';
  label?: string | null;
  unit?: string | null;
  grain?: string | null;
  keys?: number;
  time_bucket?: string | null;
  scale?: string | null;
  where?: string | null;
  columns?: string[];
  rows?: Array<Array<string | number | null>>;
  sql?: string;
  guard_notes?: string[];
  plan_rows?: number | null;
  refused?: string;
  ms?: number;
}
interface Panel {
  id: string;
  kind: 'kpi' | 'slope' | 'series' | 'ranked' | 'matrix' | 'composition' | 'hole'
    | 'sankey' | 'bubble' | 'treemap' | 'parallel';
  view?: string;
  title: string;
  question?: string;
  metric?: string;
  metrics?: string[];
  size_by?: string;
  sort?: 'asc' | 'desc';
  client_sort?: boolean;
  limit?: number;
  render?: string;
  marks?: string[];
  rows?: string;
  cols?: string;
  nodes?: Array<{ id: string; label: string }>;
  links?: Array<{ from: string; to: string; metric: string; key: string }>;
  x?: { dimension?: string; order?: string[] } | string;
  y?: string;
  size?: string;
  color?: string;
  color_labels?: Record<string, string>;
  allow_missing?: boolean;
  emit_filter?: { dimension: string; column?: string };
  filter_not_applicable?: string;
  row_label?: string;
  col_label?: string;
  null_label?: string;
  note?: string;
  expect?: string;
  why_custom?: string;
  ask_with?: string;
  requires?: string[];
  missing?: string;
  measurable_now?: { note?: string; metrics?: string[] };
  results: Record<string, MetricResult>;
}
interface DashboardPayload {
  ok: boolean;
  title?: string;
  subtitle?: string;
  events?: Array<{ id: string; at: string; label: string; note?: string; metric?: string }>;
  kpis?: Array<{ metric: string; note?: string; result: MetricResult | null }>;
  panels?: Panel[];
  holes?: Array<{ metric: string; label?: string; status: string; reason?: string; why?: string; matches_declaration?: boolean }>;
  refused?: Array<{ metric: string; label?: string; refused?: string }>;
  metrics?: Record<string, MetricResult>;
  filters?: Record<string, string>;
  value_sets?: Record<string, Array<string | number | boolean | null>>;
  briefing?: {
    headline: string;
    headline_problems: string[];
    claims: Array<{
      id: string; text?: string; rendered: string; note?: string;
      resolvable: boolean; problems: string[];
      verdict?: 'red' | 'green' | null; verdict_by?: string | null; verdict_text?: string | null;
    }>;
    cannot_see: string[];
    next: string;
    policy: Array<{
      id: string; label: string; metric: string; op: string; value: number;
      current: number | null; unit?: string | null; current_text: string;
      breached: boolean; assumed?: boolean; confirmed?: boolean; why?: string; status: string;
    }>;
    verdict: { level: 'red' | 'green'; breaches: string[]; unconfirmed: string[] };
    resolvable: boolean;
  };
  declaration_stale?: boolean;
  elapsed_ms?: number;
  cached?: boolean;
  error?: string;
}

// ── formatting: the ONLY arithmetic on this page is presentation ──────────────────────────────
function fmt(v: number | null | undefined, unit?: string | null): string {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (unit === 'ratio') return `${(n * 100).toFixed(1)}%`;
  if (unit === 'money') return `¥${n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
  if (unit === 'km') return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (Math.abs(n - Math.round(n)) < 1e-9) return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (Math.abs(n) >= 1000) return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  if (Math.abs(n) >= 10) return n.toFixed(1);
  return n.toFixed(2);
}
const keyLabel = (k: string | number | null, nullLabel?: string) =>
  k === null || k === undefined ? (nullLabel || '（未判定）') : String(k);

function rowsOf(res: MetricResult | null | undefined): Array<Array<string | number | null>> {
  return (res?.rows as Array<Array<string | number | null>>) || [];
}

// ── the frame every panel shares: question, status, and a "口径" drawer ──────────────────────
function PanelFrame({
  panel, children, tone,
}: { panel: Panel; children: React.ReactNode; tone?: string }) {
  const t = useLayoutTokens();
  const [open, setOpen] = useState(false);
  const res = panel.results?.[panel.metric || (panel.metrics || [])[0] || ''];
  const refused = res && res.status !== 'ok';
  return (
    <Card style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontSize: 13.5, fontWeight: 700, color: t.textPrimary }}>{panel.title}</span>
        {panel.view === 'custom' && <Chip colour={VIOLET}>定制</Chip>}
        {panel.kind === 'hole' && <Chip colour={DANGER}>空洞</Chip>}
        {/* a view that cannot be cut says so on the card; a filtered board must never look uniformly
            filtered when one block is not */}
        {panel.filter_not_applicable && (
          <span title={panel.filter_not_applicable}
            style={{ fontSize: 10, color: WARN, border: `1px solid ${WARN}55`, borderRadius: 999,
                     padding: '0 6px', lineHeight: '16px' }}>
            不适用筛选
          </span>
        )}
        <button
          onClick={() => setOpen(!open)}
          title="口径：声明、编译出的 SQL、guardrails 报告"
          style={{
            marginLeft: 'auto', border: 'none', background: 'transparent', cursor: 'pointer',
            fontSize: 11, color: t.textMuted, padding: 0,
          }}
        >
          口径{open ? ' ▲' : ' ▼'}
        </button>
      </div>
      {panel.question && (
        <div style={{ fontSize: 11.5, color: t.textMuted, lineHeight: 1.5 }}>{panel.question}</div>
      )}
      {refused ? (
        <div style={{ fontSize: 12, color: DANGER, lineHeight: 1.6 }}>
          <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
          {res?.status === 'missing_declaration' ? '未声明' : '拒绝回答'}：{res?.refused}
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0 }}>{children}</div>
      )}
      {open && (
        <div style={{ borderTop: `1px solid ${t.border}`, paddingTop: 8, display: 'grid', gap: 6 }}>
          <div style={{ fontSize: 10.5, color: t.textDim, ...mono }}>
            指标 :{res?.metric} · 颗粒度 :{res?.grain} · 键 {res?.keys} · {res?.ms}ms
            {res?.plan_rows != null && ` · plan ≤ ${res.plan_rows} 行`}
          </div>
          {res?.sql && (
            <pre style={{
              margin: 0, padding: 8, borderRadius: 6, background: `${t.border}33`,
              fontSize: 10.5, lineHeight: 1.45, color: t.textMuted, overflowX: 'auto',
              whiteSpace: 'pre-wrap', maxHeight: 160, ...mono,
            }}>{res.sql}</pre>
          )}
          {(res?.guard_notes || []).map((n, i) => (
            <div key={i} style={{ fontSize: 10.5, color: WARN, ...mono }}>guard · {n}</div>
          ))}
          {panel.note && <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5 }}>{panel.note}</div>}
        </div>
      )}
      {tone && <div style={{ height: 2, background: `${tone}66`, borderRadius: 2 }} />}
    </Card>
  );
}

// ── the opening assessment ──────────────────────────────────────────────────────────────────
// Every number in these sentences came from a compiled value (D7 refuses a hand-typed one), and the
// red/green comes from a declared policy whose thresholds are marked as assumptions until a human
// confirms them. The "cannot see" list is part of the assessment, not a footnote.
function BriefingBlock({ briefing }: { briefing: NonNullable<DashboardPayload['briefing']> }) {
  const t = useLayoutTokens();
  const [openWhy, setOpenWhy] = useState(false);
  const red = briefing.verdict.level === 'red';
  const head = red ? DANGER : SUCCESS;
  return (
    <Card style={{ marginBottom: 18, borderColor: `${head}55`, padding: 16 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <div style={{
          flex: 'none', padding: '3px 10px', borderRadius: 999, fontSize: 11.5, fontWeight: 700,
          color: head, background: `${head}18`, border: `1px solid ${head}55`,
        }}>
          {red ? '需要处理' : '正常'}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13.5, lineHeight: 1.7, color: t.textPrimary, fontWeight: 600 }}>
            {briefing.headline}
          </div>
          {briefing.headline_problems.length > 0 && (
            <div style={{ fontSize: 11, color: DANGER, marginTop: 4, ...mono }}>
              有结论算不出来：{briefing.headline_problems.join(' · ')}
            </div>
          )}
          <div style={{ display: 'grid', gap: 6, marginTop: 10 }}>
            {briefing.claims.map(c => (
              <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <span style={{
                  flex: 'none', width: 6, height: 6, borderRadius: 3, marginTop: 6,
                  background: c.verdict === 'red' ? DANGER : c.verdict === 'green' ? SUCCESS : t.textDim,
                }} title={c.verdict_text || undefined} />
                <div style={{ minWidth: 0 }}>
                  <span style={{
                    fontSize: 11.5, lineHeight: 1.65,
                    color: c.resolvable ? t.textPrimary : DANGER,
                  }}>
                    {c.rendered}
                  </span>
                  {c.note && (
                    <span style={{ fontSize: 10.5, color: t.textDim }}>　{c.note}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* the thresholds: visible, and labelled when they are OUR assumption rather than the
          business's decision */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
        {briefing.policy.map(pol => (
          <span key={pol.id} title={pol.why || ''} style={{
            display: 'inline-flex', gap: 5, alignItems: 'center', fontSize: 10.5, ...mono,
            padding: '2px 8px', borderRadius: 999,
            border: `1px solid ${pol.breached ? DANGER : t.border}55`,
            background: pol.breached ? `${DANGER}12` : 'transparent',
            color: pol.breached ? DANGER : t.textMuted,
          }}>
            {pol.label} {pol.op} {fmt(pol.value, pol.unit === 'ratio' ? 'ratio' : pol.unit)}
            <span style={{ color: t.textDim }}>现在 {pol.current_text}</span>
            {pol.assumed && !pol.confirmed && <span style={{ color: WARN }}>假设</span>}
          </span>
        ))}
      </div>

      <div style={{ marginTop: 10, borderTop: `1px solid ${t.border}`, paddingTop: 8 }}>
        <button
          onClick={() => setOpenWhy(!openWhy)}
          style={{ border: 'none', background: 'transparent', padding: 0, cursor: 'pointer',
                   fontSize: 11, color: t.textMuted }}
        >
          这个看板看不见什么{openWhy ? ' ▲' : ' ▼'}
        </button>
        {openWhy && (
          <ul style={{ margin: '6px 0 0', paddingLeft: 16, fontSize: 11, color: t.textMuted, lineHeight: 1.7 }}>
            {briefing.cannot_see.map((item, i) => <li key={i}>{item}</li>)}
          </ul>
        )}
        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.7, marginTop: 6 }}>
          <span style={{ color: t.textPrimary, fontWeight: 600 }}>下一步　</span>{briefing.next}
        </div>
      </div>
    </Card>
  );
}

// ── KPI ─────────────────────────────────────────────────────────────────────────────────────
function KpiStrip({ kpis }: { kpis: NonNullable<DashboardPayload['kpis']> }) {
  const t = useLayoutTokens();
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
      {kpis.map(k => {
        const r = k.result;
        const bad = r && r.status !== 'ok';
        return (
          <Card key={k.metric} style={{ padding: 12, opacity: bad ? 0.75 : 1 }}>
            <div style={{ fontSize: 10.5, color: t.textDim, textTransform: 'uppercase', letterSpacing: 0.4 }}>
              {r?.label || k.metric}
            </div>
            <div style={{ fontSize: 20, fontWeight: 700, color: bad ? DANGER : t.textPrimary, lineHeight: 1.3 }}>
              {bad ? '拒答' : fmt(rowsOf(r)[0]?.[0] as number, r?.unit)}
            </div>
            <div style={{ fontSize: 10.5, color: t.textMuted }}>{bad ? r?.refused?.slice(0, 46) : k.note}</div>
          </Card>
        );
      })}
    </div>
  );
}

// ── custom view 1: the merge slope ──────────────────────────────────────────────────────────
function SlopePanel({ panel }: { panel: Panel }) {
  const t = useLayoutTokens();
  const order = (panel as Panel & { x?: { order?: string[] } }).x?.order || ['v1', 'v2'];
  const metrics = panel.metrics || [];
  const cells = metrics.map(name => {
    const res = panel.results[name];
    const byKey = new Map(rowsOf(res).map(r => [String(r[0]), Number(r[1])]));
    const a = byKey.get(order[0]);
    const b = byKey.get(order[1]);
    const delta = a != null && b != null && a !== 0 ? (b - a) / Math.abs(a) : null;
    return { name, res, a, b, delta };
  });
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'grid', gridTemplateColumns: `140px 1fr 1fr 64px`, gap: 8, fontSize: 10.5, color: t.textDim }}>
        <span />
        <span>{order[0]}（并线前）</span>
        <span>{order[1]}（并线后）</span>
        <span style={{ textAlign: 'right' }}>变化</span>
      </div>
      {cells.map(({ name, res, a, b, delta }) => (
        <div key={name} style={{ display: 'grid', gridTemplateColumns: '140px 1fr 1fr 64px', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11.5, color: t.textMuted }}>{res?.label || name}</span>
          <span style={{ fontSize: 15, fontWeight: 600, color: t.textPrimary, ...mono }}>{fmt(a, res?.unit)}</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <ArrowRight size={13} color={t.textMuted} />
            <span style={{ fontSize: 15, fontWeight: 700, color: t.textPrimary, ...mono }}>{fmt(b, res?.unit)}</span>
          </span>
          <span style={{
            fontSize: 11.5, textAlign: 'right', fontWeight: 700, ...mono,
            color: delta == null ? t.textMuted : delta > 0.02 ? DANGER : delta < -0.02 ? SUCCESS : t.textMuted,
          }}>
            {delta == null ? '—' : `${delta > 0 ? '+' : ''}${(delta * 100).toFixed(0)}%`}
          </span>
        </div>
      ))}
      {(panel as Panel & { why_custom?: string }).why_custom && (
        <div style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.5, borderTop: `1px solid ${t.border}`, paddingTop: 8 }}>
          {(panel as Panel & { why_custom?: string }).why_custom}
        </div>
      )}
    </div>
  );
}

// ── generic: a time series (line or bars) with event markers ─────────────────────────────────
function SeriesPanel({ panel, events }: { panel: Panel; events: NonNullable<DashboardPayload['events']> }) {
  const t = useLayoutTokens();
  const res = panel.results[panel.metric || ''];
  const rows = rowsOf(res);
  if (!rows.length) return <div style={{ fontSize: 12, color: t.textMuted }}>没有可画的行。</div>;
  const W = 520, H = 130, pad = { l: 44, r: 8, t: 8, b: 18 };
  const xs = rows.map(r => String(r[0]).slice(0, 10));
  const vals = rows.map(r => Number(r[1]));
  const max = Math.max(...vals, 0) || 1;
  const min = Math.min(...vals, 0);
  const step = (W - pad.l - pad.r) / Math.max(1, rows.length - (panel.render === 'bar' ? 0 : 1));
  const x = (i: number) => pad.l + (panel.render === 'bar' ? i * step + step / 2 : i * step);
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - (v - min) / (max - min || 1));
  const marks = (panel.marks || []).map(id => events.find(e => e.id === id)).filter(Boolean) as NonNullable<DashboardPayload['events']>;
  const markX = (at: string) => {
    const day = at.slice(0, 10);
    let idx = xs.findIndex(d => d >= day);
    if (idx < 0) idx = xs.length - 1;
    return x(idx);
  };
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke={t.border} />
        <text x={2} y={pad.t + 8} fontSize={9} fill={t.textDim}>{fmt(max, res?.unit)}</text>
        <text x={2} y={H - pad.b} fontSize={9} fill={t.textDim}>{fmt(min, res?.unit)}</text>
        {panel.render === 'bar'
          ? rows.map((_, i) => (
            <rect key={i} x={x(i) - Math.max(2, step * 0.32)} y={y(vals[i])}
              width={Math.max(4, step * 0.64)} height={Math.max(1, H - pad.b - y(vals[i]))}
              fill={`${CYAN}bb`} rx={2} />
          ))
          : (
            <polyline fill="none" stroke={CYAN} strokeWidth={2}
              points={rows.map((_, i) => `${x(i)},${y(vals[i])}`).join(' ')} />
          )}
        {panel.render !== 'bar' && rows.map((_, i) => (
          <circle key={i} cx={x(i)} cy={y(vals[i])} r={2.4} fill={CYAN} />
        ))}
        {marks.map(m => (
          <g key={m.id}>
            <line x1={markX(m.at)} y1={pad.t} x2={markX(m.at)} y2={H - pad.b} stroke={DANGER} strokeDasharray="3 3" strokeWidth={1} />
            <text x={markX(m.at) + 3} y={pad.t + 9} fontSize={8.5} fill={DANGER}>{m.label.split('：')[0]}</text>
          </g>
        ))}
        <text x={pad.l} y={H - 4} fontSize={8.5} fill={t.textDim}>{xs[0]}</text>
        <text x={W - pad.r} y={H - 4} fontSize={8.5} fill={t.textDim} textAnchor="end">{xs[xs.length - 1]}</text>
      </svg>
      {panel.expect && <div style={{ fontSize: 10.5, color: WARN, lineHeight: 1.5 }}>{panel.expect}</div>}
    </div>
  );
}

// ── generic: ranked dots (lollipop) — size = declared size_by, selection = highlight ─────────
function RankedPanel({
  panel, focus, onFocus, showAll, onToggleAll,
}: {
  panel: Panel; focus: string | null;
  onFocus: (key: string | null) => void; showAll: boolean; onToggleAll: () => void;
}) {
  const t = useLayoutTokens();
  const res = panel.results[panel.metric || ''];
  const sizes = panel.results[panel.size_by || ''];
  const sizeBy = new Map(rowsOf(sizes).map(r => [String(r[0]), Number(r[1])]));
  const all = rowsOf(res).map(r => ({ key: String(r[0]), value: Number(r[1]), size: sizeBy.get(String(r[0])) ?? 0 }));
  const sorted = panel.sort === 'asc'
    ? [...all].sort((a, b) => a.value - b.value)
    : [...all].sort((a, b) => b.value - a.value);
  const limit = panel.limit || 20;
  const shown = showAll ? sorted : sorted.slice(0, limit);
  const max = Math.max(...sorted.map(d => d.value), 0) || 1;
  const maxSize = Math.max(...sorted.map(d => d.size), 0) || 1;
  const W = 520, rowH = 16, H = shown.length * rowH + 8;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={Math.min(H, 400)} role="img">
        {shown.map((d, i) => {
          const yy = 6 + i * rowH;
          const w = (W - 96) * (d.value / max);
          const active = focus === d.key;
          const dim = focus !== null && !active;
          return (
            <g key={d.key} onClick={() => onFocus(active ? null : d.key)} style={{ cursor: 'pointer' }}>
              <rect x={0} y={yy - 6} width={W} height={rowH} fill={active ? `${INFO}18` : 'transparent'} />
              <text x={2} y={yy + 2} fontSize={9.5}
                fill={dim ? t.textDim : active ? INFO : t.textMuted}>
                {d.key}
              </text>
              <line x1={70} y1={yy} x2={70 + w} y2={yy} stroke={active ? INFO : `${CYAN}88`} strokeWidth={active ? 2 : 1.4} />
              <circle cx={70 + w} cy={yy} r={2 + 5 * Math.sqrt(d.size / maxSize)} fill={active ? INFO : CYAN} opacity={dim ? 0.3 : 0.9} />
              <text x={W} y={yy + 2} fontSize={9} textAnchor="end" style={mono}
                fill={dim ? t.textDim : active ? INFO : t.textPrimary}>
                {fmt(d.value, res?.unit)}
              </text>
            </g>
          );
        })}
      </svg>
      {all.length > limit && (
        <button onClick={onToggleAll} style={{ border: 'none', background: 'transparent', color: t.textMuted, fontSize: 11, cursor: 'pointer', padding: 0 }}>
          {showAll ? `只看前 ${limit}` : `展开全部 ${all.length} 个`} · 点大小 = {panel.results[panel.size_by || '']?.label || panel.size_by}
        </button>
      )}
      {panel.client_sort && (
        <div style={{ fontSize: 10.5, color: WARN, lineHeight: 1.5 }}>
          口径按值 DESC 编译；这张图要看最低端，所以由前端重排（声明里写了 client_sort）。
        </div>
      )}
    </div>
  );
}

// ── generic: a 2-key matrix, sized by a declared count ──────────────────────────────────────
function MatrixPanel({ panel }: { panel: Panel }) {
  const t = useLayoutTokens();
  const res = panel.results[panel.metric || ''];
  const sizes = new Map(rowsOf(panel.results[panel.size_by || '']).map(r => [`${r[0]}|${r[1]}`, Number(r[2])]));
  const cells = rowsOf(res).map(r => ({ r: String(r[0]), c: String(r[1]), v: Number(r[2]), n: sizes.get(`${r[0]}|${r[1]}`) ?? 0 }));
  const rowKeys = [...new Set(cells.map(c => c.r))];
  const colKeys = [...new Set(cells.map(c => c.c))];
  const max = Math.max(...cells.map(c => c.v), 0) || 1;
  const min = Math.min(...cells.map(c => c.v), 0);
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `72px repeat(${colKeys.length}, 1fr)`, gap: 6 }}>
      <span />
      {colKeys.map(c => <span key={c} style={{ fontSize: 10.5, color: t.textDim, textAlign: 'center' }}>{c}</span>)}
      {rowKeys.map(r => (
        <div key={r} style={{ display: 'contents' }}>
          <span style={{ fontSize: 11, color: t.textMuted }}>{r}</span>
          {colKeys.map(c => {
            const cell = cells.find(x => x.r === r && x.c === c);
            const share = cell ? (cell.v - min) / (max - min || 1) : 0;
            return (
              <div key={c} title={cell ? `${r} × ${c} = ${fmt(cell.v, res?.unit)}（${cell.n} 站）` : ''}
                style={{
                  borderRadius: 6, padding: '8px 4px', textAlign: 'center',
                  background: cell ? `${DANGER}${Math.round(18 + share * 110).toString(16).padStart(2, '0')}` : `${t.border}33`,
                }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.textPrimary, ...mono }}>
                  {cell ? fmt(cell.v, res?.unit) : '—'}
                </div>
                <div style={{ fontSize: 9.5, color: t.textDim }}>{cell ? `${cell.n.toLocaleString()} 站` : ''}</div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ── generic: composition — the NULL group is a group, and it is labelled ─────────────────────
function CompositionPanel({ panel }: { panel: Panel }) {
  const t = useLayoutTokens();
  const res = panel.results[panel.metric || ''];
  const rows = rowsOf(res).map(r => ({
    key: keyLabel(r[0], panel.null_label), value: r[1] === null ? null : Number(r[1]),
  }));
  const total = rows.reduce((s, r) => s + (r.value || 0), 0) || 1;
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {rows.map(r => (
        <div key={r.key}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: t.textMuted }}>
            <span>{r.key}</span>
            <span style={mono}>{r.value === null ? '无金额（NULL，不是 0）' : fmt(r.value, res?.unit)}</span>
          </div>
          <div style={{ height: 8, borderRadius: 4, background: `${t.border}55`, marginTop: 3 }}>
            <div style={{
              height: 8, borderRadius: 4, width: `${Math.max(2, ((r.value || 0) / total) * 100)}%`,
              background: r.key === panel.null_label ? DANGER : CYAN,
            }} />
          </div>
        </div>
      ))}
      {panel.note && <div style={{ fontSize: 10.5, color: t.textDim, lineHeight: 1.5 }}>{panel.note}</div>}
    </div>
  );
}

// ── custom view 2: dispatch review — what is measurable next to what is missing ──────────────
function DispatchPanel({ panel, verbs }: {
  panel: Panel; verbs: Array<{ name: string; parameters: string[] }>;
}) {
  const t = useLayoutTokens();
  const ontime = new Map(rowsOf(panel.results['stopOnTimeRateByVehicle']).map(r => [String(r[0]), Number(r[1])]));
  const points = rowsOf(panel.results['overloadRateByVehicle'])
    .map(r => ({ key: String(r[0]), overload: Number(r[1]), ontime: ontime.get(String(r[0])) }))
    .filter(p => p.ontime !== undefined) as Array<{ key: string; overload: number; ontime: number }>;
  const W = 280, H = 170, pad = 26;
  const ox = (v: number) => pad + (W - pad * 2) * v;
  const oy = (v: number) => H - pad - (H - pad * 2) * v;
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div style={{ fontSize: 11.5, color: DANGER, lineHeight: 1.6 }}>
        <AlertTriangle size={13} style={{ verticalAlign: -2, marginRight: 4 }} />
        {panel.missing}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <line x1={pad} y1={H - pad} x2={W - pad} y2={H - pad} stroke={t.border} />
        <line x1={pad} y1={pad} x2={pad} y2={H - pad} stroke={t.border} />
        {points.map(p => (
          <circle key={p.key} cx={ox(p.overload)} cy={oy(p.ontime)} r={2.6} fill={`${VIOLET}cc`}>
            <title>{p.key} · 超载率 {(p.overload * 100).toFixed(0)}% · 准时率 {(p.ontime * 100).toFixed(1)}%</title>
          </circle>
        ))}
        <text x={W / 2} y={H - 6} fontSize={9} fill={t.textDim} textAnchor="middle">超载率 →</text>
        <text x={6} y={pad} fontSize={9} fill={t.textDim}>准时率</text>
      </svg>
      <div style={{ fontSize: 10.5, color: t.textMuted, lineHeight: 1.5 }}>
        {panel.measurable_now?.note}
      </div>
      <div style={{
        borderTop: `1px solid ${t.border}`, paddingTop: 8, display: 'grid', gap: 4,
        fontSize: 10.5, color: t.textMuted, lineHeight: 1.55,
      }}>
        <span style={{ color: t.textPrimary, fontWeight: 700 }}>写回路径（已声明的动词）</span>
        {verbs.length === 0 ? (
          <span>这个本体没有声明任何写动词 —— 所以决策记录只能由外部 SQL 写入，而那正是不能接受的。</span>
        ) : verbs.map(v => (
          <div key={v.name} style={{ display: 'grid', gap: 2 }}>
            <span style={{ ...mono, color: CYAN }}>{v.name}</span>
            <span>参数：{(v.parameters || []).join(', ')}</span>
            <span>经 <span style={mono}>POST /api/ontology/{'{key}'}/actions/{v.name}</span> 执行：单事务 + audit_events 审计行；<span style={mono}>dry_run: true</span> 只报前置条件、不写。</span>
          </div>
        ))}
        <span style={{ color: WARN }}>
          还没有调度页把它当日常动作，所以覆盖率是 0 —— 缺的是录入入口，不是声明。
        </span>
      </div>
    </div>
  );
}

// ── the page ────────────────────────────────────────────────────────────────────────────────
export default function OntologyDashboardPage() {
  const t = useLayoutTokens();
  const navigate = useNavigate();
  const s = useOntology();
  const [data, setData] = useState<DashboardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [focus, setFocus] = useState<{ panel: string; key: string } | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // ONE filter, one dimension, one value (v1). Clicking the same value clears it; clicking another
  // replaces it. The panels are RECOMPILED server-side under it — this page never re-weights a rate.
  const [filter, setFilter] = useState<{ dimension: string; value: string } | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [verbs, setVerbs] = useState<Array<{ name: string; parameters: string[]; kind?: string }>>([]);
  // THIS ontology's board, and only this one.
  //
  // The page used to fall back to `profiles.find(p => p.url === s.url)` and, when the open ontology had
  // no `dashboard.json`, offer buttons that switched to another ontology's board ("这些本体的看板已经
  // 写好：打开 clinic"). Reported from the deployment: opening retail's Dashboard showed a different
  // ontology's page. A board is a declaration; an ontology without one has no board, and the page says
  // so instead of borrowing one.
  const key = s.preset || null;

  const load = useCallback(async (refresh = false) => {
    if (!key) return;
    setLoading(true); setError(null);
    try {
      const qs = new URLSearchParams();
      if (refresh) qs.set('refresh', 'true');
      if (filter) qs.set('filter', `${filter.dimension}:${filter.value}`);
      const res: any = await apiClient.get(
        `/api/ontology/${encodeURIComponent(key)}/dashboard/panels${qs.toString() ? `?${qs}` : ''}`,
        { timeout: 200000 });
      const payload = (res?.data ?? res) as DashboardPayload;
      setData(payload);
      if (payload?.error) setError(payload.error);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '看板取数失败');
    } finally {
      setLoading(false);
    }
  }, [key, filter]);

  useEffect(() => { void ontology.ensureReady().then(() => load(false)); }, [load]);

  // the WRITE side of this ontology: a declared verb, or nothing at all. A dashboard that shows a
  // 0-row decision log must be able to say whether a write path exists — and name it.
  useEffect(() => {
    if (!key) return;
    void (async () => {
      try {
        const res: any = await apiClient.get(`/api/ontology/${encodeURIComponent(key)}/actions`,
                                            { timeout: 60000 });
        const payload = res?.data ?? res;
        setVerbs(payload?.actions || []);
      } catch { setVerbs([]); }
    })();
  }, [key]);

  const unitOf = useCallback((metric?: string | null) => {
    const entry = metric ? (data?.metrics?.[metric] || null) : null;
    return { label: entry?.label ?? null, unit: entry?.unit ?? null };
  }, [data]);

  const events = data?.events || [];
  const panels = data?.panels || [];
  const focusKey = focus?.key || null;
  const copy = async (text: string, id: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(id); setTimeout(() => setCopied(null), 1600); } catch { /* clipboard denied */ }
  };

  return (
    <PageShell>
      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
      <Hero
        icon={BarChart3}
        title={data?.title || 'Ontology 看板'}
        subtitle={data?.subtitle || `声明式看板 —— 每个面板都是 ${key || '本体'} 的一项已声明指标`}
        actions={
          <>
            <Btn onClick={() => load(true)} disabled={loading}>
              <RefreshCw size={13} style={{ animation: loading ? 'lc-spin 1s linear infinite' : undefined, marginRight: 4 }} />
              重算
            </Btn>
          </>
        }
      >
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 11, color: t.textMuted }}>
          <Chip colour={INFO}>本体 {key || '—'}</Chip>
          {data && <Chip>{panels.length} 个面板</Chip>}
          {data && <Chip colour={DANGER}>{data.holes?.length || 0} 块空洞</Chip>}
          {data?.elapsed_ms != null && <span>{data.elapsed_ms} ms{data.cached ? ' · 缓存' : ''}</span>}
          {data?.declaration_stale && <Chip colour={DANGER}>声明已过期</Chip>}
          {events.map(e => (
            <span key={e.id} title={e.note} style={{ color: DANGER }}>◆ {e.at} {e.label}</span>
          ))}
        </div>
      </Hero>

      {/* the filter bar: the values are the DECLARED groups of the emitting panels, so a choice can
          only ever be one the ontology can answer; the count next to each is that group's row count. */}
      {data?.value_sets && Object.keys(data.value_sets).length > 0 && (
        <Card style={{ marginBottom: 16, padding: 12 }}>
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: t.textDim, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              交叉筛选
            </span>
            {Object.entries(data.value_sets).slice(0, 4).map(([dim, values]) => (
              <div key={dim} style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, color: t.textMuted, ...mono }}>{dim}</span>
                {values.slice(0, 8).map(v => {
                  const label = v === null ? '未判定' : String(v);
                  const active = filter?.dimension === dim && filter.value === label;
                  return (
                    <button
                      key={`${dim}-${label}`}
                      onClick={() => {
                        setFilter(active ? null : { dimension: dim, value: label });
                        void load(true);
                      }}
                      style={{
                        fontSize: 10.5, padding: '2px 8px', borderRadius: 999, cursor: 'pointer',
                        fontFamily: 'inherit', ...mono,
                        border: `1px solid ${active ? INFO : t.border}`,
                        background: active ? `${INFO}1f` : 'transparent',
                        color: active ? INFO : t.textMuted,
                      }}
                    >
                      {label}
                    </button>
                  );
                })}
                {values.length > 8 && (
                  <span style={{ fontSize: 10, color: t.textDim }}>+{values.length - 8}</span>
                )}
              </div>
            ))}
            {filter && (
              <Btn onClick={() => { setFilter(null); void load(true); }}>
                清除筛选
              </Btn>
            )}
          </div>
          {filter && (
            <div style={{ fontSize: 10.5, color: WARN, marginTop: 6, lineHeight: 1.5 }}>
              以下所有数字都在 <span style={mono}>{filter.dimension}={filter.value}</span> 下重新编译；
              不能按此维度切的视图会显示拒答，而不是留在未筛选的样子。
            </div>
          )}
        </Card>
      )}

      {error && (
        <Card style={{ marginBottom: 18, borderColor: `${DANGER}66` }}>
          <div style={{ fontSize: 12.5, color: DANGER, lineHeight: 1.6 }}>
            <AlertTriangle size={14} style={{ verticalAlign: -2, marginRight: 5 }} />
            {error}
          </div>
          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6, lineHeight: 1.7 }}>
            看板是一份声明（<span style={mono}>{key || '<ontology>'}/dashboard.json</span>）。没有声明就没有看板——这不是加载失败，
            也不会借另一个本体的看板来填满这一页。
          </div>
          <div style={{ marginTop: 10 }}>
            <Btn onClick={() => navigate('/ontology/browse')}>
              <Boxes size={13} style={{ marginRight: 4 }} />回到本体列表
            </Btn>
          </div>
        </Card>
      )}

      {loading && !data && <Card><div style={{ fontSize: 12, color: t.textMuted }}>编译并执行声明里的指标…</div></Card>}

      {data && (
        <>
          {data.briefing && <BriefingBlock briefing={data.briefing} />}

          <Section title="关键数" hint="每个数都来自一项声明；点开面板的「口径」能看到编译出的 SQL">
            <KpiStrip kpis={data.kpis || []} />
          </Section>

          <Section title="面板" hint="交叉高亮：点一个值，全页标出它；不会在浏览器里重算任何数">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: 14 }}>
              {panels.map(p => (
                <div key={p.id} style={{ gridColumn: ['slope', 'sankey', 'treemap', 'bubble'].includes(p.kind) ? 'span 2' : undefined }}>
                  <PanelFrame panel={p} tone={p.kind === 'hole' ? DANGER : undefined}>
                    {p.kind === 'slope' && <SlopePanel panel={p} />}
                    {p.kind === 'series' && <SeriesPanel panel={p} events={events} />}
                    {p.kind === 'ranked' && (
                      <RankedPanel
                        panel={p}
                        focus={p.emit_filter?.dimension === 'plate' ? (filter?.dimension === 'plate' ? filter.value : null) : null}
                        onFocus={k => {
                          setFocus(k ? { panel: p.id, key: k } : null);
                          if (p.emit_filter?.dimension === 'plate' && k) {
                            setFilter({ dimension: 'plate', value: k });
                            void load(true);
                          }
                        }}
                        showAll={!!expanded[p.id]}
                        onToggleAll={() => setExpanded(e => ({ ...e, [p.id]: !e[p.id] }))}
                      />
                    )}
                    {p.kind === 'matrix' && <MatrixPanel panel={p} />}
                    {p.kind === 'composition' && <CompositionPanel panel={p} />}
                    {p.kind === 'hole' && <DispatchPanel panel={p} verbs={verbs} />}
                    {p.kind === 'sankey' && <SankeyPanel panel={p} results={p.results} />}
                    {p.kind === 'bubble' && <BubblePanel panel={p} results={p.results} />}
                    {p.kind === 'treemap' && <TreemapPanel panel={p} results={p.results} />}
                    {p.kind === 'parallel' && <ParallelPanel panel={p} results={p.results} />}
                  </PanelFrame>
                </div>
              ))}
            </div>
          </Section>

          {focusKey && (
            <Card style={{ marginBottom: 18, padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 12 }}>
                <Chip colour={INFO}>已选 {focusKey}</Chip>
                <span style={{ color: t.textMuted }}>
                  它的数就在上面那张表的行里。跨面板按值过滤还没有声明——所以这里只做高亮，不改数。
                </span>
                <Btn onClick={() => copy(`按车辆看${panels.find(p => p.id === focus?.panel)?.title || ''}`, 'q')}>
                  <Copy size={12} style={{ marginRight: 4 }} />{copied === 'q' ? '已复制' : '复制问题'}
                </Btn>
                <Btn onClick={() => setFocus(null)}>清除</Btn>
              </div>
            </Card>
          )}

          <Section
            title="空洞"
            hint="这些指标拒绝回答，并说出缺的是哪条声明——空洞是结论，不是加载失败"
          >
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
              {(data.holes || []).map(h => (
                <Card key={h.metric} style={{ padding: 14, borderColor: `${DANGER}44` }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                    <AlertTriangle size={13} color={DANGER} />
                    <span style={{ fontSize: 12.5, fontWeight: 700, color: t.textPrimary }}>{h.label || h.metric}</span>
                    <Chip colour={h.status === 'refused' ? DANGER : WARN}>{h.status === 'refused' ? '拒答' : '已答（声明过期）'}</Chip>
                  </div>
                  <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.55, ...mono }}>{h.reason}</div>
                  {h.why && <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.55, marginTop: 6 }}>{h.why}</div>}
                </Card>
              ))}
              {(data.refused || []).map(r => (
                <Card key={r.metric} style={{ padding: 14, borderColor: `${DANGER}66` }}>
                  <div style={{ fontSize: 12.5, fontWeight: 700, color: DANGER, marginBottom: 6 }}>
                    未声明：{r.label || r.metric}
                  </div>
                  <div style={{ fontSize: 11, color: t.textMuted, ...mono }}>{r.refused}</div>
                </Card>
              ))}
            </div>
          </Section>

          <Section title="口径附注" hint="这张看板能画出来，靠的是本体的这些能力；其余的都还在空洞里">
            <Card style={{ padding: 14 }}>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11.5, color: t.textMuted, lineHeight: 1.8 }}>
                <li><Sigma size={12} style={{ verticalAlign: -2 }} /> 分组比率：分子分母同颗粒度才允许；跨颗粒度按名字拒绝。</li>
                <li><Route size={12} style={{ verticalAlign: -2 }} /> 时间轴：<span style={mono}>:timeBucket</span> 只用 grain 自己声明的 <span style={mono}>:timeColumn</span>；在手跳之外的按名字拒绝。</li>
                <li><Sparkles size={12} style={{ verticalAlign: -2 }} /> 每个面板都带编译出的 SQL 与 guard 报告；闸门 D1（<span style={mono}>check_dashboard.py</span>）验证分组值能加权回整体值，并跑独立 SQL 对照。</li>
              </ul>
            </Card>
          </Section>
        </>
      )}
      </div>

      {/* The business question lives here, next to the business numbers. Sticky so scrolling the
          panels never takes the input away. */}
      <div style={{ width: 360, flex: 'none', position: 'sticky', top: 0 }}>
        <DashboardChat ontologyKey={key} unitOf={unitOf} />
      </div>
      </div>
    </PageShell>
  );
}

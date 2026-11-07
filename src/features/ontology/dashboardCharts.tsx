/**
 * dashboardCharts — the panel kinds that need a layout algorithm, kept out of the page.
 *
 * The rule the whole dashboard is built on holds here too: **a chart never computes a value**. Every
 * number arrives already compiled by the ontology (`/api/ontology/{key}/dashboard/panels`); these
 * components only decide where to put it. That is why each of them takes `results` and a declaration,
 * never a formula.
 *
 *  · Sankey  — every band is ONE declared group value (`metric:key`). Nothing is summed to make a
 *              band; flow conservation is checked server-side by gate D8, so a chart that draws is a
 *              chart whose flows balance.
 *  · Bubble  — four declared channels (x / y / size / colour). An object missing a channel is drawn
 *              hollow and COUNTED in the footer, never silently dropped.
 *  · Treemap — 2-key grouped sum. A NULL group (unjudged liability) is a real cell: it is drawn grey
 *              and labelled "无金额", because drawing it as 0 would be the lie.
 *  · Parallel — 2+ scalar metrics side by side. No difference bar: subtracting two grains is not a
 *              declared operation yet.
 */
import { useMemo } from 'react';
import { sankey, sankeyLinkHorizontal, sankeyJustify } from 'd3-sankey';
import { hierarchy, treemap as d3treemap } from 'd3-hierarchy';
import { useLayoutTokens } from '../../components/layout2/tokens';
import { mono, DANGER, INFO, SUCCESS, VIOLET, WARN, CYAN } from './ui';

export interface ChartMetric {
  status: string;
  keys?: number;
  unit?: string | null;
  label?: string | null;
  rows?: Array<Array<string | number | boolean | null>>;
  refused?: string;
}

const fmtNum = (v: number | null | undefined, unit?: string | null): string => {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  if (unit === 'ratio') return `${(n * 100).toFixed(1)}%`;
  if (unit === 'money') return `¥${n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
  if (Math.abs(n - Math.round(n)) < 1e-9) return n.toLocaleString('zh-CN', { maximumFractionDigits: 0 });
  return n.toFixed(1);
};

/** One declared group value: `metric` + `key` (1 or 2 keys, "k1|k2", case-insensitive). */
function lookup(res: ChartMetric | undefined, key: string | null | undefined): number | null {
  if (!res || res.status !== 'ok' || !key) return null;
  const want = key.toLowerCase().split('|').map(s => s.trim());
  for (const row of res.rows || []) {
    const keys = row.slice(0, -1).map(k => (k === null ? 'null' : String(k).toLowerCase()));
    if (keys.length === want.length && keys.every((k, i) => k === want[i])) {
      return row[row.length - 1] as number;
    }
  }
  return null;
}

// ── Sankey ────────────────────────────────────────────────────────────────────────────────────
export function SankeyPanel({
  panel, results,
}: {
  panel: {
    nodes?: Array<{ id: string; label: string }>;
    links?: Array<{ from: string; to: string; metric: string; key: string }>;
    results?: Record<string, ChartMetric>;
  };
  results: Record<string, ChartMetric>;
}) {
  const t = useLayoutTokens();
  const W = 520, H = 260;
  const { nodes, links, missing } = useMemo(() => {
    const bad: string[] = [];
    const linksOut = (panel.links || []).map(l => {
      const value = lookup(panel.results?.[l.metric] || results[l.metric], l.key);
      if (value === null) bad.push(`${l.from}→${l.to} (${l.metric}:${l.key})`);
      return { source: l.from, target: l.to, value: value ?? 0 };
    }).filter(l => l.value > 0);
    return { nodes: panel.nodes || [], links: linksOut, missing: bad };
  }, [panel, results]);

  const layout = useMemo(() => {
    const gen = sankey()
      .nodeId((d: any) => d.id)
      .nodeWidth(12)
      .nodePadding(14)
      .nodeAlign(sankeyJustify)
      .extent([[8, 8], [W - 8, H - 8]]);
    try {
      return gen({ nodes: nodes.map(n => ({ ...n })), links: links.map(l => ({ ...l })) });
    } catch {
      return null;
    }
  }, [nodes, links]);

  if (!layout) {
    return <div style={{ fontSize: 11, color: WARN }}>流向画不出来（节点/链接不一致）。</div>;
  }
  const colorOf = (id: string) =>
    id.includes('late') || id === 'suburb' ? DANGER : id === 'ontime' || id === 'core' ? SUCCESS : CYAN;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        {layout.links.map((l: any, i: number) => (
          <path
            key={i}
            d={sankeyLinkHorizontal()(l) || ''}
            fill="none"
            stroke={colorOf(String(l.target.id))}
            strokeOpacity={0.28}
            strokeWidth={Math.max(1, l.width)}
          >
            <title>{`${l.source.label || l.source.id} → ${l.target.label || l.target.id}: ${l.value.toLocaleString()}`}</title>
          </path>
        ))}
        {layout.nodes.map((n: any, i: number) => (
          <g key={i}>
            <rect x={n.x0} y={n.y0} width={Math.max(2, n.x1 - n.x0)} height={Math.max(2, n.y1 - n.y0)}
              fill={colorOf(String(n.id))} rx={2} />
            <text x={n.x0 < W / 2 ? n.x1 + 5 : n.x0 - 5} y={(n.y0 + n.y1) / 2}
              fontSize={10} textAnchor={n.x0 < W / 2 ? 'start' : 'end'}
              fill={t.textPrimary}>
              {n.label || n.id} {Number(n.value || 0).toLocaleString()}
            </text>
          </g>
        ))}
      </svg>
      {missing.length > 0 && (
        <div style={{ fontSize: 10.5, color: DANGER, ...mono }}>
          这些股没有编译值，未绘制：{missing.join(' · ')}
        </div>
      )}
    </div>
  );
}

// ── Bubble ───────────────────────────────────────────────────────────────────────────────────
export function BubblePanel({
  panel, results,
}: {
  panel: {
    x?: string | { dimension?: string; order?: string[] };
    y?: string; size?: string; color?: string;
    color_labels?: Record<string, string>;
  };
  results: Record<string, ChartMetric>;
}) {
  const t = useLayoutTokens();
  const W = 520, H = 270, pad = { l: 46, r: 12, t: 12, b: 30 };
  const asName = (v: unknown) => (typeof v === 'string' ? v : undefined);
  const xs = asName(panel.x) ? results[asName(panel.x) as string] : undefined;
  const ys = asName(panel.y) ? results[asName(panel.y) as string] : undefined;
  const sz = asName(panel.size) ? results[asName(panel.size) as string] : undefined;
  const col = asName(panel.color) ? results[asName(panel.color) as string] : undefined;

  const colourOf = (key: string): string | null => {
    if (!col) return null;
    for (const row of col.rows || []) {
      if (String(row[0]) === key) return String(row[1]).toLowerCase() === 'true' ? INFO : VIOLET;
    }
    return null;
  };

  const points = useMemo(() => {
    const xBy = new Map((xs?.rows || []).map(r => [String(r[0]), Number(r[1])]));
    const yBy = new Map((ys?.rows || []).map(r => [String(r[0]), Number(r[1])]));
    const sBy = new Map((sz?.rows || []).map(r => [String(r[0]), Number(r[1])]));
    const all = [...xBy.keys()];
    return all.map(k => ({
      key: k,
      x: xBy.get(k),
      y: yBy.get(k),
      size: sBy.get(k) ?? null,
      colour: colourOf(k),
    }));
  }, [xs, ys, sz, col]);

  const complete = points.filter(p => p.x !== undefined && p.y !== undefined && p.size !== null);
  const gaps = points.length - complete.length;
  if (!complete.length) {
    return <div style={{ fontSize: 11, color: WARN }}>没有同时具备 x/y/size 的对象，气泡画不出来。</div>;
  }
  const xMin = Math.min(...complete.map(p => p.x as number)), xMax = Math.max(...complete.map(p => p.x as number));
  const yMin = Math.min(...complete.map(p => p.y as number)), yMax = Math.max(...complete.map(p => p.y as number));
  const sizeMax = Math.max(...complete.map(p => p.size as number), 1);
  const px = (v: number) => pad.l + (W - pad.l - pad.r) * ((v - xMin) / (xMax - xMin || 1));
  const py = (v: number) => H - pad.b - (H - pad.t - pad.b) * ((v - yMin) / (yMax - yMin || 1));

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        <line x1={pad.l} y1={H - pad.b} x2={W - pad.r} y2={H - pad.b} stroke={t.border} />
        <line x1={pad.l} y1={pad.t} x2={pad.l} y2={H - pad.b} stroke={t.border} />
        <text x={(W + pad.l) / 2} y={H - 8} fontSize={9} textAnchor="middle" fill={t.textDim}>
          {xs?.label || asName(panel.x) || 'x'} →
        </text>
        <text x={4} y={pad.t + 6} fontSize={9} fill={t.textDim}>{ys?.label || asName(panel.y) || 'y'}</text>
        {complete.map(p => {
          const r = 2 + 7 * Math.sqrt((p.size as number) / sizeMax);
          return (
            <circle
              key={p.key}
              cx={px(p.x as number)} cy={py(p.y as number)} r={r}
              fill={p.colour ? `${p.colour}aa` : `${CYAN}88`}
              stroke={p.colour || CYAN} strokeWidth={1}
            >
              <title>{`${p.key} · ${xs?.label || 'x'} ${fmtNum(p.x, xs?.unit)} · ${ys?.label || 'y'} ${fmtNum(p.y, ys?.unit)} · ${(p.size as number).toLocaleString()} 站`}</title>
            </circle>
          );
        })}
        <text x={pad.l} y={H - pad.b + 12} fontSize={8.5} fill={t.textDim}>{fmtNum(xMin, xs?.unit)}</text>
        <text x={W - pad.r} y={H - pad.b + 12} fontSize={8.5} textAnchor="end" fill={t.textDim}>{fmtNum(xMax, xs?.unit)}</text>
      </svg>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 10, color: t.textMuted }}>
        {panel.color_labels && Object.entries(panel.color_labels).map(([k, label]) => (
          <span key={k} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 7, height: 7, borderRadius: 4, background: k.toLowerCase() === 'true' ? INFO : VIOLET }} />
            {label}
          </span>
        ))}
        {gaps > 0 && (
          <span style={{ color: WARN }}>
            {gaps} 个对象缺通道未绘制（D9 要求这条数字可见）
          </span>
        )}
      </div>
    </div>
  );
}

// ── Treemap ─────────────────────────────────────────────────────────────────────────────────
export function TreemapPanel({
  panel, results,
}: {
  panel: { metric?: string; null_label?: string; row_label?: string; col_label?: string };
  results: Record<string, ChartMetric>;
}) {
  const t = useLayoutTokens();
  const res = panel.metric ? results[panel.metric] : undefined;
  const W = 520, H = 250;
  const cells = useMemo(() => (res?.rows || []).map(r => ({
    k1: r[0] === null ? (panel.null_label || '（未判定）') : String(r[0]),
    k2: r[1] === null ? '—' : String(r[1]),
    value: r[r.length - 1] === null ? null : Number(r[r.length - 1]),
  })), [res, panel.null_label]);

  const root = useMemo(() => {
    if (!cells.length) return null;
    const byTop = new Map<string, Array<{ k2: string; value: number | null }>>();
    cells.forEach(c => {
      const list = byTop.get(c.k1) || [];
      list.push({ k2: c.k2, value: c.value });
      byTop.set(c.k1, list);
    });
    return hierarchy({
      children: [...byTop.entries()].map(([k1, leaves]) => ({
        name: k1,
        children: leaves.map(l => ({ name: `${k1} · ${l.k2}`, value: l.value, nullValue: l.value === null })),
      })),
    })
      .sum((d: any) => (d.value === null || d.value === undefined ? 0 : d.value))
      .sort((a, b) => (b.value || 0) - (a.value || 0));
  }, [cells]);

  if (!root) return <div style={{ fontSize: 11, color: WARN }}>没有可画的格子。</div>;
  const laid = d3treemap().size([W, H]).paddingInner(3).paddingTop(14)(root as any);
  const colour = (name: string) =>
    name.includes(panel.null_label || '（未判定）') ? `${t.textDim}` :
    name.startsWith('driver') ? INFO : name.startsWith('labourer') ? VIOLET : CYAN;

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img">
        {(laid as any).descendants().filter((d: any) => d.depth === 1).map((d: any) => (
          <text key={`h-${d.data.name}`} x={d.x0 + 2} y={d.y0 - 3} fontSize={9.5} fill={t.textMuted}>
            {d.data.name}
          </text>
        ))}
        {(laid as any).leaves().map((d: any) => {
          const isNull = d.data.nullValue;
          const w = d.x1 - d.x0, h = d.y1 - d.y0;
          return (
            <g key={d.data.name}>
              <rect x={d.x0} y={d.y0} width={w} height={h} rx={3}
                fill={isNull ? `${t.border}` : `${colour(d.data.name)}cc`}
                stroke={isNull ? DANGER : 'none'} strokeDasharray={isNull ? '3 2' : undefined}
                strokeWidth={isNull ? 1 : 0}>
                <title>{`${d.data.name}: ${isNull ? '无金额（NULL）' : fmtNum(d.data.value, res?.unit)}`}</title>
              </rect>
              {w > 54 && h > 20 && (
                <text x={d.x0 + 4} y={d.y0 + 12} fontSize={9} fill={isNull ? DANGER : '#fff'}>
                  {isNull ? '无金额' : fmtNum(d.data.value, res?.unit)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div style={{ fontSize: 10, color: t.textDim }}>
        {panel.row_label || '行'} × {panel.col_label || '列'}；虚线灰块 = {panel.null_label || 'NULL 分组'}（不是 0）。
      </div>
    </div>
  );
}

// ── Parallel (no difference drawn) ───────────────────────────────────────────────────────────
export function ParallelPanel({
  panel, results,
}: {
  panel: { metrics?: string[] };
  results: Record<string, ChartMetric>;
}) {
  const t = useLayoutTokens();
  const rows = (panel.metrics || []).map(name => {
    const res = results[name];
    const value = res?.rows?.[0]?.[0];
    return { name, label: res?.label || name, unit: res?.unit, value: value === undefined ? null : Number(value) };
  });
  const max = Math.max(...rows.map(r => Math.abs(r.value || 0)), 1);
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {rows.map(r => (
        <div key={r.name}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: t.textMuted }}>
            <span>{r.label}</span>
            <span style={{ ...mono, color: t.textPrimary }}>{fmtNum(r.value, r.unit)}</span>
          </div>
          <div style={{ height: 10, borderRadius: 5, background: `${t.border}55`, marginTop: 3 }}>
            <div style={{
              height: 10, borderRadius: 5, width: `${Math.max(1, (Math.abs(r.value || 0) / max) * 100)}%`,
              background: r.name.toLowerCase().includes('claim') ? DANGER : SUCCESS,
            }} />
          </div>
        </div>
      ))}
      <div style={{ fontSize: 10.5, color: WARN, lineHeight: 1.5 }}>
        两块都是声明值；差值需要一种跨颗粒度四则运算，本体还没有——所以不画，也不在浏览器里减。
      </div>
    </div>
  );
}

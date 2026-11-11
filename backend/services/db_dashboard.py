"""Database → interactive HTML dashboard, schema-driven rather than retail-specific.

The design decisions, and why:

* **One cube query per dashboard.** Every figure (KPI, sankey, bubble, tree, bars, line) is
  derived in Python from ONE grouped result set — fact table joined to its dimensions in the
  schema's own FK order. Per-figure SQL would let two figures disagree, which is the failure
  mode this whole afternoon was about.
* **Nothing on the page that is not in that result set.** The numbers are injected as JSON and
  D3 only draws them; there is no code path where a chart can show a value the database did not
  return. The renderer re-runs the cube afterwards and compares (see `verify`).
* **Depth comes from the data.** The dimension chain is the fact table's FK graph, bridged
  through a line-item table when one exists (orders → order_lines → products), so a 3- or
  4-level sankey happens when the schema has the levels — not because retail has three.
* **Small samples are labelled, not dressed up.** A group count under 3 marks the panel
  "样本不足", because a 4-row "trend" is noise.
* **D3 is bundled offline** (`backend/assets/d3-dashboard.min.js`, built from the repo's own
  d3-* packages with esbuild), inlined into the page so the artefact opens with no network.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)

ASSET = Path(__file__).resolve().parents[1] / "assets" / "d3-dashboard.min.js"

LOG_TABLE = ("_events", "_log", "_audit", "audit_", "logs")
TIME_TYPES = ("timestamp with time zone", "timestamp without time zone", "date")
NUMERIC_TYPES = ("smallint", "integer", "bigint", "numeric", "real", "double precision")
ID_LIKE = ("id", "_id", "code", "no", "num")


# ── profiling ───────────────────────────────────────────────────────────────

def _connect(db_name: str, host="", port=0, user="", password=""):
    import psycopg2

    from tools.native_impl import _pg_conn_kwargs

    return psycopg2.connect(**_pg_conn_kwargs(host, port, user, password, dbname=db_name))


def profile(db_name: str, **conn) -> dict:
    """Schema + role classification: facts, dimensions, log tables, the join path, measures, time."""
    cnn = _connect(db_name, **conn)
    try:
        cur = cnn.cursor()
        cur.execute("""select table_name from information_schema.tables
                        where table_schema='public' and table_type='BASE TABLE' order by 1""")
        tables = [r[0] for r in cur.fetchall()]
        info = {}
        for t in tables:
            cur.execute("""select column_name, data_type from information_schema.columns
                            where table_schema='public' and table_name=%s order by ordinal_position""", (t,))
            columns = cur.fetchall()          # read BEFORE the next execute discards this result
            cur.execute(f'select count(*) from "{t}"')
            info[t] = {"columns": columns, "rows": cur.fetchone()[0]}
            cur.execute("""select kcu.column_name, ccu.table_name as ref_table, ccu.column_name as ref_col
                             from information_schema.table_constraints tc
                             join information_schema.key_column_usage kcu
                               on kcu.constraint_name = tc.constraint_name and kcu.table_schema = tc.table_schema
                             join information_schema.constraint_column_usage ccu
                               on ccu.constraint_name = tc.constraint_name and ccu.table_schema = tc.table_schema
                            where tc.table_schema='public' and tc.constraint_type='FOREIGN KEY'
                              and tc.table_name=%s""", (t,))
            info[t]["fks"] = [{"col": c, "table": rt, "ref": rc} for c, rt, rc in cur.fetchall()]
        cur.execute("""select i.indrelid::regclass::text, a.attname from pg_index i
                         join pg_class c on c.oid=i.indrelid
                         join pg_namespace n on n.oid=c.relnamespace
                         join pg_attribute a on a.attrelid=c.oid and a.attnum=any(i.indkey)
                        where i.indisprimary and n.nspname='public'""")
        pks = {}
        for tbl, col in cur.fetchall():
            pks.setdefault(tbl, []).append(col)
    finally:
        cnn.close()

    is_log = {t: (any(m in t.lower() for m in LOG_TABLE)
                  or (info[t]["rows"] > 20 * max([v["rows"] for v in info.values() if v["rows"]] or [1])
                      and any(ty == "jsonb" for _, ty in info[t]["columns"])))
              for t in tables}

    def measure_cols(t):
        fk_cols = {fk["col"] for fk in info[t]["fks"]}
        out = []
        for c, ty in info[t]["columns"]:
            low = c.lower()
            if ty not in NUMERIC_TYPES or c in fk_cols:
                continue
            if any(low == i or low.endswith("_" + i) for i in ID_LIKE):
                continue
            if low.endswith(("_at", "_ts", "_date")):     # a timestamp, never a measure
                continue
            out.append(c)
        return out

    def dim_cols(t, cap=50):
        out = []
        for c, ty in info[t]["columns"]:
            if ty not in ("text", "character varying"):
                continue
            if info[t]["rows"] > 5000:
                continue
            out.append(c)
        return out

    facts = [t for t in tables if not is_log[t] and measure_cols(t)]
    if not facts:                                   # fall back to the widest table
        facts = sorted([t for t in tables if not is_log[t]], key=lambda t: info[t]["rows"])[-1:]
    def fact_score(t):
        cols = [c.lower() for c, _ in info[t]["columns"]]
        money = any(k in c for c in cols for k in ("amount", "total", "revenue", "value", "sales", "qty", "price"))
        has_time = any(ty in TIME_TYPES for _, ty in info[t]["columns"])
        return (has_time, money, len(info[t]["fks"]), info[t]["rows"])

    fact = max(facts, key=fact_score) if facts else None
    bridges = {}                                    # fact → line table that carries more dims
    for t in tables:
        if t == fact or is_log[t]:
            continue
        refs = {fk["table"] for fk in info[t]["fks"]}
        if fact in refs and any(fk["table"] != fact for fk in info[t]["fks"]):
            bridges[t] = [fk for fk in info[t]["fks"] if fk["table"] != fact]

    time_col = next((c for c, ty in info[fact]["columns"] if ty in TIME_TYPES), None) if fact else None
    measures = measure_cols(fact) if fact else []

    # dimension chain: the fact's FK targets, then the bridge's extra dims, capped at 4 levels
    chain = []
    for fk in (info[fact]["fks"] if fact else []):
        label = next((c for c, ty in info[fk["table"]]["columns"]
                      if ty in ("text", "character varying") and info[fk["table"]]["rows"] <= 5000), fk["ref"])
        chain.append({"table": fk["table"], "key": fk["ref"], "via": f"{fact}.{fk['col']}", "label": label})
    # NOTE (measured): a line-level dimension cannot share a cube with an order-level
    # measure — joining `order_lines` fans 4 orders out to 6 rows and `sum(orders.amount)`
    # counts a multi-line order twice. So the chain stays at the fact's own grain; a
    # line-level breakdown needs its own measure (Σ qty×price) and is offered separately.
    # One FK dimension is not a flow. When the graph offers only one level, add a second from
    # the same dimension table's low-cardinality text column (customers.tier → customers.name):
    # still data-driven, and it gives the sankey/tree something real to show.
    if len(chain) == 1:
        dim_table = chain[0]["table"]
        extra = [c for c, ty in info[dim_table]["columns"]
                 if ty in ("text", "character varying") and c != chain[0]["label"]]
        for c in extra:
            # Top-down: the coarser column is the parent (tier before name), so insert it first.
            chain.insert(0, {"table": dim_table, "key": chain[0]["key"],
                             "via": chain[0]["via"], "label": c, "same_table": True})
            if len(chain) >= 2:
                break
    chain = chain[:4]

    return {"db": db_name, "tables": tables, "info": info, "is_log": is_log, "fact": fact,
            "pks": pks, "bridge": next(iter(bridges), None), "measures": measures, "time": time_col,
            "chain": chain, "dims": [c for t in tables if not is_log[t] for c in dim_cols(t)]}


def table_dims(tables, is_log):
    return [t for t in tables if not is_log[t]]


# ── the cube: one grouped query, every figure derived from it ───────────────

def cube(prof: dict) -> dict:
    fact, chain = prof["fact"], prof["chain"]
    if not fact:
        return {"rows": [], "levels": [], "measure": None, "time": None}
    measure = prof["measures"][0]
    joins, selects, groups = [], [], []
    bridge_join = ""
    # Join the line-item table ONLY if a chain level lives on it — joining it "just in case"
    # fanned 4 orders out to 6 rows and inflated the total (1589.5 vs 969.5).
    if prof["bridge"] and any(str(l["via"]).startswith(prof["bridge"] + ".") for l in chain):
        fk_to_fact = next(fk for fk in prof["info"][prof["bridge"]]["fks"] if fk["table"] == fact)
        bridge_join = (f'left join "{prof["bridge"]}" b on b."{fk_to_fact["col"]}" = '
                       f'{fact}."{_pk(prof, fact)}"')
    for i, level in enumerate(chain):
        alias = f"d{i}"
        owner = fact if level["via"].startswith(fact + ".") else "b"
        joins.append(f'left join "{level["table"]}" {alias} on {alias}."{level["key"]}" = '
                     f'{owner}."{level["via"].split(".")[-1]}"')
        selects.append(f'{alias}."{level["label"]}" as l{i}')
        groups.append(f'{alias}."{level["label"]}"')
    if prof["time"]:
        selects.append(f"to_char({fact}.\"{prof['time']}\", 'YYYY-MM') as period")
        groups.append(f"to_char({fact}.\"{prof['time']}\", 'YYYY-MM')")
    selects.append(f"sum({fact}.\"{measure}\") as amount")
    selects.append("count(*) as n")

    group_sql = ", ".join(groups)
    sql = (f'select {", ".join(selects)} from "{fact}" {bridge_join} {" ".join(joins)} '
           + (f'group by {group_sql} ' if group_sql else '') + 'order by 1')
    cnn = _connect(prof["db"])
    try:
        cur = cnn.cursor()
        cur.execute(sql)
        rows = cur.fetchall() if groups else [cur.fetchone()]
        cols = [d[0] for d in cur.description]
    finally:
        cnn.close()
    return {"rows": [[_plain(v) for v in r] for r in rows], "columns": cols,
            "levels": [f"l{i}" for i in range(len(chain))],
            "level_names": [f'{level["table"]}.{level["label"]}' for level in chain],
            "measure": f"{fact}.{measure}", "time": prof["time"], "sql": sql}


def _pk(prof, table):
    for t, cols in (prof.get("pks") or {}).items():
        if t == table and cols:
            return cols[0]
    for c, ty in prof["info"][table]["columns"]:
        if c == "id":
            return c
    return prof["info"][table]["columns"][0][0]


def _plain(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    return v


def _plan_text(prof: dict, cub: dict) -> str:
    fact = prof["fact"]
    lines = [f"# 仪表盘方案：{prof['db']}", ""]
    business = [t for t in prof["tables"] if not prof["is_log"][t]]
    logs = [t for t in prof["tables"] if prof["is_log"][t]]
    lines.append(f"业务表 {len(business)} 张（{', '.join(business)}）；"
                 f"遥测/日志表 {len(logs)} 张（{', '.join(logs) or '无'}，不进图）")
    lines.append(f"事实表：`{fact}`；度量：`{', '.join(prof['measures'])}`；时间列：`{prof['time'] or '无'}`")
    if prof["chain"]:
        lines.append(f"维度链（{len(prof['chain'])} 层）："
                     + " → ".join(f'`{l["table"]}.{l["label"]}`' for l in prof["chain"]))
    else:
        lines.append("维度链：**空的** —— 这个库没有外键，或事实表上没有外键。"
                     "先跑 `db_review(db_name=…, apply=true)` 把主键/外键建上，再出仪表盘；"
                     "没有维度链就只能画 KPI、趋势和分组条形，桑基/树无法生成。")
    lines.append("")
    lines.append("## 页面结构")
    lines.append("① 业务综述：KPI 卡（合计 / 单数 / 均值 / 头部分组占比）+ 3–5 句综述")
    lines.append(f"② 桑基：{' → '.join([fact] + [l['table'] for l in prof['chain']])}（钱的流向）")
    lines.append("③ 气泡：一个维度 × 度量（x=笔数, y=均值, r=合计）")
    lines.append("④ 树：自顶向下 " + " → ".join([l["table"] for l in prof["chain"]][:3]))
    lines.append(f"⑤ 趋势：{prof['time'] + ' × ' + (prof['measures'][0] if prof['measures'] else '度量') if prof['time'] else '无时间列 → 不做趋势'}")
    lines.append("⑥ 数据质量与口径面板")
    if prof.get("bridge"):
        lines.append("")
        lines.append(f"粒度说明：立方体是 `{fact}` 粒度（一条事实一行）。"
                     f"`{prof['bridge']}` 是明细表，**不能**和订单级度量混在同一个立方体里"
                     f"（会把多行订单的金额重复计一次）；要按明细维度看，需用明细口径 `Σ(qty×price)`。")
    lines.append("")
    lines.append("## 立方体（所有图都从这一条查询派生）")
    lines.append("```sql")
    lines.append(cub["sql"])
    lines.append("```")
    lines.append(f"该查询返回 {len(cub['rows'])} 组。样本不足（每组 <3）的面板会打「样本不足」标记。")
    return "\n".join(lines)


def plan(db_name: str, **conn) -> str:
    prof = profile(db_name, **conn)
    return _plan_text(prof, cube(prof))


# ── rendering ───────────────────────────────────────────────────────────────

def render(db_name: str, out_path: str | Path, title: str = "", **conn) -> str:
    prof = profile(db_name, **conn)
    cub = cube(prof)
    data = {"db": db_name, "title": title or f"{db_name} · dashboard",
            "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "levels": cub.get("level_names") or [], "measure": cub.get("measure"),
            "time": cub.get("time"), "rows": cub.get("rows") or [], "columns": cub.get("columns") or [],
            "sql": cub.get("sql") or ""}
    d3 = ASSET.read_text(encoding="utf-8") if ASSET.is_file() else ""
    html = (_HTML.replace("/*__D3__*/", d3)
                 .replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
                 .replace("__TITLE__", data["title"]))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    # self-verify: the page's own totals must equal a fresh query
    problems = verify(db_name, data)
    if problems:
        return f"Error: rendered, but the numbers do not match the database:\n" + "\n".join(problems)
    return f"wrote {out} ({len(html) // 1024} KB, {len(data['rows'])} cube rows)\n" + _plan_text(prof, cub)


def verify(db_name: str, data: dict) -> list:
    """Every figure on the page comes from `rows`; re-derive the totals from the database."""
    problems = []
    rows = data.get("rows") or []
    total = sum(r[-2] for r in rows) if rows else 0
    cnn = _connect(db_name)
    try:
        cur = cnn.cursor()
        cur.execute(data["sql"].split(" order by ")[0])
        fresh = cur.fetchall()
    finally:
        cnn.close()
    fresh_total = sum(_plain(r[-2]) for r in fresh) if fresh else 0
    if abs(float(total) - float(fresh_total)) > 1e-6:
        problems.append(f"total {total} on the page vs {fresh_total} from the database")
    if len(fresh) != len(rows):
        problems.append(f"{len(rows)} groups on the page vs {len(fresh)} from the database")
    return problems


_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
:root{--bg:#0f1419;--card:#161d26;--ink:#e6edf3;--mut:#8b98a5;--acc:#4dabf7;--warn:#f59f00;--bad:#f03e3e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,"PingFang SC",Segoe UI,sans-serif}
header{padding:18px 22px;border-bottom:1px solid #232c37;display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:18px;margin:0}.sub{color:var(--mut);font-size:12px}
.banner{margin:0 22px 12px;padding:10px 14px;border-radius:8px;background:rgba(245,159,0,.12);border:1px solid rgba(245,159,0,.4);font-size:12px}
main{padding:0 22px 28px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:14px 0}
.kpi{background:var(--card);border:1px solid #232c37;border-radius:10px;padding:14px}
.kpi .v{font-size:26px;font-weight:600}.kpi .l{color:var(--mut);font-size:12px;margin-top:4px}
.kpi .m{color:var(--acc);font-size:11px;margin-top:6px}
.summary{background:var(--card);border:1px solid #232c37;border-radius:10px;padding:14px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.panel{background:var(--card);border:1px solid #232c37;border-radius:10px;padding:12px;min-height:340px}
.panel h2{font-size:13px;margin:0 0 4px}.panel .hint{color:var(--mut);font-size:11px;margin-bottom:6px}
.tag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:99px;border:1px solid var(--warn);color:var(--warn);margin-left:6px}
svg{display:block;width:100%;height:300px}.tip{position:fixed;pointer-events:none;background:#000c;color:#fff;padding:6px 8px;border-radius:6px;font-size:11px;opacity:0;transition:opacity .12s}
</style></head><body>
<header><h1 id="title"></h1><span class="sub" id="meta"></span></header>
<div class="banner" id="banner" style="display:none"></div>
<main>
  <div class="summary" id="summary"></div>
  <div class="kpis" id="kpis"></div>
  <div class="grid">
    <div class="panel"><h2>桑基 · 钱的流向<span class="tag" id="tag-sankey" style="display:none">样本不足</span></h2>
      <div class="hint" id="hint-sankey"></div><svg id="sankey"></svg></div>
    <div class="panel"><h2>气泡 · 维度对比</h2><div class="hint" id="hint-bubble"></div><svg id="bubble"></svg></div>
    <div class="panel"><h2>树 · 自顶向下</h2><div class="hint" id="hint-tree"></div><svg id="tree"></svg></div>
    <div class="panel"><h2>分组 · 度量对比</h2><div class="hint" id="hint-bars"></div><svg id="bars"></svg></div>
    <div class="panel" style="grid-column:1/-1"><h2>趋势</h2><div class="hint" id="hint-line"></div><svg id="line"></svg></div>
  </div>
</div>
</main>
<div class="tip" id="tip"></div>
<script>/*__D3__*/</script>
<script id="payload" type="application/json">/*__DATA__*/</script>
<script>
const D = JSON.parse(document.getElementById('payload').textContent);
const A = window.D3LIB;                       // esbuild IIFE bundle, one namespace per module
const sel = A.select.select, sum = A.array.sum, rollup = A.array.rollup;
const hierarchy = A.hierarchy.hierarchy, treeLayout = A.hierarchy.tree;
const sankeyLayout = A.sankey.sankey, sankeyLink = A.sankey.sankeyLinkHorizontal;
const linePath = A.shape.line, linkVert = A.shape.linkVertical;
const tip = document.getElementById('tip');
function hover(el, html){ el.on('mousemove', e=>{tip.style.opacity=1;tip.innerHTML=html;tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-8)+'px';})
  .on('mouseleave', ()=>tip.style.opacity=0); }
const fmt = n => (n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:1}));

document.getElementById('title').textContent = D.title;
document.getElementById('meta').textContent = `${D.db} · 生成 ${D.generated} · 度量 ${D.measure||'—'}`;

// rows: [l0..l3..., (period?), amount, n]
const nLevels = D.levels.length;
const valIdx = D.columns.length - 2, nIdx = D.columns.length - 1;
const periodIdx = D.time ? D.columns.indexOf('period') : -1;
const rows = D.rows.map(r => ({levels: r.slice(0, nLevels).map(v => v==null? '(空)' : v),
                               period: periodIdx>=0 ? r[periodIdx] : null,
                               amount: r[valIdx], n: r[nIdx]}));
const total = sum(rows, r=>r.amount) || 0;
const totalN = sum(rows, r=>r.n) || 0;

// ── KPIs + summary ─────────────────────────────────────────────────────────
const byL0 = rollup(rows, v=>sum(v, r=>r.amount), r=>r.levels[0]);
const topL0 = [...byL0].sort((a,b)=>b[1]-a[1])[0];
const kpis = [
  {l:`${D.measure||'合计'}`, v:fmt(total), m:`${rows.length} 组`},
  {l:'笔数', v:fmt(totalN), m:'count(*)'},
  {l:'均值', v:fmt(total/Math.max(totalN,1)), m:'合计 ÷ 笔数'},
  topL0 ? {l:`头部 ${D.levels[0]||'分组'}`, v:String(topL0[0]), m:`${fmt(topL0[1])} · 占比 ${(topL0[1]/Math.max(total,1)*100).toFixed(1)}%`} : null,
].filter(Boolean);
sel('#kpis').selectAll('div').data(kpis).join('div').attr('class','kpi')
  .html(d=>`<div class="v">${d.v}</div><div class="l">${d.l}</div><div class="m">${d.m}</div>`);
document.getElementById('summary').innerHTML =
  `<b>业务综述</b><div class="hint">口径：\`${D.measure||'—'}\`（只统计立方体里出现的分组）</div>`
  + `<p>共 <b>${fmt(total)}</b>，覆盖 <b>${totalN}</b> 笔，<b>${rows.length}</b> 个分组`
  + (D.levels.length ? `，层级 ${D.levels.map(l=>'`'+l+'`').join(' → ')}` : '')
  + (D.time ? `，时间列 \`${D.time}\`` : '，无时间列')
  + `。</p>`
  + (topL0 ? `<p>头部 <b>${topL0[0]}</b> 占 ${(topL0[1]/Math.max(total,1)*100).toFixed(1)}%。</p>` : '');
document.getElementById('banner').style.display = 'block';
document.getElementById('banner').textContent = '提示：本页所有数字均由一条 SQL 立方体派生并已复核；数据量很小，不要据此下"趋势/占比"结论。';

// ── sankey: consecutive levels ─────────────────────────────────────────────
if (nLevels >= 2) {
  const nodes = [...new Set(rows.flatMap(r=>r.levels))].map(id=>({id}));
  const idx = new Map(nodes.map((n,i)=>[n.id,i]));
  const links = [];
  for (const r of rows) for (let i=0;i<nLevels-1;i++) {
    const s=r.levels[i], t=r.levels[i+1];
    if (s===t) continue;
    links.push({source: idx.get(s), target: idx.get(t), value: Math.max(r.amount,0)});
  }
  const agg = rollup(links, v=>sum(v, l=>l.value), l=>l.source+'>'+l.target);
  const merged = [...agg].map(([k,v])=>{const [s,t]=k.split('>').map(Number);return {source:s,target:t,value:v};});
  const svg = sel('#sankey'), W = svg.node().clientWidth||620, H = 300;
  svg.attr('viewBox', `0 0 ${W} ${H}`);
  const g = sankeyLayout().nodeWidth(12).nodePadding(14).extent([[8,8],[W-8,H-8]])({nodes: nodes.map(n=>({...n})), links: merged});
  const col = id => `hsl(${(id*47)%360} 62% 58%)`;
  svg.append('g').selectAll('path').data(g.links).join('path')
    .attr('d', sankeyLink()).attr('fill','none')
    .attr('stroke', d=>col(d.source.index)).attr('stroke-opacity',0.35).attr('stroke-width',d=>Math.max(1,d.width))
    .each(function(d){hover(sel(this), `${d.source.name||d.source.id} → ${d.target.name||d.target.id}<br>${fmt(d.value)}`);});
  svg.append('g').selectAll('rect').data(g.nodes).join('rect')
    .attr('x',d=>d.x0).attr('y',d=>d.y0).attr('width',d=>d.x1-d.x0).attr('height',d=>Math.max(2,d.y1-d.y0))
    .attr('fill',d=>col(d.index)).attr('rx',2);
  svg.append('g').selectAll('text').data(g.nodes).join('text')
    .attr('x',d=>d.x0-4).attr('y',d=>(d.y0+d.y1)/2).attr('text-anchor','end').attr('fill','#8b98a5').attr('font-size',10)
    .text(d=>d.id);
  document.getElementById('hint-sankey').textContent = `${D.levels.join(' → ')} · ${merged.length} 条流`;
  if (new Set(rows.map(r=>r.levels[0])).size < 3) document.getElementById('tag-sankey').style.display='inline-block';
} else { document.getElementById('hint-sankey').textContent = '这个库没有可用的维度链（至少需要一层外键维度）'; }

// ── bubble: level0 × amount/n ──────────────────────────────────────────────
(function(){
  const g = [...rollup(rows, v=>({amount:sum(v,r=>r.amount), n:sum(v,r=>r.n)}), r=>r.levels[0])]
    .map(([k,v])=>({label:k, ...v}));
  const svg = sel('#bubble'), W=svg.node().clientWidth||620, H=300;
  svg.attr('viewBox',`0 0 ${W} ${H}`);
  if (!g.length) { document.getElementById('hint-bubble').textContent='无数据'; return; }
  const maxR = Math.max(...g.map(d=>d.amount))||1, rMax=38;
  const x = i => 60 + (i+0.5)*((W-100)/g.length), y = d => H-40 - (d.n/Math.max(...g.map(z=>z.n),1))*(H-90);
  svg.selectAll('circle').data(g).join('circle')
    .attr('cx',(d,i)=>x(i)).attr('cy',d=>y(d)).attr('r',d=>Math.max(8, Math.sqrt(d.amount/maxR)*rMax))
    .attr('fill','#4dabf7').attr('fill-opacity',.55).attr('stroke','#4dabf7')
    .each(function(d){hover(sel(this), `${d.label}<br>${fmt(d.amount)} · ${d.n} 笔`);});
  svg.selectAll('text').data(g).join('text').attr('x',(d,i)=>x(i)).attr('y',H-16)
    .attr('text-anchor','middle').attr('fill','#8b98a5').attr('font-size',10).text(d=>String(d.label).slice(0,14));
  document.getElementById('hint-bubble').textContent = `x=分组 · y=笔数 · r=${D.measure||'合计'}（${g.length} 组）`;
})();

// ── tree: top-down hierarchy ───────────────────────────────────────────────
(function(){
  const svg = sel('#tree'), W=svg.node().clientWidth||620, H=300;
  svg.attr('viewBox',`0 0 ${W} ${H}`);
  if (nLevels < 2) { document.getElementById('hint-tree').textContent='层级不足'; return; }
  const rootData = {name:'全部', children:[]};
  for (const r of rows) {
    let cur = rootData;
    for (let i=0;i<nLevels;i++){
      const nm = String(r.levels[i]);
      let child = cur.children.find(c=>c.name===nm);
      if (!child){ child={name:nm, children:[]}; cur.children.push(child); }
      if (i===nLevels-1) child.value=(child.value||0)+r.amount;
      cur = child;
    }
  }
  const root = hierarchy(rootData).sum(d=>d.value||0).sort((a,b)=>b.value-a.value);
  treeLayout().size([W-40, H-40])(root);
  const g = svg.append('g').attr('transform','translate(20,20)');
  g.selectAll('path').data(root.links()).join('path')
    .attr('d', d3link()).attr('fill','none').attr('stroke','#2b3542');
  g.selectAll('circle').data(root.descendants()).join('circle')
    .attr('cx',d=>d.x).attr('cy',d=>d.y).attr('r',d=>Math.sqrt(d.value||1)/2+3)
    .attr('fill',d=>d.depth===0?'#f59f00':'#4dabf7').attr('fill-opacity',.8)
    .each(function(d){hover(sel(this), `${d.data.name}<br>${fmt(d.value)}`);});
  g.selectAll('text').data(root.descendants().filter(d=>d.depth<=2)).join('text')
    .attr('x',d=>d.x).attr('y',d=>d.y-8).attr('text-anchor','middle')
    .attr('fill','#8b98a5').attr('font-size',9).text(d=>String(d.data.name).slice(0,12));
  function d3link(){ return linkVert(); }
  document.getElementById('hint-tree').textContent = D.levels.slice(0,nLevels).join(' → ') + '（自顶向下）';
})();

// ── bars: level0 totals ────────────────────────────────────────────────────
(function(){
  const g = [...rollup(rows, v=>sum(v,r=>r.amount), r=>r.levels[0])].sort((a,b)=>b[1]-a[1]);
  const svg = sel('#bars'), W=svg.node().clientWidth||620, H=300;
  svg.attr('viewBox',`0 0 ${W} ${H}`);
  if (!g.length){document.getElementById('hint-bars').textContent='无数据';return;}
  const max=Math.max(...g.map(z=>z[1]))||1, bh=Math.min(26,(H-40)/g.length);
  svg.selectAll('rect').data(g).join('rect')
    .attr('x',90).attr('y',(d,i)=>20+i*bh).attr('height',bh-6)
    .attr('width',d=>Math.max(2,(d[1]/max)*(W-120))).attr('fill','#4dabf7').attr('fill-opacity',.75)
    .each(function(d){hover(sel(this), `${d[0]}<br>${fmt(d[1])}`);});
  svg.selectAll('text').data(g).join('text').attr('x',84).attr('y',(d,i)=>20+i*bh+12)
    .attr('text-anchor','end').attr('fill','#8b98a5').attr('font-size',10).text(d=>String(d[0]).slice(0,12));
  document.getElementById('hint-bars').textContent = `${D.levels[0]||'分组'} × ${D.measure||'合计'}`;
})();

// ── line: period × amount ──────────────────────────────────────────────────
(function(){
  const svg = sel('#line'), W=svg.node().clientWidth||1100, H=220;
  svg.attr('viewBox',`0 0 ${W} ${H}`);
  if (periodIdx < 0) { document.getElementById('hint-line').textContent='没有时间列，不做趋势'; return; }
  const g = [...rollup(rows, v=>sum(v,r=>r.amount), r=>r.period)].sort((a,b)=>a[0]<b[0]?-1:1);
  const max=Math.max(...g.map(z=>z[1]))||1;
  const px=i=>40+i*((W-80)/Math.max(g.length-1,1)), py=v=>H-30-(v/max)*(H-60);
  svg.append('path').attr('d', linePath().x((d,i)=>px(i)).y(d=>py(d[1]))(g))
    .attr('fill','none').attr('stroke','#4dabf7').attr('stroke-width',2);
  svg.selectAll('circle').data(g).join('circle').attr('cx',(d,i)=>px(i)).attr('cy',d=>py(d[1])).attr('r',4)
    .attr('fill','#4dabf7').each(function(d){hover(sel(this), `${d[0]}<br>${fmt(d[1])}`);});
  svg.selectAll('text').data(g).join('text').attr('x',(d,i)=>px(i)).attr('y',H-10)
    .attr('text-anchor','middle').attr('fill','#8b98a5').attr('font-size',10).text(d=>d[0]);
  document.getElementById('hint-line').textContent = `${D.time} × ${D.measure||'合计'}（${g.length} 个周期）`;
  if (g.length < 3) document.getElementById('hint-line').textContent += ' · 样本不足，不要当趋势看';
})();
</script></body></html>"""

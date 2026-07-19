"""
Generate ALL Sun Hing executive dashboards from the SQLite database.

Produces:
  - sunhing_dashboard.html         — main hub (executive cockpit)
  - sunhing_dashboard_profit.html  — 净利润率 (KPI 01-09)
  - sunhing_dashboard_turnover.html  — 资产周转率 (KPI 10-13)
  - sunhing_dashboard_leverage.html  — 权益乘数 (KPI 14-17)
  - sunhing_dashboard_support.html   — 支撑层 (KPI 18-21)
  - sunhing_dashboard_risk.html      — 风险监控 (RS01-RS07)

All follow the visual language of the ROE KPI simulator
(ROE_KPI_模拟器.html) while rendering live metrics from SQLite.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DB_PATH = Path(__file__).parent / "sunhing_kpi.db"
OUTPUT_DIR = Path(__file__).parent
DB_META_PATH = "data/analysis_dbs/sunhing_kpi.db"

DASHBOARD_META = {
    "db": DB_META_PATH,
    "skills": "sunhing-analyst",
    "mode": "static-embed",
    "entry": "hub",
    "title": "Sun Hing ROE Executive Dashboard",
    "study": "sunhing-transformation",
}

LOWER_IS_BETTER = {
    "03_赔偿金额预算控制率",
    "04_劳动仲裁与诉讼事件数",
    "16_新架构集团权益乘数",
    "20_重大风险事件发生率",
    "RS01_协商减员纠纷发生率",
    "RS03_群体性劳动争议风险指数",
    "RS05_海关违规/罚款金额",
    "RS06_核心技术骨干流失率(变革期)",
    "RS07_客户订单转移/流失率",
}

FACTOR_META = {
    "净利润率": {
        "short": "净利润率",
        "card_class": "npm",
        "header_class": "npm",
        "accent": "#006600",
        "summary": "成本与盈利修复",
        "link": "/api/files/sunhing_dashboard_profit.html",
        "link_label": "查看 Profit Dashboard",
    },
    "资产周转率": {
        "short": "资产周转率",
        "card_class": "at",
        "header_class": "at",
        "accent": "#1F4E79",
        "summary": "轻资产与数字化周转",
        "link": "/api/files/sunhing_dashboard_turnover.html",
        "link_label": "查看 Turnover Dashboard",
    },
    "权益乘数": {
        "short": "权益乘数",
        "card_class": "em",
        "header_class": "em",
        "accent": "#5B2C6F",
        "summary": "股权重组与协同放大",
        "link": "/api/files/sunhing_dashboard_leverage.html",
        "link_label": "查看 Leverage Dashboard",
    },
    "支撑层": {
        "short": "支撑层",
        "card_class": "sup",
        "header_class": "sup",
        "accent": "#C65911",
        "summary": "人才、PMO 与落地保障",
        "link": "/api/files/sunhing_dashboard_support.html",
        "link_label": "查看 Support Dashboard",
    },
    "风险监控": {
        "short": "风险监控",
        "card_class": "risk",
        "header_class": "risk",
        "accent": "#7A1F1F",
        "summary": "关键预警与收口风险",
        "link": "/api/files/sunhing_dashboard_risk.html",
        "link_label": "查看 Risk Dashboard",
    },
}

# ── Shared CSS for sub-dashboards ──────────────────────────────────────

SUB_CSS = """
  :root {
    --navy: #0B2344;
    --navy-mid: #1A3A5C;
    --gold: #B5935A;
    --gold-light: #D4AF70;
    --slate: #4A5568;
    --mid-grey: #718096;
    --light-grey: #E2E8F0;
    --body: #1A202C;
    --green: #00B050;
    --orange: #FFC000;
    --red: #FF5050;
    --dark-green: #006600;
    --dark-blue: #1F4E79;
    --dark-purple: #5B2C6F;
    --dark-orange: #C65911;
    --dark-red: #7A1F1F;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 0 0 40px 0;
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    background: #f0f2f5;
    color: var(--body);
    line-height: 1.5;
  }
  .header {
    background: var(--navy);
    color: white;
    padding: 18px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }
  .header h1 { font-size: 20px; font-weight: 700; margin: 0; }
  .header .sub { font-size: 13px; color: var(--gold-light); }
  .baseline-bar {
    background: var(--navy-mid);
    color: white;
    padding: 10px 24px;
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    font-size: 13px;
  }
  .baseline-bar span { color: var(--gold-light); }
  .container {
    max-width: 1320px;
    margin: 20px auto;
    padding: 0 16px;
  }
  .nav-links {
    display: flex;
    gap: 10px;
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .nav-links a {
    background: #fff;
    color: var(--slate);
    text-decoration: none;
    padding: 10px 16px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }
  .nav-links a:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
  .nav-links a.active {
    background: var(--navy);
    color: white;
  }
  .page-title {
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 4px;
  }
  .page-subtitle {
    color: #666;
    font-size: 13px;
    margin-bottom: 20px;
  }
  .kpi-row, .summary {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 14px;
    margin-bottom: 18px;
  }
  .kpi-card, .summary-card, .card, .insight-box {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }
  .kpi-card, .summary-card { padding: 16px; border-left: 4px solid #1f77b4; }
  .kpi-card .label, .summary-card .label {
    font-size: 11px;
    color: #7f8c8d;
    text-transform: uppercase;
    letter-spacing: .5px;
  }
  .kpi-card .value, .summary-card .value {
    font-size: 24px;
    font-weight: 700;
    margin: 4px 0 2px;
  }
  .kpi-card .note, .summary-card .note {
    font-size: 12px;
    color: #999;
  }
  .kpi-card.ok, .summary-card.ok { border-left-color: #2ca02c; }
  .kpi-card.warn, .summary-card.warn { border-left-color: #ff7f0e; }
  .kpi-card.danger, .summary-card.danger { border-left-color: #e74c3c; }
  .card { padding: 14px 16px; margin-bottom: 16px; }
  .chart-title {
    font-size: 13px;
    font-weight: 600;
    margin-bottom: 6px;
    color: #2c3e50;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
  .grid .full { grid-column: 1 / -1; }
  .chart { width: 100%; height: 300px; }
  .kpi-table, table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    background: #fff;
  }
  .kpi-table th, table th {
    text-align: left;
    padding: 8px 10px;
    background: #f8f9fa;
    border-bottom: 2px solid #eee;
    font-weight: 600;
    white-space: nowrap;
  }
  .kpi-table td, table td {
    padding: 7px 10px;
    border-bottom: 1px solid #f0f0f0;
  }
  .kpi-table .met { color: #2ca02c; font-weight: 600; }
  .kpi-table .miss { color: #e74c3c; font-weight: 600; }
  .kpi-table .safe { color: #2ca02c; font-weight: 600; }
  .kpi-table .warn { color: #e74c3c; font-weight: 600; }
  .insight-box { padding: 16px 20px; border-left: 4px solid #2ca02c; }
  .insight-box h3 { margin: 0 0 8px; font-size: 14px; color: var(--navy); }
  .insight-box ul { margin: 0; padding-left: 18px; font-size: 13px; color: #333; }
  .insight-box li { margin: 4px 0; }
  @media (max-width: 1100px) {
    .kpi-row, .summary { grid-template-columns: repeat(2, 1fr); }
    .grid { grid-template-columns: 1fr; }
  }
  @media (max-width: 640px) {
    .kpi-row, .summary { grid-template-columns: 1fr; }
  }
"""

# ── Sub-dashboard definitions ─────────────────────────────────────────
# Each entry: (filename, title_en, title_cn, subtitle, factor_key, kpi_ids, header_class, accent_color)

SUB_DASHBOARDS = [
    {
        "filename": "sunhing_dashboard_profit.html",
        "title_en": "Profit Factor Dashboard",
        "title_cn": "净利润率 Factor Dashboard",
        "subtitle": "净利润率因子看板 · KPI 01-09 执行与盈利修复",
        "icon": "📈",
        "baseline_label": "净利润率 / 利润修复",
        "factor_key": "净利润率",
        "kpi_prefix": None,  # all KPIs for this factor
        "header_class": "npm",
        "accent": "#006600",
        "active_nav": "Profit",
    },
    {
        "filename": "sunhing_dashboard_turnover.html",
        "title_en": "Turnover Factor Dashboard",
        "title_cn": "资产周转率 Factor Dashboard",
        "subtitle": "资产周转率因子看板 · KPI 10-13 轻资产与周转效率",
        "icon": "🔄",
        "baseline_label": "资产周转率 / 轻资产化",
        "factor_key": "资产周转率",
        "kpi_prefix": None,
        "header_class": "at",
        "accent": "#1F4E79",
        "active_nav": "Turnover",
    },
    {
        "filename": "sunhing_dashboard_leverage.html",
        "title_en": "Leverage Factor Dashboard",
        "title_cn": "权益乘数 Factor Dashboard",
        "subtitle": "权益乘数因子看板 · KPI 14-17 资本结构与协同放大",
        "icon": "🏗️",
        "baseline_label": "权益乘数 / 架构重组",
        "factor_key": "权益乘数",
        "kpi_prefix": None,
        "header_class": "em",
        "accent": "#5B2C6F",
        "active_nav": "Leverage",
    },
    {
        "filename": "sunhing_dashboard_support.html",
        "title_en": "Support Factor Dashboard",
        "title_cn": "支撑层 Factor Dashboard",
        "subtitle": "支撑层看板 · KPI 18-21 人才、PMO 与制度落地",
        "icon": "🛡️",
        "baseline_label": "支撑层 / 执行保障",
        "factor_key": "支撑层",
        "kpi_prefix": None,
        "header_class": "sup",
        "accent": "#C65911",
        "active_nav": "Support",
    },
    {
        "filename": "sunhing_dashboard_risk.html",
        "title_en": "Risk Monitoring Dashboard",
        "title_cn": "风险监控 Dashboard",
        "subtitle": "风险监控看板 · RS01-RS07 预警阈值与收口动作",
        "icon": "⚠️",
        "baseline_label": "风险监控 / 预警",
        "factor_key": "风险监控",
        "kpi_prefix": "RS",
        "header_class": "risk",
        "accent": "#7A1F1F",
        "active_nav": "Risk",
    },
]

# Chart color mapping per KPI index (cycling)
CHART_COLORS = ["#2ca02c", "#1f77b4", "#ff7f0e", "#9467bd", "#e74c3c", "#17becf"]


# ── Helpers ────────────────────────────────────────────────────────────

def is_lower_better(kpi_id: str) -> bool:
    return kpi_id in LOWER_IS_BETTER


def calc_score(actual: float, target: float, kpi_id: str) -> float:
    if target == 0:
        return 100.0 if actual == 0 else 0.0
    if is_lower_better(kpi_id):
        if actual <= 0:
            return 100.0
        return max(0.0, min(100.0, target * 100.0 / actual))
    return max(0.0, min(100.0, actual * 100.0 / target))


def is_met(actual: float, target: float, kpi_id: str) -> bool:
    if target == 0:
        return actual == 0
    if is_lower_better(kpi_id):
        return actual <= target
    return actual >= target


def clean_name(name: str) -> str:
    return name.lstrip("_")


def format_value(value: float, unit: str) -> str:
    if unit in {"%", "score(0-100)"}:
        return f"{value:.1f}%"
    if unit == "score(1-10)":
        return f"{value:.1f}"
    if unit == "ratio":
        return f"{value:.2f}x"
    if unit in {"events", "points"}:
        return f"{value:.0f}"
    if unit in {"万元", "万"}:
        return f"{value:.1f}万"
    if float(value).is_integer():
        return f"{value:.0f}"
    return f"{value:.1f}"


def format_dupont_value(metric: str, value: float) -> str:
    if metric in {"net_profit_margin", "roe"}:
        return f"{value:.1f}%"
    return f"{value:.2f}x"


def status_detail(actual: float, target: float, kpi_id: str, unit: str) -> str:
    if target == 0:
        return "目标为 0"
    gap = actual - target
    if is_lower_better(kpi_id):
        if actual <= target:
            return f"优于阈值 {format_value(target, unit)}"
        return f"超出阈值 {format_value(abs(gap), unit)}"
    if actual >= target:
        return f"高于目标 {format_value(abs(gap), unit)}"
    return f"低于目标 {format_value(abs(gap), unit)}"


def grade_from_score(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    return "C"


def render_dashboard_meta(generated_at: str, source_name: str, meta: dict) -> str:
    lines = [
        "<!--",
        f"  Generated: {generated_at} | Source: {source_name} | Mode: {meta['mode']}",
        "  LangConfig Dashboard Meta",
    ]
    for key in ("db", "skills", "mode", "entry", "title", "study"):
        value = meta.get(key)
        if value:
            lines.append(f"  {key}: {value}")
    lines.append("-->")
    return "\n".join(lines)


def factor_health_class(score: float) -> str:
    if score >= 90:
        return "good"
    if score >= 80:
        return "watch"
    return "risk"


def nav_links_html(active: str) -> str:
    """Generate nav-links block with active page highlighted."""
    pages = [
        ("Intro", "/api/files/sunhing_intro.html"),
        ("Main Dashboard", "/api/files/sunhing_dashboard.html"),
        ("Profit", "/api/files/sunhing_dashboard_profit.html"),
        ("Turnover", "/api/files/sunhing_dashboard_turnover.html"),
        ("Leverage", "/api/files/sunhing_dashboard_leverage.html"),
        ("Support", "/api/files/sunhing_dashboard_support.html"),
        ("Risk", "/api/files/sunhing_dashboard_risk.html"),
        ("Employees", "/api/files/sunhing_dashboard_employees.html"),
        ("Liability", "/api/files/sunhing_dashboard_liability.html"),
        ("ERD", "/api/files/sunhing_erd.html"),
        ("Gantt", "/api/files/sunhing_gantt.html"),
    ]
    links = []
    for label, href in pages:
        cls = ' class="active"' if label == active else ""
        links.append(f'    <a href="{href}"{cls}>{label}</a>')
    return "\n".join(links)


def generate_chart_js(chart_id: str, kpi_id: str, periods: list, actuals: list, target_val: float) -> str:
    """Generate Plotly JS for a single KPI time-series chart."""
    actuals_json = json.dumps(actuals)
    periods_json = json.dumps(periods)

    # Pick color based on last value vs target
    last_val = actuals[-1] if actuals else 0
    is_ok = is_met(last_val, target_val, kpi_id) if target_val != 0 else (last_val == 0)
    color = "#2ca02c" if is_ok else "#ff7f0e"

    # Determine title from kpi_id
    pretty_id = kpi_id.split("_", 1)[0]

    js = f"""
Plotly.newPlot('{chart_id}', [
  {{
    x: {periods_json},
    y: {actuals_json},
    type: 'scatter',
    mode: 'lines+markers',
    line: {{ color: '{color}', width: 3 }},
  }},
"""

    if target_val is not None and target_val != 0:
        js += f"""
  {{
    x: {periods_json},
    y: {periods_json}.map(function() {{ return {target_val}; }}),
    type: 'scatter',
    mode: 'lines',
    name: 'Target',
    line: {{ color: '#e74c3c', width: 1, dash: 'dash' }}
  }},
"""

    js += f"""
], {{
  margin: {{ t: 36, b: 30, l: 40, r: 10 }},
  hovermode: 'x unified',
  showlegend: false
}});"""
    return js


def generate_sub_dashboard_html(
    db_cursor: sqlite3.Cursor,
    config: dict,
    periods: list,
    all_monthly_data: dict,
) -> str:
    """Generate a factor sub-dashboard HTML file."""
    factor_key = config["factor_key"]
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Get latest period
    latest_p = periods[-1]
    earliest_p = periods[0]

    # Get KPI data for this factor
    kpi_rows = db_cursor.execute(
        """
        SELECT f.kpi_id, d.kpi_name, d.roe_factor, f.actual, f.target, f.unit
        FROM fact_kpi_monthly f
        JOIN dim_kpi d ON f.kpi_id = d.kpi_id
        WHERE f.company_id = 1 AND f.period = ? AND d.roe_factor = ?
        ORDER BY f.kpi_id
        """,
        (latest_p, factor_key),
    ).fetchall()

    items = []
    for row in kpi_rows:
        row = dict(row)
        row["kpi_name"] = clean_name(row["kpi_name"])
        row["score"] = round(calc_score(row["actual"], row["target"], row["kpi_id"]), 1)
        row["met"] = is_met(row["actual"], row["target"], row["kpi_id"])
        row["actual_display"] = format_value(row["actual"], row["unit"])
        row["target_display"] = format_value(row["target"], row["unit"])
        items.append(row)

    # Summary cards (top 4 items)
    summary_cards = []
    for item in items:
        card_class = "ok" if item["met"] else "warn"
        gap = item["target"] - item["actual"] if not is_lower_better(item["kpi_id"]) else item["actual"] - item["target"]
        kpi_short = item["kpi_id"].split("_", 1)[0]
        note = (
            f"Target {item['target_display']} ✅ Met"
            if item["met"]
            else f"Target {item['target_display']} △ {abs(gap):.1f} gap"
        )
        summary_cards.append(
            f'    <div class="kpi-card {card_class}">'
            f'<div class="label">{kpi_short} {item["kpi_name"]}</div>'
            f'<div class="value">{item["actual_display"]}</div>'
            f'<div class="note">{note}</div></div>'
        )

    # KPI status table rows (all items)
    table_rows = []
    for item in items:
        kpi_short = item["kpi_id"].split("_", 1)[0]
        status_cls = "met" if item["met"] else "miss"
        status_text = "✅ Met" if item["met"] else ("⚠️ Near Miss" if item["score"] >= 70 else "⚠️ Far Behind")
        gap = item["target"] - item["actual"] if not is_lower_better(item["kpi_id"]) else item["actual"] - item["target"]
        gap_str = f"+{gap:.1f}" if gap > 0 and item["met"] else f"{gap:.1f}" if gap != 0 else "0"
        table_rows.append(
            f"    <tr><td>{kpi_short}</td><td>{item['kpi_name']}</td>"
            f"<td>{item['actual_display']}</td>"
            f"<td>{item['target_display']}</td>"
            f"<td>{gap_str}</td>"
            f'<td class="{status_cls}">{status_text}</td></tr>'
        )

    # Generate chart JS for each KPI
    chart_js_parts = []
    for i, item in enumerate(items):
        kpi_short = item["kpi_id"]
        chart_id = f"c{kpi_short.split('_', 1)[0]}"
        monthly = all_monthly_data.get(kpi_short, [])
        if monthly:
            chart_js_parts.append(
                generate_chart_js(chart_id, kpi_short, periods, monthly, item["target"])
            )

    # Chart grid cards
    chart_cards = []
    for i, item in enumerate(items):
        kpi_short = item["kpi_id"].split("_", 1)[0]
        chart_cards.append(
            f'    <div class="card">'
            f'<div class="chart-title">{item["kpi_id"]}</div>'
            f'<div id="c{kpi_short}" class="chart"></div></div>'
        )

    # Insight text — auto-generated from items
    met_items = [it for it in items if it["met"]]
    miss_items = [it for it in items if not it["met"]]
    near_miss = [it for it in miss_items if it["score"] >= 70]
    far_behind = [it for it in miss_items if it["score"] < 70]

    insight_parts = []
    if met_items:
        met_names = "、".join(f'{it["kpi_name"]} ({it["actual_display"]})' for it in met_items[:3])
        insight_parts.append(f"<li><strong>已完成</strong>: {met_names}</li>")
    if near_miss:
        for it in near_miss:
            gap = abs((it["target"] - it["actual"]) if not is_lower_better(it["kpi_id"]) else (it["actual"] - it["target"]))
            insight_parts.append(
                f"<li><strong>接近达标</strong>: {it['kpi_name']} {it['actual_display']} vs {it['target_display']}"
                f" — 差距 {gap:.1f}</li>"
            )
    if far_behind:
        for it in far_behind:
            insight_parts.append(
                f"<li><strong>需重点关注</strong>: {it['kpi_name']} 仅 {it['actual_display']} vs {it['target_display']}"
                f" — 差距较大</li>"
            )
    if not insight_parts:
        insight_parts.append("<li><strong>所有KPI均达标</strong>: 本因子所有指标均达到或超过目标值</li>")

    meta_block = render_dashboard_meta(
        generated_at, DB_PATH.name,
        {"db": DB_META_PATH, "skills": "sunhing-analyst", "mode": "static-embed",
         "entry": "detail", "title": config["title_en"], "study": "sunhing-transformation"}
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
{meta_block}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sun Hing — {config["title_en"]}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>{SUB_CSS}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>{config["icon"]} {config["title_cn"]}</h1>
    <div class="sub">Sun Hing Vision Group detail dashboard · aligned with executive cockpit visual system</div>
  </div>
  <div style="font-size:13px;color:var(--gold-light)">Sun Hing transformation dashboard suite</div>
</div>

<div class="baseline-bar">
  <div>当前主题 <span>{config["baseline_label"]}</span></div>
  <div>观察期 <span>{earliest_p} → {latest_p}</span></div>
  <div>当前月 <span>{latest_p}</span></div>
</div>

<div class="container">

  <div class="nav-links">
{nav_links_html(config["active_nav"])}
  </div>

  <div class="page-title">{config["icon"]} {config["title_cn"]}</div>
  <div class="page-subtitle">{config["subtitle"]}</div>

  <div class="kpi-row">
{chr(10).join(summary_cards)}
  </div>

  <div class="grid">
{chr(10).join(chart_cards)}
  </div>

  <div class="card">
    <h3 style="margin:0 0 10px;font-size:14px;">📋 {config["title_cn"]} KPI Status</h3>
    <table class="kpi-table">
      <tr><th>#</th><th>KPI</th><th>{latest_p}</th><th>Target</th><th>Gap</th><th>Status</th></tr>
{chr(10).join(table_rows)}
    </table>
  </div>

  <div class="insight-box">
    <h3>关键洞察</h3>
    <ul>
{chr(10).join(insight_parts)}
    </ul>
  </div>

</div>

<script>
var periods = {json.dumps(periods)};
{chr(10).join(chart_js_parts)}
</script>
</body>
</html>"""
    return html


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# ── Periods ────────────────────────────────────────────────────────────
latest_period = conn.execute(
    "SELECT MAX(period) AS period FROM fact_kpi_monthly WHERE company_id = 1"
).fetchone()["period"]
earliest_period = conn.execute(
    "SELECT MIN(period) AS period FROM fact_kpi_monthly WHERE company_id = 1"
).fetchone()["period"]
all_periods = [
    r["period"]
    for r in conn.execute(
        "SELECT DISTINCT period FROM fact_kpi_monthly WHERE company_id = 1 ORDER BY period"
    ).fetchall()
]

# ── ROE trend ──────────────────────────────────────────────────────────
roe_rows = [
    dict(row)
    for row in conn.execute(
        """
        SELECT period, net_profit_margin, asset_turnover, equity_multiplier, roe
        FROM fact_roe_summary
        WHERE company_id = 1
        ORDER BY period
        """
    ).fetchall()
]

# ── Latest KPI data (for hub) ──────────────────────────────────────────
latest_kpis = [
    dict(row)
    for row in conn.execute(
        """
        SELECT
            f.kpi_id,
            d.kpi_name,
            d.roe_factor,
            f.actual,
            f.target,
            f.unit
        FROM fact_kpi_monthly f
        JOIN dim_kpi d ON f.kpi_id = d.kpi_id
        WHERE f.company_id = 1 AND f.period = ?
        ORDER BY
            CASE d.roe_factor
                WHEN '净利润率' THEN 1
                WHEN '资产周转率' THEN 2
                WHEN '权益乘数' THEN 3
                WHEN '支撑层' THEN 4
                WHEN '风险监控' THEN 5
                ELSE 99
            END,
            f.kpi_id
        """,
        (latest_period,),
    ).fetchall()
]

# ── Monthly time-series data for all KPIs (for sub-dashboard charts) ───
all_monthly_data: dict[str, list[float]] = defaultdict(list)
for row in conn.execute(
    """
    SELECT kpi_id, period, actual
    FROM fact_kpi_monthly
    WHERE company_id = 1
    ORDER BY kpi_id, period
    """
).fetchall():
    all_monthly_data[row["kpi_id"]].append(row["actual"])

# ── HR data ────────────────────────────────────────────────────────────
raw_hr = [
    dict(row)
    for row in conn.execute(
        """
        SELECT period, total_headcount, production_headcount,
               severance_completed_cumulative, severance_paid_cumulative_wan
        FROM raw_hr
        ORDER BY period
        """
    ).fetchall()
]

# ── Liability data ─────────────────────────────────────────────────────
raw_liability = [
    dict(row)
    for row in conn.execute(
        """
        SELECT category, total_amount_wan, resolved_wan, remaining_wan
        FROM raw_liability
        ORDER BY total_amount_wan DESC, category
        """
    ).fetchall()
]

conn.close()

# ── Enrich KPI rows for hub ────────────────────────────────────────────
factor_groups: dict[str, list[dict]] = defaultdict(list)
for row in latest_kpis:
    row["kpi_name"] = clean_name(row["kpi_name"])
    row["score"] = round(calc_score(row["actual"], row["target"], row["kpi_id"]), 1)
    row["met"] = is_met(row["actual"], row["target"], row["kpi_id"])
    row["grade"] = grade_from_score(row["score"])
    row["actual_display"] = format_value(row["actual"], row["unit"])
    row["target_display"] = format_value(row["target"], row["unit"])
    row["status_detail"] = status_detail(row["actual"], row["target"], row["kpi_id"], row["unit"])
    factor_groups[row["roe_factor"]].append(row)

factor_cards = []
for factor_name, items in factor_groups.items():
    meta = FACTOR_META[factor_name]
    met_count = sum(1 for item in items if item["met"])
    avg_score = round(sum(item["score"] for item in items) / len(items), 1)
    critical = min(items, key=lambda item: item["score"])
    factor_cards.append({
        "factor": factor_name,
        "short": meta["short"],
        "score": avg_score,
        "met_count": met_count,
        "total": len(items),
        "grade": grade_from_score(avg_score),
        "health_class": factor_health_class(avg_score),
        "meta": meta,
        "critical_name": critical["kpi_name"],
        "critical_status": critical["status_detail"],
    })

factor_cards.sort(
    key=lambda card: ["净利润率", "资产周转率", "权益乘数", "支撑层", "风险监控"].index(card["factor"])
)

baseline_roe = roe_rows[0]["roe"]
latest_roe = roe_rows[-1]["roe"]
latest_dupont = roe_rows[-1]
roe_delta = latest_roe - baseline_roe
roe_direction = "up" if roe_delta > 0 else "down" if roe_delta < 0 else "flat"

met_total = sum(card["met_count"] for card in factor_cards)
all_total = sum(card["total"] for card in factor_cards)
risk_card = next(card for card in factor_cards if card["factor"] == "风险监控")
top_bottlenecks = sorted(
    [item for item in latest_kpis if not item["met"]],
    key=lambda item: item["score"],
)[:3]

latest_hr = raw_hr[-1]
first_hr = raw_hr[0]
liability_total = sum(item["total_amount_wan"] for item in raw_liability)
liability_resolved = sum(item["resolved_wan"] for item in raw_liability)
liability_remaining = sum(item["remaining_wan"] for item in raw_liability)

dupont_card_metrics = {
    "净利润率": "net_profit_margin",
    "资产周转率": "asset_turnover",
    "权益乘数": "equity_multiplier",
}
main_cards = []
for card in factor_cards:
    dupont_metric = dupont_card_metrics.get(card["factor"])
    display_value = f'{card["score"]:.1f}'
    meta_line = f'平均达成得分 · 达标 {card["met_count"]}/{card["total"]}'
    focus_prefix = "当前最弱项"

    if dupont_metric:
        display_value = format_dupont_value(dupont_metric, latest_dupont[dupont_metric])
        meta_line = (
            f'DuPont 原始值 · KPI 平均得分 {card["score"]:.1f} · '
            f'达标 {card["met_count"]}/{card["total"]}'
        )
        focus_prefix = "KPI层最弱项"

    main_cards.append({
        **card,
        "display_value": display_value,
        "meta_line": meta_line,
        "focus_prefix": focus_prefix,
    })

# ── Build hub sections (collapsible factor tables) ─────────────────────
sections_html = []
for factor_name, items in factor_groups.items():
    meta = FACTOR_META[factor_name]
    rows_html = []
    for item in items:
        status_class = "met" if item["met"] else "miss"
        rows_html.append(
            f"""
          <div class="kpi-row">
            <div class="kpi-id">{item['kpi_id'].split('_', 1)[0]}</div>
            <div class="kpi-name">{item['kpi_name']}</div>
            <div class="kpi-value">{item['actual_display']}</div>
            <div class="kpi-target">{item['target_display']}</div>
            <div class="kpi-score">{item['score']:.1f}</div>
            <div class="kpi-status {status_class}">{'达标' if item['met'] else '关注'}</div>
          </div>
          <div class="kpi-note">{item['status_detail']}</div>
            """.strip()
        )
    sections_html.append(
        f"""
      <div class="section">
        <div class="section-header {meta['header_class']}" onclick="toggleSection(this)">
          <span>{factor_name} · {meta['summary']}</span>
          <span class="toggle-icon">▼</span>
        </div>
        <div class="section-body open">
          <div class="section-meta">
            <span>{meta['link_label']}</span>
            <a href="{meta['link']}">打开详情</a>
          </div>
          <div class="kpi-head">
            <div>#</div>
            <div>指标</div>
            <div>实际</div>
            <div>目标</div>
            <div>得分</div>
            <div>状态</div>
          </div>
          {''.join(rows_html)}
        </div>
      </div>
        """.strip()
    )

# ── Generate HUB HTML ──────────────────────────────────────────────────
embedded_data = {
    "roeTrend": roe_rows,
    "latestKpis": latest_kpis,
    "factorCards": factor_cards,
    "rawHr": raw_hr,
    "liabilitySummary": raw_liability,
}

generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
meta_block = render_dashboard_meta(generated_at, DB_PATH.name, DASHBOARD_META)

hub_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
{meta_block}
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sun Hing — ROE Executive Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  :root {{
    --navy: #0B2344;
    --navy-mid: #1A3A5C;
    --gold: #B5935A;
    --gold-light: #D4AF70;
    --off-white: #F5F4F0;
    --slate: #4A5568;
    --mid-grey: #718096;
    --light-grey: #E2E8F0;
    --body: #1A202C;
    --green: #00B050;
    --orange: #FFC000;
    --red: #FF5050;
    --dark-green: #006600;
    --dark-blue: #1F4E79;
    --dark-purple: #5B2C6F;
    --dark-orange: #C65911;
    --dark-red: #7A1F1F;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
    background: #f0f2f5;
    color: var(--body);
    line-height: 1.5;
    padding: 0 0 40px 0;
  }}
  .header {{
    background: var(--navy);
    color: white;
    padding: 18px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .header h1 {{ font-size: 20px; font-weight: 700; }}
  .header .sub {{ font-size: 13px; color: var(--gold-light); }}
  .baseline-bar {{
    background: var(--navy-mid);
    color: white;
    padding: 10px 24px;
    display: flex;
    gap: 28px;
    flex-wrap: wrap;
    font-size: 13px;
  }}
  .baseline-bar span {{ color: var(--gold-light); }}
  .container {{
    max-width: 1320px;
    margin: 20px auto;
    padding: 0 16px;
  }}
  .nav-links {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 16px;
  }}
  .nav-links a {{
    background: white;
    color: var(--slate);
    padding: 10px 16px;
    border-radius: 8px;
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }}
  .nav-links a:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.12); }}
  .dashboard {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 14px;
    margin-bottom: 18px;
  }}
  @media (max-width: 1200px) {{
    .dashboard {{ grid-template-columns: repeat(3, 1fr); }}
  }}
  @media (max-width: 900px) {{
    .dashboard {{ grid-template-columns: repeat(2, 1fr); }}
  }}
  @media (max-width: 640px) {{
    .dashboard {{ grid-template-columns: 1fr; }}
  }}
  .factor-card {{
    background: white;
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    border-top: 4px solid #ccc;
  }}
  .factor-card.npm {{ border-top-color: var(--dark-green); }}
  .factor-card.at {{ border-top-color: var(--dark-blue); }}
  .factor-card.em {{ border-top-color: var(--dark-purple); }}
  .factor-card.sup {{ border-top-color: var(--dark-orange); }}
  .factor-card.risk {{ border-top-color: var(--dark-red); }}
  .factor-card h3 {{ font-size: 13px; color: var(--slate); margin-bottom: 6px; }}
  .factor-card .score {{ font-size: 26px; font-weight: 700; color: var(--navy); }}
  .factor-card .meta {{ font-size: 12px; color: var(--mid-grey); margin-top: 4px; }}
  .factor-card .focus {{
    margin-top: 8px;
    font-size: 12px;
    color: var(--body);
    min-height: 34px;
  }}
  .grade-badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 700;
    color: white;
    margin-top: 6px;
  }}
  .grade-A {{ background: var(--green); }}
  .grade-B {{ background: var(--orange); color: #333; }}
  .grade-C {{ background: var(--red); }}
  .result-bar {{
    background: var(--navy);
    color: white;
    border-radius: 12px;
    padding: 18px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 16px;
    margin-bottom: 16px;
  }}
  .result-bar .roe-value {{ font-size: 36px; font-weight: 700; color: white; }}
  .result-bar .delta {{ font-size: 18px; font-weight: 600; }}
  .delta.up {{ color: #4ade80; }}
  .delta.down {{ color: #f87171; }}
  .delta.flat {{ color: var(--gold-light); }}
  .summary-bar {{
    background: white;
    border-radius: 10px;
    padding: 12px 18px;
    margin-bottom: 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
    font-size: 14px;
  }}
  .summary-bar .total {{
    font-weight: 700;
    font-size: 16px;
  }}
  .summary-bar .ok {{ color: var(--dark-green); }}
  .summary-bar .warn {{ color: var(--red); }}
  .overview-grid {{
    display: grid;
    grid-template-columns: 1.2fr 1fr;
    gap: 16px;
    margin-bottom: 16px;
  }}
  @media (max-width: 960px) {{
    .overview-grid {{ grid-template-columns: 1fr; }}
  }}
  .card {{
    background: white;
    border-radius: 12px;
    padding: 14px 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }}
  .card h3 {{
    color: var(--navy);
    margin-bottom: 8px;
    font-size: 14px;
  }}
  .chart {{ width: 100%; height: 330px; }}
  .section {{
    background: white;
    border-radius: 12px;
    margin-bottom: 16px;
    overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }}
  .section-header {{
    padding: 12px 18px;
    font-weight: 700;
    font-size: 15px;
    color: white;
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
  }}
  .section-header.npm {{ background: var(--dark-green); }}
  .section-header.at {{ background: var(--dark-blue); }}
  .section-header.em {{ background: var(--dark-purple); }}
  .section-header.sup {{ background: var(--dark-orange); }}
  .section-header.risk {{ background: var(--dark-red); }}
  .section-body {{ padding: 12px 16px 16px; display: none; }}
  .section-body.open {{ display: block; }}
  .section-meta {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 10px;
    font-size: 12px;
    color: var(--mid-grey);
  }}
  .section-meta a {{
    color: var(--navy);
    text-decoration: none;
    font-weight: 700;
  }}
  .kpi-head,
  .kpi-row {{
    display: grid;
    grid-template-columns: 72px 2fr 1fr 1fr 90px 90px;
    gap: 10px;
    align-items: center;
    font-size: 13px;
  }}
  .kpi-head {{
    border-bottom: 2px solid #eee;
    padding-bottom: 8px;
    font-weight: 700;
    color: var(--mid-grey);
  }}
  .kpi-row {{
    padding: 10px 0 6px;
    border-bottom: 1px solid #f1f5f9;
  }}
  .kpi-row:last-of-type {{ border-bottom: none; }}
  .kpi-id {{ font-weight: 700; color: var(--navy); }}
  .kpi-name {{ font-weight: 500; }}
  .kpi-score {{ font-weight: 700; }}
  .kpi-status {{
    text-align: center;
    padding: 4px 0;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
  }}
  .kpi-status.met {{ background: #dcfce7; color: #166534; }}
  .kpi-status.miss {{ background: #fee2e2; color: #991b1b; }}
  .kpi-note {{
    font-size: 12px;
    color: var(--mid-grey);
    padding-bottom: 10px;
    margin-left: 82px;
  }}
  .insight-box {{
    background: white;
    border-radius: 12px;
    padding: 16px 20px;
    font-size: 13px;
    color: var(--slate);
    line-height: 1.7;
    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
  }}
  .insight-box h3 {{ color: var(--navy); margin-bottom: 8px; font-size: 14px; }}
  .insight-box ul {{ padding-left: 20px; }}
  .toggle-icon {{ font-size: 14px; opacity: 0.9; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Sun Hing Vision Group ROE Executive Dashboard</h1>
    <div class="sub">一分为多重组执行驾驶舱 · 主仪表盘以 ROE 因子组织 28 项 KPI · 只读管理视图</div>
  </div>
  <div style="font-size:13px;color:var(--gold-light)">ROE = 净利润率 × 资产周转率 × 权益乘数 · 支撑层与风险监控提供执行保障</div>
</div>

<div class="baseline-bar">
  <div>时间范围 <span>{earliest_period} → {latest_period}</span></div>
  <div>当前观察月 <span>{latest_period}</span></div>
  <div>基准 ROE <span>{baseline_roe:.1f}%</span></div>
  <div>当前 ROE <span>{latest_roe:.1f}%</span></div>
  <div>追缴总额 <span>{liability_total:.0f} 万HKD</span></div>
</div>

<div class="container">
  <div class="nav-links">
    <a href="/api/files/sunhing_intro.html">Intro</a>
    <a href="/api/files/sunhing_dashboard_profit.html">Profit (KPI 01-09)</a>
    <a href="/api/files/sunhing_dashboard_turnover.html">Turnover (10-13)</a>
    <a href="/api/files/sunhing_dashboard_leverage.html">Leverage (14-17)</a>
    <a href="/api/files/sunhing_dashboard_support.html">Support (18-21)</a>
    <a href="/api/files/sunhing_dashboard_risk.html">Risk (RS01-07)</a>
    <a href="/api/files/sunhing_dashboard_employees.html">Employees</a>
    <a href="/api/files/sunhing_dashboard_liability.html">Liability Detail</a>
    <a href="/api/files/sunhing_erd.html">ERD</a>
    <a href="/api/files/sunhing_gantt.html">Gantt</a>
  </div>

  <div class="dashboard">
    {''.join(
        f'''
    <div class="factor-card {card["meta"]["card_class"]}">
      <h3>{card["short"]}</h3>
      <div class="score">{card["display_value"]}</div>
      <div class="meta">{card["meta_line"]}</div>
      <div><span class="grade-badge grade-{card["grade"]}">KPI等级 {card["grade"]}</span></div>
      <div class="focus">{card["focus_prefix"]}：<strong>{card["critical_name"]}</strong><br>{card["critical_status"]}</div>
    </div>
        '''.strip()
        for card in main_cards
    )}
  </div>

  <div class="result-bar">
    <div>
      <div style="font-size:13px;color:var(--gold-light);margin-bottom:4px">当前 ROE（{latest_period}）</div>
      <div class="roe-value">{latest_roe:.1f}%</div>
    </div>
    <div style="text-align:right">
      <div class="delta {roe_direction}">
        {'+' if roe_delta > 0 else ''}{roe_delta:.1f}% vs {earliest_period}
      </div>
      <div style="font-size:12px;color:#94a3b8;margin-top:4px">
        {roe_rows[-1]["net_profit_margin"]:.1f}% \u00d7 {roe_rows[-1]["asset_turnover"]:.2f} \u00d7 {roe_rows[-1]["equity_multiplier"]:.2f}
      </div>
    </div>
  </div>

  <div class="summary-bar">
    <div>
      最新月总体达标：
      <span class="total">{met_total}/{all_total}</span>
      <span class="{ 'ok' if met_total >= all_total * 0.7 else 'warn' }">
        ({met_total / all_total * 100:.1f}%)
      </span>
    </div>
    <div>减员完成 <strong>{latest_hr["severance_completed_cumulative"]}</strong> / 856 · 赔偿已支出 <strong>{latest_hr["severance_paid_cumulative_wan"]:.0f} 万</strong></div>
    <div>追缴已化解 <strong>{liability_resolved:.0f} 万</strong> · 剩余 <strong>{liability_remaining:.0f} 万</strong></div>
  </div>

  <div class="overview-grid">
    <div class="card">
      <h3>ROE 修复趋势</h3>
      <div id="roe-trend" class="chart"></div>
    </div>
    <div class="card">
      <h3>五大因子最新得分</h3>
      <div id="factor-score" class="chart"></div>
    </div>
  </div>

  {''.join(sections_html)}

  <div class="insight-box">
    <h3>管理层结论</h3>
    <ul>
      <li><strong>ROE 修复</strong>：ROE 从 {earliest_period} 的 {baseline_roe:.1f}% 回升到 {latest_period} 的 {latest_roe:.1f}%，已由负转正，说明重组开始释放财务修复效果。</li>
      <li><strong>最稳因子</strong>：风险监控当前达标 {risk_card["met_count"]}/{risk_card["total"]}，整体处于可控区间，但仍需盯住 RS04 保税物料合规处理完成率。</li>
      <li><strong>执行短板</strong>：{'; '.join(item['kpi_name'] for item in top_bottlenecks)} 仍是当前主要拖累项，应优先安排专项收口。</li>
      <li><strong>组织进度</strong>：累计减员 {latest_hr["severance_completed_cumulative"]} 人，较起点总人数下降 {((first_hr["total_headcount"] - latest_hr["total_headcount"]) * 100.0 / first_hr["total_headcount"]):.1f}%，但生产人员结构优化仍落后于目标。</li>
      <li><strong>下一步动作</strong>：保持利润率与资产周转修复节奏，同时将注意力转向生产结构、客户迁移风险和历史追缴尾项。</li>
    </ul>
  </div>
</div>

<script>
var EMBEDDED_DATA = {json.dumps(embedded_data, ensure_ascii=False)};

function toggleSection(header) {{
  var body = header.nextElementSibling;
  var icon = header.querySelector('.toggle-icon');
  body.classList.toggle('open');
  icon.textContent = body.classList.contains('open') ? '\u25bc' : '\u25b6';
}}

var roeRows = EMBEDDED_DATA.roeTrend;
var factorCards = EMBEDDED_DATA.factorCards;

Plotly.newPlot('roe-trend', [
  {{
    x: roeRows.map(function(r) {{ return r.period; }}),
    y: roeRows.map(function(r) {{ return r.roe; }}),
    type: 'scatter',
    mode: 'lines+markers',
    name: 'ROE',
    line: {{ color: '#0B2344', width: 3 }},
    marker: {{ size: 8 }}
  }},
  {{
    x: roeRows.map(function(r) {{ return r.period; }}),
    y: roeRows.map(function() {{ return 0; }}),
    type: 'scatter',
    mode: 'lines',
    name: 'Break-even',
    line: {{ color: '#B5935A', width: 2, dash: 'dash' }}
  }}
], {{
  margin: {{ t: 30, b: 40, l: 50, r: 20 }},
  hovermode: 'x unified',
  legend: {{ orientation: 'h', y: -0.22 }},
  yaxis: {{ ticksuffix: '%' }}
}});

Plotly.newPlot('factor-score', [{{
  x: factorCards.map(function(card) {{ return card.short; }}),
  y: factorCards.map(function(card) {{ return card.score; }}),
  type: 'bar',
  marker: {{
    color: factorCards.map(function(card) {{ return card.meta.accent; }})
  }},
  text: factorCards.map(function(card) {{ return card.score.toFixed(1); }}),
  textposition: 'outside'
}}], {{
  margin: {{ t: 30, b: 60, l: 50, r: 20 }},
  yaxis: {{ range: [0, 110] }}
}});
</script>
</body>
</html>
"""

# ── Write hub HTML ─────────────────────────────────────────────────────
hub_path = OUTPUT_DIR / "sunhing_dashboard.html"
hub_path.write_text(hub_html, encoding="utf-8")
print(f"\u2705 Hub dashboard generated: {hub_path}")
print(f"   File size: {len(hub_html):,} bytes")

# ── Generate ALL sub-dashboards ────────────────────────────────────────
for sd_config in SUB_DASHBOARDS:
    # Open a fresh DB connection for each dashboard
    sub_conn = sqlite3.connect(str(DB_PATH))
    sub_conn.row_factory = sqlite3.Row
    sub_html = generate_sub_dashboard_html(
        sub_conn,
        sd_config,
        all_periods,
        dict(all_monthly_data),
    )
    sub_conn.close()

    sub_path = OUTPUT_DIR / sd_config["filename"]
    sub_path.write_text(sub_html, encoding="utf-8")
    print(f"\u2705 Sub-dashboard generated: {sub_path} ({len(sub_html):,} bytes)")

print(f"\n\u2705 All dashboards generated successfully.")
print(f"   Hub: sunhing_dashboard.html")
print(f"   Sub-dashboards:")
for sd in SUB_DASHBOARDS:
    print(f"     - {sd['filename']}")

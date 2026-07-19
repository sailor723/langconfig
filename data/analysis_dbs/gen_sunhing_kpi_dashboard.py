"""
Generate the main Sun Hing executive dashboard.

The main dashboard is a read-only executive cockpit for the Sun Hing
transformation program. It follows the visual language of the ROE KPI
simulator while rendering live metrics from SQLite instead of interactive
score inputs.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


DB_PATH = Path(__file__).parent / "sunhing_kpi.db"
OUTPUT_PATH = Path(__file__).parent / "sunhing_dashboard.html"

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


def is_lower_better(kpi_id: str) -> bool:
    return kpi_id in LOWER_IS_BETTER


def calc_score(actual: float, target: float, kpi_id: str) -> float:
    """Normalize KPI achievement to a 0-100 score for dashboard summaries."""
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


def factor_health_class(score: float) -> str:
    if score >= 90:
        return "good"
    if score >= 80:
        return "watch"
    return "risk"


conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

latest_period = conn.execute(
    "SELECT MAX(period) AS period FROM fact_kpi_monthly WHERE company_id = 1"
).fetchone()["period"]
earliest_period = conn.execute(
    "SELECT MIN(period) AS period FROM fact_kpi_monthly WHERE company_id = 1"
).fetchone()["period"]

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

raw_hr = [
    dict(row)
    for row in conn.execute(
        """
        SELECT
            period,
            total_headcount,
            production_headcount,
            severance_completed_cumulative,
            severance_paid_cumulative_wan
        FROM raw_hr
        ORDER BY period
        """
    ).fetchall()
]

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

# Enrich KPI rows for rendering and summaries.
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
    factor_cards.append(
        {
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
        }
    )

factor_cards.sort(
    key=lambda card: ["净利润率", "资产周转率", "权益乘数", "支撑层", "风险监控"].index(card["factor"])
)

baseline_roe = roe_rows[0]["roe"]
latest_roe = roe_rows[-1]["roe"]
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

embedded_data = {
    "roeTrend": roe_rows,
    "latestKpis": latest_kpis,
    "factorCards": factor_cards,
    "rawHr": raw_hr,
    "liabilitySummary": raw_liability,
}

generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<!--
  Generated: {generated_at} | Source: sunhing_kpi.db | Mode: static-embed
  LangConfig Dashboard Meta
  db: {DB_PATH}
  skills: sunhing-analyst
-->
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
      <div class="score">{card["score"]:.1f}</div>
      <div class="meta">平均达成得分 · 达标 {card["met_count"]}/{card["total"]}</div>
      <div><span class="grade-badge grade-{card["grade"]}">等级 {card["grade"]}</span></div>
      <div class="focus">当前最弱项：<strong>{card["critical_name"]}</strong><br>{card["critical_status"]}</div>
    </div>
        '''.strip()
        for card in factor_cards
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
        {roe_rows[-1]["net_profit_margin"]:.1f}% × {roe_rows[-1]["asset_turnover"]:.2f} × {roe_rows[-1]["equity_multiplier"]:.2f}
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
  icon.textContent = body.classList.contains('open') ? '▼' : '▶';
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

OUTPUT_PATH.write_text(html, encoding="utf-8")
print(f"✅ Dashboard generated: {OUTPUT_PATH}")
print(f"   File size: {len(html):,} bytes")

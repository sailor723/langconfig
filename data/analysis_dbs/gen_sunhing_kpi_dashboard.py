"""
Generate a KPI #1 dashboard (协商减员完成率) for Sun Hing Vision Group.

Queries sunhing_kpi.db and produces a Plotly HTML dashboard
showing severance completion progress, cost tracking, and risk indicators.
"""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "sunhing_kpi.db"
OUTPUT_PATH = Path(__file__).parent / "sunhing_dashboard.html"

# ── Load data ──────────────────────────────────────────────────────────
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# KPI #1 monthly actuals
rows = conn.execute("""
    SELECT f.period, f.actual, f.target
    FROM fact_kpi_monthly f
    WHERE f.kpi_id = '01_协商减员完成率'
    ORDER BY f.period
""").fetchall()

# raw_hr for headcount + cost detail
hr_rows = conn.execute("""
    SELECT period, total_headcount, production_headcount,
           severance_completed_cumulative, severance_paid_cumulative_wan
    FROM raw_hr
    ORDER BY period
""").fetchall()

# raw_legal for risk events
legal_rows = conn.execute("""
    SELECT period, new_labor_arbitration_cases, pending_labor_cases, near_miss_group_incidents
    FROM raw_legal
    ORDER BY period
""").fetchall()

conn.close()

# ── Build embedded data ────────────────────────────────────────────────
periods = [r["period"] for r in rows]
kpi_actuals = [r["actual"] for r in rows]
target = rows[0]["target"] if rows else 100

hr_data = []
for r in hr_rows:
    hr_data.append({
        "period": r["period"],
        "headcount": r["total_headcount"],
        "prod_pct": round(r["production_headcount"] / r["total_headcount"] * 100, 1) if r["total_headcount"] else 0,
        "severed": r["severance_completed_cumulative"],
        "cost": r["severance_paid_cumulative_wan"]
    })

risk_data = []
for r in legal_rows:
    risk_data.append({
        "period": r["period"],
        "cases": r["new_labor_arbitration_cases"],
        "pending": r["pending_labor_cases"],
        "near_miss": r["near_miss_group_incidents"]
    })

PLANNED = 856

# ── Generate HTML ──────────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Sun Hing — 协商减员完成率 Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 24px; font-family: -apple-system, 'Noto Sans SC', sans-serif; background: #f0f2f5; }}
  h1 {{ font-size: 20px; font-weight: 600; margin-bottom: 6px; }}
  .subtitle {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 18px; }}
  .kpi-card {{ background: #fff; padding: 16px; border-radius: 10px; border-left: 4px solid #1f77b4; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  .kpi-card .label {{ font-size: 11px; color: #7f8c8d; text-transform: uppercase; letter-spacing: .5px; }}
  .kpi-card .value {{ font-size: 24px; font-weight: 700; margin: 4px 0 2px; }}
  .kpi-card .note {{ font-size: 12px; color: #999; }}
  .kpi-card.warn {{ border-left-color: #e74c3c; }}
  .kpi-card.ok {{ border-left-color: #2ca02c; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .grid .full {{ grid-column: 1 / -1; }}
  .chart-title {{ font-size: 13px; font-weight: 600; margin-bottom: 4px; color: #2c3e50; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .card {{ min-width: 0; background: #fff; padding: 12px; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
  .chart {{ width: 100%; height: 340px; }}
  .risk-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  .risk-table th {{ text-align: left; padding: 8px 10px; background: #f8f9fa; border-bottom: 2px solid #eee; }}
  .risk-table td {{ padding: 7px 10px; border-bottom: 1px solid #f0f0f0; }}
  .risk-table .warn {{ color: #e74c3c; font-weight: 600; }}
  .risk-table .ok {{ color: #2ca02c; }}
  .insight-box {{ background: #fff; padding: 14px 18px; border-radius: 10px; border-left: 4px solid #2ca02c; margin-top: 14px; }}
  .insight-box h3 {{ margin: 0 0 8px; font-size: 14px; }}
  .insight-box ul {{ margin: 0; padding-left: 18px; font-size: 13px; color: #333; }}
  .insight-box li {{ margin: 4px 0; }}
</style>
</head>
<body>

<h1>🏭 KPI #1 — 协商减员完成率</h1>
<div class="subtitle">Sun Hing Vision Group — 一分为多 Restructuring | Sep 2026 → Feb 2027 | Planned: {PLANNED} people</div>

<div class="kpi-row">
  <div class="kpi-card {'' if kpi_actuals[-1] >= 90 else 'warn'}">
    <div class="label">Completion Rate (Feb)</div>
    <div class="value">{kpi_actuals[-1]:.1f}%</div>
    <div class="note">Target: {target}%</div>
  </div>
  <div class="kpi-card">
    <div class="label">People Severed</div>
    <div class="value">{hr_data[-1]['severed']}</div>
    <div class="note">of {PLANNED} planned</div>
  </div>
  <div class="kpi-card">
    <div class="label">Total Cost (万HKD)</div>
    <div class="value">{hr_data[-1]['cost']:.0f}</div>
    <div class="note">vs 2,600 budget</div>
  </div>
  <div class="kpi-card {'' if risk_data[-1]['cases'] == 0 else 'warn'}">
    <div class="label">Labor Disputes (Feb)</div>
    <div class="value">{risk_data[-1]['cases']}</div>
    <div class="note">Peak: {max(r['cases'] for r in risk_data)} in Nov</div>
  </div>
</div>

<div class="grid">
  <div class="card"><div class="chart-title">协商减员完成率 (%)</div><div id="chart1" class="chart"></div></div>
  <div class="card"><div class="chart-title">Cumulative People Severed (of {PLANNED})</div><div id="chart2" class="chart"></div></div>
  <div class="card full"><div class="chart-title">Headcount &amp; Production Ratio</div><div id="chart3" class="chart"></div></div>
</div>

<div class="card" style="margin-bottom:14px;">
  <h3 style="margin:0 0 10px;font-size:14px;">⚠️ Risk Events by Month</h3>
  <table class="risk-table">
    <tr><th>Period</th><th>New Cases</th><th>Pending</th><th>Near-Miss Incidents</th><th>Status</th></tr>
    {''.join(
        f'<tr><td>{r["period"]}</td><td>{r["cases"]}</td><td>{r["pending"]}</td><td>{r["near_miss"]}</td><td class="{"warn" if r["cases"] > 0 else "ok"}">{"⚠️" if r["cases"] > 0 else "✅"}</td></tr>'
        for r in risk_data
    )}
  </table>
</div>

<div class="insight-box">
  <h3>关键洞察</h3>
  <ul>
    <li><strong>进度</strong>: {kpi_actuals[-1]:.1f}% complete at month 6 ({hr_data[-1]['severed']}/{PLANNED}) — { 'on track for 100%' if kpi_actuals[-1] >= 90 else 'lagging behind target' }</li>
    <li><strong>成本</strong>: {hr_data[-1]['cost']:.0f}万 spent vs 2,600万 budget — { 'under budget ✅' if hr_data[-1]['cost'] <= 2600 else 'over budget ⚠️' }</li>
    <li><strong>风险</strong>: Peak disputes in Nov ({max(r['cases'] for r in risk_data)} cases), declining to {risk_data[-1]['cases']} by Feb</li>
    <li><strong>Headcount</strong>: Reduced from {hr_data[0]['headcount']} → {hr_data[-1]['headcount']} ({ (hr_data[0]['headcount'] - hr_data[-1]['headcount']) / hr_data[0]['headcount'] * 100:.0f}% reduction)</li>
  </ul>
</div>

<script>
var months = {json.dumps(periods)};
var pct = {json.dumps(kpi_actuals)};
var targetVal = {target};
var hr = {json.dumps(hr_data)};

// Chart 1: Completion rate with target line
var trace1 = {{
  x: months, y: pct, type: 'scatter', mode: 'lines+markers',
  name: 'Actual',
  line: {{color: '#1f77b4', width: 3}},
  marker: {{size: 8}}
}};
var targetTrace = {{
  x: months, y: months.map(function() {{ return targetVal; }}),
  type: 'scatter', mode: 'lines',
  name: 'Target (100%)',
  line: {{color: '#e74c3c', width: 2, dash: 'dash'}}
}};
var milestone60 = {{
  x: months, y: months.map(function(m) {{ return m <= '2026-11' ? 60 : null; }}),
  type: 'scatter', mode: 'lines',
  name: '3mo milestone (60%)',
  line: {{color: '#ff7f0e', width: 2, dash: 'dot'}}
}};
Plotly.newPlot('chart1', [trace1, targetTrace, milestone60], {{
  title: '协商减员完成率 (%)',
  yaxis: {{range: [0, 105], ticksuffix: '%'}},
  margin: {{t: 52, b: 40, l: 50, r: 20}},
  legend: {{orientation: 'h', y: -0.25}},
  hovermode: 'x unified'
}});

// Chart 2: Cumulative people severed
var severed = hr.map(function(r) {{ return r.severed; }});
Plotly.newPlot('chart2', [{{
  x: months, y: severed, type: 'bar',
  marker: {{color: '#2ca02c'}},
  text: severed,
  textposition: 'outside'
}}], {{
  title: 'Cumulative People Severed (of {PLANNED})',
  yaxis: {{range: [0, {PLANNED + 50}]}},
  margin: {{t: 52, b: 40, l: 50, r: 20}}
}});

// Chart 3: Headcount trend
var hc = hr.map(function(r) {{ return r.headcount; }});
var prod = hr.map(function(r) {{ return r.prod_pct; }});
Plotly.newPlot('chart3', [
  {{
    x: months, y: hc, type: 'scatter', mode: 'lines+markers',
    name: 'Total Headcount',
    line: {{color: '#1f77b4', width: 3}},
    yaxis: 'y'
  }},
  {{
    x: months, y: prod, type: 'scatter', mode: 'lines+markers',
    name: 'Production Ratio (%)',
    line: {{color: '#ff7f0e', width: 2, dash: 'dot'}},
    yaxis: 'y2'
  }}
], {{
  title: 'Headcount & Production Ratio',
  yaxis: {{title: 'Headcount'}},
  yaxis2: {{title: 'Production %', overlaying: 'y', side: 'right', ticksuffix: '%'}},
  margin: {{t: 52, b: 40, l: 50, r: 50}},
  legend: {{orientation: 'h', y: -0.25}},
  hovermode: 'x unified'
}});
</script>
</body>
</html>
"""

import re as _re_meta

OUTPUT_PATH.write_text(html, encoding="utf-8")

# ── Inject LangConfig Dashboard Meta block ──
txt = OUTPUT_PATH.read_text(encoding="utf-8")
if "LangConfig Dashboard Meta" not in txt:
    meta = (
        "<!--\n"
        "  Generated: 2026-07-16 | Source: sunhing_kpi.db | Mode: static-embed\n"
        "  LangConfig Dashboard Meta\n"
        f"  db: {DB_PATH}\n"
        "  skills: sunhing-analyst\n"
        "-->"
    )
    patched = _re_meta.sub(r"(<head>\s*)", r"\1" + meta + "\n", txt, count=1)
    if patched != txt:
        OUTPUT_PATH.write_text(patched, encoding="utf-8")
        print("📝 Injected LangConfig Dashboard Meta block")

print(f"✅ Dashboard generated: {OUTPUT_PATH}")
print(f"   File size: {len(html):,} bytes")

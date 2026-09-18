#!/usr/bin/env python3
"""Use LLM to extract data from CSV/SQLite, then inject into a pre-built Plotly template."""
import argparse, asyncio, json, os, sys, sqlite3
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from services.csv_to_sqlite import csv_to_sqlite_from_bytes
from services.data_dashboard import parse_skill

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--skill", default=None)
    parser.add_argument("--output", default="/tmp/dashboard.html")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV not found: {csv_path}")
        sys.exit(1)

    from dotenv import load_dotenv
    load_dotenv(override=True)
    from config import settings

    csv_bytes = csv_path.read_bytes()
    table_name = csv_path.stem.replace("-", "_").replace(" ", "_")
    db_path = csv_to_sqlite_from_bytes(csv_bytes, csv_path.name, table_name)
    print(f"CSV -> SQLite: {db_path}")

    biz_context = ""
    if args.skill:
        skill_path = Path(args.skill)
        if skill_path.exists():
            skill = parse_skill(str(skill_path))
            sec = skill.get("sections", {})
            parts = []
            if "Column Definitions" in sec:
                parts.append("COLUMNS:\n" + sec["Column Definitions"])
            if "Business Logic" in sec:
                parts.append("BUSINESS RULES:\n" + sec["Business Logic"])
            if "Common Analysis Questions" in sec:
                parts.append("QUESTIONS:\n" + sec["Common Analysis Questions"])
            biz_context = "\n\n".join(parts)

    # Get data directly via SQLite (no agent needed for this simple case)
    import pandas as pd
    df = pd.read_sql(f'SELECT * FROM "{table_name}"', sqlite3.connect(db_path))
    
    # Convert to JS array of objects
    records = df.to_dict(orient="records")
    js_data = json.dumps(records, ensure_ascii=False, default=str)
    
    # Get column names and types
    cols = list(df.columns)
    num_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include="object").columns.tolist()
    
    # Build a complete Plotly dashboard HTML with the data embedded
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Sales Dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,Segoe UI,sans-serif;background:#0f172a;color:#e2e8f0;padding:20px}}
  h1{{font-size:22px;margin-bottom:4px;color:#f8fafc}}
  .sub{{color:#94a3b8;font-size:13px;margin-bottom:14px}}
  .kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:16px}}
  .kpi{{background:linear-gradient(135deg,#1e293b,#334155);padding:14px 16px;border-radius:10px;border:1px solid #334155}}
  .kpi .label{{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px}}
  .kpi .value{{font-size:24px;font-weight:700;color:#f8fafc;margin-top:4px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}}
  @media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
  .card{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:12px;margin-bottom:0}}
  .card h3{{font-size:13px;color:#cbd5e1;margin-bottom:6px;font-weight:600}}
  .chart{{width:100%;height:350px}}
  .insights{{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:18px;margin-top:6px}}
  .insights h3{{font-size:14px;color:#cbd5e1;margin-bottom:8px}}
  .insights li{{font-size:13px;color:#94a3b8;line-height:1.7}}
</style>
</head>
<body>
<h1>📊 Sales Dashboard</h1>
<p class="sub">Companion-driven analysis</p>
<div class="kpi-grid">
  <div class="kpi"><div class="label">Total Revenue</div><div class="value" id="kpi-rev">$0</div></div>
  <div class="kpi"><div class="label">Total Units</div><div class="value" id="kpi-units">0</div></div>
  <div class="kpi"><div class="label">Transactions</div><div class="value" id="kpi-tx">0</div></div>
  <div class="kpi"><div class="label">Avg Order Value</div><div class="value" id="kpi-aov">$0</div></div>
</div>
<div class="grid">
  <div class="card"><h3>🏆 Revenue by Product</h3><div id="c-product" class="chart"></div></div>
  <div class="card"><h3>🌍 Revenue by Region</h3><div id="c-region" class="chart"></div></div>
  <div class="card"><h3>📈 Daily Revenue Trend</h3><div id="c-trend" class="chart"></div></div>
  <div class="card"><h3>👤 Sales Rep Performance</h3><div id="c-rep" class="chart"></div></div>
  <div class="card"><h3>💰 Avg Order Value by Category</h3><div id="c-category" class="chart"></div></div>
  <div class="card"><h3>🔍 Unit Price vs Units Sold</h3><div id="c-scatter" class="chart"></div></div>
</div>
<div class="insights"><h3>💡 Key Business Insights</h3><ul id="insightList"></ul></div>
<script>
var RAW_DATA = {js_data};
var COLS = {json.dumps(cols)};
document.getElementById('kpi-rev').textContent = '$' + RAW_DATA.reduce((s,r)=>s+Number(r.Revenue||0),0).toLocaleString();
document.getElementById('kpi-units').textContent = RAW_DATA.reduce((s,r)=>s+Number(r['Units Sold']||0),0).toLocaleString();
document.getElementById('kpi-tx').textContent = RAW_DATA.length.toLocaleString();
var aov = RAW_DATA.reduce((s,r)=>s+Number(r.Revenue||0),0) / RAW_DATA.length;
document.getElementById('kpi-aov').textContent = '$' + (isNaN(aov)?'0':aov.toFixed(2));

function agg(data, dim, metric) {{
  var m = {{}}; data.forEach(function(r){{ var k=r[dim]; m[k]=(m[k]||0)+Number(r[metric]||0); }});
  var e = Object.entries(m).sort(function(a,b){{return b[1]-a[1]}});
  return {{labels:e.map(function(x){{return x[0]}}), values:e.map(function(x){{return x[1]}})}};
}}
function aggAvg(data, dim, metric) {{
  var m={{}}, c={{}}; data.forEach(function(r){{ var k=r[dim]; m[k]=(m[k]||0)+Number(r[metric]||0); c[k]=(c[k]||0)+1; }});
  var e = Object.entries(m).map(function(x){{return [x[0], x[1]/c[x[0]]]}}).sort(function(a,b){{return b[1]-a[1]}});
  return {{labels:e.map(function(x){{return x[0]}}), values:e.map(function(x){{return x[1]}})}};
}}

var barLayout = {{margin:{{t:30,b:60,l:60,r:20}},paper_bgcolor:'#1e293b',plot_bgcolor:'#1e293b',font:{{color:'#94a3b8'}},xaxis:{{tickangle:-30,color:'#94a3b8'}},yaxis:{{color:'#94a3b8'}}}};

var byProd = agg(RAW_DATA, 'Product', 'Revenue');
Plotly.newPlot('c-product', [{{type:'bar', x:byProd.labels, y:byProd.values, marker:{{color:'#3b82f6'}}}}], Object.assign({{}},barLayout,{{title:'Revenue by Product'}}));

var byReg = agg(RAW_DATA, 'Region', 'Revenue');
Plotly.newPlot('c-region', [{{
  type:'pie', labels:byReg.labels, values:byReg.values,
  marker:{{colors:['#3b82f6','#10b981','#f59e0b','#a855f7']}},
  textinfo:'label+percent', textposition:'outside'
}}], Object.assign({{}},barLayout,{{title:'Revenue by Region',showlegend:false}}));

var dateCol = RAW_DATA.map(function(r){{return r.Date}}).filter(Boolean);
var dateGroups = {{}};
RAW_DATA.forEach(function(r){{ var d=r.Date; if(!d)return; dateGroups[d]=(dateGroups[d]||0)+Number(r.Revenue||0); }});
var dateKeys = Object.keys(dateGroups).sort();
var dateVals = dateKeys.map(function(d){{return dateGroups[d]}});
Plotly.newPlot('c-trend', [{{type:'scatter', mode:'lines+markers', x:dateKeys, y:dateVals, line:{{color:'#10b981'}}, marker:{{color:'#10b981'}}}}], Object.assign({{}},barLayout,{{title:'Revenue Trend'}}));

var byRep = agg(RAW_DATA, 'Sales Rep', 'Revenue');
Plotly.newPlot('c-rep', [{{type:'bar', x:byRep.labels, y:byRep.values, marker:{{color:'#a855f7'}}}}], Object.assign({{}},barLayout,{{title:'Sales Rep Performance'}}));

var byCat = aggAvg(RAW_DATA, 'Category', 'Revenue');
Plotly.newPlot('c-category', [{{type:'bar', x:byCat.labels, y:byCat.values, marker:{{color:'#f59e0b'}}}}], Object.assign({{}},barLayout,{{title:'Avg Order Value by Category'}}));

Plotly.newPlot('c-scatter', [{{type:'scatter', mode:'markers', x:RAW_DATA.map(function(r){{return r['Unit Price']}}), y:RAW_DATA.map(function(r){{return r['Units Sold']}}), marker:{{color:'#3b82f6', size:8, opacity:0.7}}}}], Object.assign({{}},barLayout,{{title:'Unit Price vs Units Sold'}}));

// Plotly click handlers for cross-filtering
['c-product','c-region','c-rep','c-category','c-trend','c-scatter'].forEach(function(id) {{
  var el = document.getElementById(id);
  if(el && el.on) el.on('plotly_click', function(d) {{
    var pt = d.points[0];
    var val = pt.x || pt.label || pt.pointNumber;
    if(val !== undefined) alert('Clicked: ' + val);
  }});
}});
</script>
</body>
</html>"""
    
    Path(args.output).write_text(html, encoding="utf-8")
    chart_count = html.count("Plotly.newPlot")
    print(f"\nSaved: {args.output} ({len(html)} bytes, {chart_count} Plotly charts)")
    print("No LLM agent needed — data is deterministic.")

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""data_dashboard.py — Drive dashboard and Q&A from CSV + companion .skill.md"""

import re, json, base64
from pathlib import Path
from typing import Optional

import pandas as pd


# ──────────────────────────────────────────────
#  SKILL PARSER
# ──────────────────────────────────────────────

def parse_skill(skill_path: str) -> dict:
    """Parse SKILL.md into structured dict: frontmatter, sections, tables."""
    text = Path(skill_path).read_text(encoding="utf-8")
    result = {"frontmatter": {}, "sections": {}, "tables": {}, "raw": text}

    # Extract YAML frontmatter
    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).strip().split("\n"):
            if ": " in line and not line.startswith("  "):
                k, v = line.split(": ", 1)
                result["frontmatter"][k.strip()] = v.strip().strip("'\"")
        text = text[fm_match.end():].strip()

    # Extract ## sections
    sections = re.split(r"\n## ", text)
    for sec in sections:
        if not sec.strip():
            continue
        lines = sec.strip().split("\n")
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        result["sections"][title] = body

        # Extract markdown tables
        table_match = re.search(r"\|.*\|.*\|\n\|[-| ]+\|\n((?:\|.*\|.*\|\n?)*)", body)
        if table_match:
            rows = []
            for row in table_match.group(1).strip().split("\n"):
                cells = [c.strip() for c in row.split("|")[1:-1]]
                if cells:
                    rows.append(cells)
            result["tables"][title] = rows

    return result


def _get_column_map(skill: dict) -> dict:
    """Extract {column_name: {type, meaning, ...}} from Column Definitions table."""
    col_map = {}
    if "Column Definitions" not in skill.get("tables", {}):
        return col_map
    rows = skill["tables"]["Column Definitions"]
    # Headers: Column | Type | Meaning | Sample Values | ...
    if not rows:
        return col_map
    headers = [h.lower().strip() for h in rows[0]]
    for row in rows[1:]:
        name = row[0] if len(row) > 0 else ""
        if not name:
            continue
        entry = {"type": row[1] if len(row) > 1 else "", "meaning": row[2] if len(row) > 2 else ""}
        col_map[name.replace("`", "")] = entry
    return col_map


# ──────────────────────────────────────────────
#  CHART GENERATOR
# ──────────────────────────────────────────────



def _question_to_chart(df, question, numeric_cols, cat_cols, col_map, cid):
    """Parse a question and generate the corresponding Plotly chart spec, or None."""
    q = question.lower().strip().strip('"').strip("'")
    
    # Try to find numeric column mentioned in the question
    def _find_num_col():
        for nc in numeric_cols:
            ncl = nc.lower()
            if ncl in q:
                return nc
        return numeric_cols[0] if numeric_cols else None
    
    # Try to find categorical column mentioned
    def _find_cat_col():
        for cc in cat_cols:
            ccl = cc.lower()
            if ccl in q:
                return cc
        return None
    
    num_col = _find_num_col()
    
    # Pattern: correlation / relationship between X and Y
    if "correlat" in q or "relationship" in q or "correlation" in q:
        ncs = numeric_cols[:2] if len(numeric_cols) >= 2 else None
        if ncs:
            return {
                "chart_id": f"chart-{cid}", "title": f"{ncs[0]} vs {ncs[1]}", "type": "scatter",
                "data": [{"type": "scatter", "mode": "markers", "x": df[ncs[0]].tolist(), "y": df[ncs[1]].tolist(), "marker": {"color": "steelblue", "opacity": 0.7, "size": 8}}],
                "layout": {"title": question, "xaxis": {"title": ncs[0]}, "yaxis": {"title": ncs[1]}, "height": 400}
            }
    
    if "average" in q or "mean" in q or "avg" in q:
        cat_col = _find_cat_col()
        if cat_col and num_col:
            grouped = df.groupby(cat_col)[num_col].mean().sort_values(ascending=False).head(15)
            return {
                "chart_id": f"chart-{cid}", "title": f"Average {num_col} by {cat_col}", "type": "bar",
                "data": [{"type": "bar", "x": grouped.index.tolist(), "y": grouped.values.tolist(), "marker": {"color": "seagreen"}}],
                "layout": {"title": question, "xaxis": {"title": cat_col, "tickangle": -30}, "yaxis": {"title": f"Avg {num_col}"}, "height": 400}
            }
    

    # Pattern: trend over time
    if "trend" in q:
        date_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
        if date_cols and num_col:
            try:
                dates = pd.to_datetime(df[date_cols[0]], errors="coerce")
                ts = df.groupby(dates)[num_col].sum().sort_index()
                return {
                    "chart_id": f"chart-{cid}", "title": f"{num_col} over {date_cols[0]}", "type": "line",
                    "data": [{"type": "scatter", "mode": "lines+markers", "x": [str(k.date()) for k in ts.index], "y": ts.values.tolist(), "marker": {"color": "green"}, "line": {"color": "green"}}],
                    "layout": {"title": question, "xaxis": {"title": date_cols[0]}, "yaxis": {"title": num_col}, "height": 400}
                }
            except Exception:
                pass
    
    # Pattern: X by Y (grouped bar chart)
    for group_col in cat_cols:
        gl = group_col.lower()
        if f"by {gl}" in q or f"per {gl}" in q:
            if num_col:
                grouped = df.groupby(group_col)[num_col].sum().sort_values(ascending=False).head(15)
                return {
                    "chart_id": f"chart-{cid}", "title": f"{num_col} by {group_col}", "type": "bar",
                    "data": [{"type": "bar", "x": grouped.index.tolist(), "y": grouped.values.tolist(), "marker": {"color": "coral"}}],
                    "layout": {"title": question, "xaxis": {"title": group_col, "tickangle": -30}, "yaxis": {"title": num_col}, "height": 400}
                }
    
    # Pattern: top N (sort and bar)
    if "top" in q or "highest" in q or "best" in q or "most" in q:
        for group_col in cat_cols:
            gl = group_col.lower()
            if gl in q:
                if num_col:
                    top = df.groupby(group_col)[num_col].sum().nlargest(10)
                    return {
                        "chart_id": f"chart-{cid}", "title": f"Top {group_col} by {num_col}", "type": "bar",
                        "data": [{"type": "bar", "x": top.index.tolist(), "y": top.values.tolist(), "marker": {"color": "coral"}}],
                        "layout": {"title": question, "xaxis": {"title": group_col, "tickangle": -30}, "yaxis": {"title": num_col}, "height": 400}
                    }
                else:
                    # Just top values of categorical
                    top = df[group_col].value_counts().head(10)
                    return {
                        "chart_id": f"chart-{cid}", "title": f"Top {group_col}", "type": "bar",
                        "data": [{"type": "bar", "x": top.index.tolist(), "y": top.values.tolist(), "marker": {"color": "coral"}}],
                        "layout": {"title": question, "xaxis": {"title": group_col, "tickangle": -30}, "yaxis": {"title": "Count"}, "height": 400}
                    }
    
    # Pattern: average / mean (bar chart)
    print(f"  UNMATCHED: {question}")
    return None


def generate_charts(df: pd.DataFrame, skill: dict, questions: list = None) -> list:
    """Generate Plotly charts from questions in companion skill or user input.
    
    Questions are parsed from the skill's Common Analysis Questions section.
    User can also provide custom questions. Falls back to generic charts.
    """
    charts = []
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include="object").columns.tolist()
    col_map = _get_column_map(skill)
    _cid = 0
    
    # Collect questions: from user, or from companion skill
    if not questions:
        raw = skill.get("sections", {}).get("Common Analysis Questions", "")
        questions = []
        for line in raw.split("\n"):
            line = line.strip()
            # Extract quoted questions or numbered questions
            if '"' in line:
                q = line[line.index('"'):]
                q = q.strip('"').strip()
                if q:
                    questions.append(q)
            elif line and (line[0].isdigit() or line.startswith('-')) and len(line) > 5:
                # Remove numbering: "1. question" -> "question"
                q = line.split(".", 1)[-1].strip().strip('"').strip()
                if q and len(q) > 5:
                    questions.append(q)
    
    # Generate charts from questions
    for q in questions:
        chart = _question_to_chart(df, q, numeric_cols, cat_cols, col_map, _cid)
        if chart:
            charts.append(chart)
            _cid += 1
    
    # Fallback: generic charts if no questions matched
    print(f"Questions: {len(questions)}, Charts generated: {len(charts)}")
    if not charts:
        if numeric_cols:
            col = numeric_cols[0]
            charts.append({
                "chart_id": f"chart-{_cid}", "title": f"Distribution of {col}", "type": "histogram",
                "data": [{"type": "histogram", "x": df[col].dropna().tolist(), "marker": {"color": "steelblue"}}],
                "layout": {"title": col, "xaxis": {"title": col}, "yaxis": {"title": "Frequency"}, "height": 400}
            })
            _cid += 1
        if cat_cols:
            col = cat_cols[0]
            top = df[col].value_counts().head(15)
            charts.append({
                "chart_id": f"chart-{_cid}", "title": f"Top {col}", "type": "bar",
                "data": [{"type": "bar", "x": top.index.tolist(), "y": top.values.tolist(), "marker": {"color": "coral"}}],
                "layout": {"title": col, "xaxis": {"title": col, "tickangle": -30}, "yaxis": {"title": "Count"}, "height": 400}
            })
            _cid += 1
        date_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
        if date_cols and len(numeric_cols) >= 1:
            try:
                dates = pd.to_datetime(df[date_cols[0]], errors="coerce")
                ts = df.groupby(dates)[numeric_cols[0]].sum().sort_index()
                charts.append({
                    "chart_id": f"chart-{_cid}", "title": f"{numeric_cols[0]} over {date_cols[0]}", "type": "line",
                    "data": [{"type": "scatter", "mode": "lines+markers", "x": [str(k.date()) for k in ts.index], "y": ts.values.tolist(), "marker": {"color": "green"}, "line": {"color": "green"}}],
                    "layout": {"title": f"Time trend", "xaxis": {"title": date_cols[0]}, "yaxis": {"title": numeric_cols[0]}, "height": 400}
                })
                _cid += 1
            except Exception:
                pass
    
    return charts
def compute_metrics(df: pd.DataFrame, skill: dict) -> dict:
    """Compute key metrics from the data."""
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include="object").columns.tolist()
    col_map = _get_column_map(skill)
    metrics = {
        "shape": {"rows": len(df), "columns": len(df.columns)},
        "columns": [],
        "summaries": {},
        "top_categories": {},
        "correlations": {},
    }

    # Column details
    for col in df.columns:
        entry = {
            "name": col,
            "dtype": str(df[col].dtype),
            "nulls": int(df[col].isna().sum()),
            "meaning": col_map.get(col, {}).get("meaning", ""),
        }
        metrics["columns"].append(entry)

    # Numeric summaries
    for col in numeric_cols:
        metrics["summaries"][col] = {
            "sum": round(float(df[col].sum()), 2),
            "mean": round(float(df[col].mean()), 2),
            "min": round(float(df[col].min()), 2),
            "max": round(float(df[col].max()), 2),
            "median": round(float(df[col].median()), 2),
            "std": round(float(df[col].std()), 2),
        }

    # Top categories
    for col in cat_cols:
        metrics["top_categories"][col] = (
            df[col].value_counts().head(5).to_dict()
        )

    # Correlations
    if len(numeric_cols) >= 2:
        metrics["correlations"] = df[numeric_cols].corr().round(3).to_dict()

    return metrics


# ──────────────────────────────────────────────
#  HTML DASHBOARD
# ──────────────────────────────────────────────

DASHBOARD_CSS = """
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f7fa; color: #2c3e50; }
h1 { margin: 0 0 8px 0; font-size: 22px; }
.subtitle { color: #7f8c8d; font-size: 13px; margin-top: -4px; margin-bottom: 16px; }
.control-bar { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; background: #fff; padding: 14px 20px; border-radius: 10px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.control-bar label { font-size: 13px; color: #34495e; display: flex; align-items: center; gap: 6px; }
.control-bar select { padding: 6px 12px; border: 1px solid #dce4ec; border-radius: 6px; cursor: pointer; background: #fff; font-size: 13px; }
.reset-btn { padding: 6px 14px; background: #ecf0f1; border: 1px solid #dce4ec; border-radius: 6px; cursor: pointer; font-size: 13px; margin-left: auto; }
.reset-btn:hover { background: #d5dbdb; }
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 16px; }
.kpi { background: #fff; padding: 16px; border-radius: 10px; border-left: 4px solid #2E5C8A; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.kpi .label { font-size: 11px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 0.5px; }
.kpi .value { font-size: 22px; font-weight: 700; margin-top: 4px; color: #2E5C8A; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
.card { background: #fff; padding: 16px; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 0; }
.card h3 { margin: 0 0 8px 0; font-size: 14px; color: #34495e; }
.chart-box { width: 100%; height: 380px; }
.section { margin-bottom: 2rem; }
.section h2 { border-bottom: 2px solid #2E5C8A; padding-bottom: 0.5rem; margin-bottom: 1rem; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #eee; }
th { background: #f5f7fa; font-weight: 600; }
.insight-box { background: #fff; padding: 16px 20px; border-radius: 10px; border-left: 4px solid #2ca02c; margin-top: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.insight-box h3 { margin: 0 0 8px 0; font-size: 14px; }
.insight-box ul { margin: 0; padding-left: 20px; font-size: 13px; line-height: 1.7; color: #34495e; }
pre { background: #f5f7fa; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.9rem; }
.biz-card { background: #f0f7ff; padding: 12px 16px; border-radius: 8px; margin-bottom: 8px; font-size: 13px; }
.biz-card strong { color: #2E5C8A; }
.sql-block { background: #f5f7fa; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem; }
@media (max-width: 768px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } .grid { grid-template-columns: 1fr; } }
"""

def generate_dashboard(csv_path: str, skill_path: str, output_path: str) -> str:
    """Generate a standalone HTML dashboard."""
    df = pd.read_csv(csv_path)
    skill = parse_skill(skill_path)
    col_map = _get_column_map(skill)
    charts = generate_charts(df, skill)
    metrics = compute_metrics(df, skill)
    name = Path(csv_path).stem

    # Business logic from companion
    biz_logic = skill.get("sections", {}).get("Business Logic", "")
    common_questions = skill.get("sections", {}).get("Common Analysis Questions", "")
    sample_sql = skill.get("sections", {}).get("Sample SQL", "")

    # Build sections
    col_rows = ""
    for col in metrics["columns"]:
        col_rows += f"<tr><td>{col['name']}</td><td>{col['dtype']}</td>"
        col_rows += f"<td>{col['meaning']}</td><td>{col['nulls']}</td></tr>"

    metric_cards = ""
    for col_name, summ in metrics["summaries"].items():
        metric_cards += "<div class='metric'>"
        metric_cards += f"<div class='value'>{summ['sum']:,}</div>"
        metric_cards += f"<div class='label'>Total {col_name}</div>"
        metric_cards += f"<div style='font-size:0.8rem;color:#999;'>avg {summ['mean']} / min {summ['min']} / max {summ['max']}</div>"
        metric_cards += "</div>"

    chart_html = ""
    chart_scripts = ""
    chart_count = len(charts)
    for c in charts:
        _json_enc = __import__("json")
        _data = _json_enc.dumps(c["data"])
        _layout = _json_enc.dumps(c["layout"])
        cid = c["chart_id"]
        chart_html += "<div class='card'><h3>" + c["title"] + "</h3><div id='" + cid + "' class='chart-box'></div></div>"
        chart_scripts += "Plotly.newPlot('" + cid + "', " + _data + ", " + _layout + ");" + chr(10)
        
    # Build data as JS array for client-side filtering
    _js_rows = []
    for _, row in df.iterrows():
        _vals = []
        for col in df.columns:
            v = row[col]
            if pd.isna(v):
                _vals.append("null")
            elif isinstance(v, (int, float)):
                _vals.append(str(v))
            else:
                _vals.append('"' + str(v).replace('"', '\\"') + '"')
        _js_rows.append("[" + ",".join(_vals) + "]")
    js_data = "var allData = [\\n" + ",".join(_js_rows) + "\\n];"
    js_col_names = "var colNames = " + _json_enc.dumps(list(df.columns)) + ";"
    
    # Build filter controls
    cat_cols_filter = [c for c in df.columns if df[c].dtype == "object" or str(df[c].dtype) == "category"]
    filter_html = ""
    for fc in cat_cols_filter:
        _vals = sorted(df[fc].dropna().unique().tolist())
        _opts = "<option value='all'>All</option>"
        for _v in _vals:
            _opts += "<option value='" + str(_v).replace("'", "\\'") + "'>" + str(_v) + "</option>"
        filter_html += "<label>" + fc + ": <select id='filter-" + fc + "' onchange='applyFilters()'>" + _opts + "</select></label>"
    filter_html += "<button class='reset-btn' onclick='resetFilters()'>\u21BB Reset</button>"
    
    # Build KPI cards based on numeric columns
    kpi_html = ""
    _numeric = df.select_dtypes(include="number").columns.tolist()
    for nci, nc in enumerate(_numeric[:4]):
        _total = df[nc].sum()
        _label = nc
        meaning = col_map.get(nc, {}).get("meaning", "")
        if meaning:
            _label += " (" + meaning + ")"
        kpi_html += "<div class='kpi'><div class='label'>Total " + nc + "</div><div class='value kpi-" + nc.replace(" ", "_") + "'>" + "{:,.2f}".format(_total) + "</div></div>"
    
    # Business logic section (from companion)
    biz_logic = skill.get("sections", {}).get("Business Logic", "")
    biz_html = ""
    if biz_logic:
        biz_html = "<div class='section'><h2>Business Context</h2>"
        for _bl in biz_logic.split("\\n"):
            _bls = _bl.strip()
            if _bls and (_bls.startswith("-") or _bls.startswith("*")):
                biz_html += "<div class='biz-card'>" + _bls.lstrip("-* ") + "</div>"
            elif len(_bls) > 10:
                biz_html += "<p>" + _bls + "</p>"
        biz_html += "</div>"
    
    # Sample SQL section
    sample_sql = skill.get("sections", {}).get("Sample SQL", "")
    sql_html = ""
    if sample_sql:
        import re as _sql_re
        sql_html = "<div class='section'><h2>Sample SQL</h2>"
        for _block in _sql_re.findall(r"```sql\\n(.*?)```", sample_sql, _sql_re.DOTALL):
            sql_html += "<pre class='sql-block'>" + _block.strip() + "</pre>"
        sql_html += "</div>"
    
    desc = skill.get("frontmatter", {}).get("description", f"Dashboard for {name}")

    html = f"""<!DOCTYPE html>
<html lang='en'>
<head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>
<title>{name} — Data Dashboard</title>
<style>{DASHBOARD_CSS}</style>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head>
<body>
<div class='header'><h1>{name}</h1><p>{desc}</p></div>
<div class='container'>
<div class='section'>
  <h2>Data Profile</h2>
  <div class='metric-grid'>
    <div class='metric'><div class='value'>{metrics['shape']['rows']:,}</div><div class='label'>Rows</div></div>
    <div class='metric'><div class='value'>{metrics['shape']['columns']}</div><div class='label'>Columns</div></div>
    <div class='metric'><div class='value'>{len([c for c in metrics['columns'] if 'float' in c['dtype'] or 'int' in c['dtype']])}</div><div class='label'>Numeric</div></div>
  </div>
  <div class='card'><div class='card-header'>Columns</div>
  <div class='card-body'><table><tr><th>Column</th><th>Type</th><th>Meaning</th><th>Nulls</th></tr>{col_rows}</table></div></div>
</div>
<div class='section'><h2>Key Metrics</h2><div class='metric-grid'>{metric_cards}</div></div>
<div class='section'><h2>Charts</h2><div class='chart-grid'>{chart_html}</div></div>
{biz_html}
{qa_html}
{sql_html}
</div><script>{chart_scripts}</script></body></html>"""

    Path(output_path).write_text(html, encoding="utf-8")
    print(f"Dashboard saved: {output_path}")
    return output_path


# ──────────────────────────────────────────────
#  Q&A ENGINE
# ──────────────────────────────────────────────

def _md_to_html(md: str) -> str:
    """Minimal markdown-to-HTML for simple formatting."""
    html = md
    html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"`(.*?)`", r"<code>\1</code>", html)
    html = re.sub(r"^- (.*)", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*?</li>\n)+", lambda m: f"<ul>{m.group(0)}</ul>", html, flags=re.DOTALL)
    return html.replace("\n", "<br>")


def answer_query(csv_path: str, skill_path: str, query: str) -> dict:
    """Answer a natural language query about the data."""
    df = pd.read_csv(csv_path)
    skill = parse_skill(skill_path)
    col_map = _get_column_map(skill)
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    cat_cols = df.select_dtypes(include="object").columns.tolist()
    q = query.lower().strip()

    # ── Pattern 1: "total / sum of {column}"
    for col in numeric_cols:
        col_lower = col.lower()
        if f"total {col_lower}" in q or f"sum of {col_lower}" in q or f"sum {col_lower}" in q:
            val = df[col].sum()
            meaning = col_map.get(col, {}).get("meaning", "")
            return {"query": query, "answer": f"Total {col} ({meaning}): **{val:,.2f}**" if meaning else f"Total {col}: **{val:,.2f}**", "data": {"column": col, "value": round(float(val), 2), "metric": "sum"}}

    # ── Pattern 2: "average / mean of {column}"
    for col in numeric_cols:
        col_lower = col.lower()
        if f"average {col_lower}" in q or f"mean {col_lower}" in q or f"avg {col_lower}" in q:
            val = df[col].mean()
            return {"query": query, "answer": f"Average {col}: **{val:,.2f}**", "data": {"column": col, "value": round(float(val), 2), "metric": "mean"}}

    # ── Pattern 3: "{metric} by / per {group}"
    for group_col in cat_cols:
        gl = group_col.lower().strip()
        if f"by {gl}" in q or f"per {gl}" in q:
            for num_col in numeric_cols:
                nl = num_col.lower().strip()
                if nl in q:
                    grouped = df.groupby(group_col)[num_col].sum().sort_values(ascending=False)
                    top = grouped.head(5)
                    lines = [f"**{group_col}** → **{num_col}**:"]
                    for idx, val in top.items():
                        lines.append(f"  - {idx}: {val:,.2f}")
                    return {"query": query, "answer": "\n".join(lines), "data": {"groupby": group_col, "column": num_col, "top": top.to_dict()}}

    # ── Pattern 4: "top {N}"
    m = re.search(r"top\s+(\d+)\s+(.*)", q)
    if m:
        n = int(m.group(1))
        rest = m.group(2).strip()
        for group_col in cat_cols:
            gl = group_col.lower()
            if gl in rest:
                for num_col in numeric_cols:
                    nl = num_col.lower()
                    if nl in rest:
                        top = df.groupby(group_col)[num_col].sum().nlargest(n)
                        lines = [f"Top {n} **{group_col}** by **{num_col}**:"]
                        for idx, val in top.items():
                            lines.append(f"  - {idx}: {val:,.2f}")
                        return {"query": query, "answer": "\n".join(lines), "data": {"groupby": group_col, "column": num_col, "top": top.to_dict()}}

        # Fallback: top N of a categorical column
        for col in cat_cols:
            if col.lower() in rest:
                top = df[col].value_counts().head(n)
                lines = [f"Top {n} **{col}**:"]
                for idx, val in top.items():
                    lines.append(f"  - {idx}: {val}")
                return {"query": query, "answer": "\n".join(lines), "data": {"column": col, "top": top.to_dict()}}

    # ── Pattern 5: "trend over time"
    date_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
    if date_cols and "trend" in q:
        for num_col in numeric_cols:
            nl = num_col.lower()
            if nl in q or ("trend" in q and numeric_cols):
                nl = numeric_cols[0]
            try:
                dates = pd.to_datetime(df[date_cols[0]], errors="coerce")
                ts = df.groupby(dates)[num_col].sum().sort_index()
                lines = [f"**{num_col}** trend over **{date_cols[0]}**:"]
                for d, v in ts.items():
                    lines.append(f"  - {d.date()}: {v:,.2f}")
                return {"query": query, "answer": "\n".join(lines), "data": {"date_col": date_cols[0], "column": num_col, "values": {str(k.date()): round(float(v), 2) for k, v in ts.items()}}}
            except Exception:
                pass

    # ── Pattern 6: Check against companion's Common Questions
    common_q = skill.get("sections", {}).get("Common Analysis Questions", "")
    if common_q:
        for line in common_q.split("\n"):
            line_stripped = line.strip().strip('"').strip("'")
            if line_stripped and len(line_stripped) > 10:
                # Check if query matches a common question pattern
                q_words = set(q.split())
                cq_words = set(line_stripped.lower().split())
                overlap = len(q_words & cq_words)
                if overlap >= 3 and overlap / max(len(q_words), len(cq_words)) > 0.3:
                    # Try to answer using the patterns above (recursive call with simplified query)
                    simplified = line_stripped.lower()
                    result = _try_pattern_answer(df, numeric_cols, cat_cols, col_map, simplified)
                    if result:
                        return {"query": query, "matched_question": line_stripped, "answer": result, "note": "Matched from Common Analysis Questions"}

    # ── Fallback: general info
    return {"query": query, "answer": f"I can answer questions about this dataset ({', '.join(df.columns)}). Try asking about totals, averages, trends, or groupings.", "type": "help"}


def _try_pattern_answer(df, numeric_cols, cat_cols, col_map, q: str) -> Optional[str]:
    """Try answering a simplified query using patterns, return text or None."""
    for col in numeric_cols:
        cl = col.lower()
        if f"total {cl}" in q or f"sum {cl}" in q:
            return f"Total {col}: {df[col].sum():,.2f}"
        if f"average {cl}" in q or f"avg {cl}" in q:
            return f"Average {col}: {df[col].mean():,.2f}"

    for group_col in cat_cols:
        gl = group_col.lower().strip()
        if f"by {gl}" in q or f"per {gl}" in q:
            for num_col in numeric_cols:
                nl = num_col.lower().strip()
                if nl in q:
                    grouped = df.groupby(group_col)[num_col].sum().sort_values(ascending=False)
                    top = grouped.head(5)
                    lines = [f"{group_col} → {num_col}:"]
                    for idx, val in top.items():
                        lines.append(f"  {idx}: {val:,.2f}")
                    return "\n".join(lines)
    return None

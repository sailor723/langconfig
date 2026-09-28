#!/usr/bin/env python3
"""Generate a database ERD dashboard (self-contained HTML) from a live SQLite DB.

Why this exists: the hand-maintained Sun Hing ERD drifted from the database —
12 of its 16 tables had wrong or missing columns (invented column names that
would break any SQL written from it). This generator derives everything from
the live schema, so the ERD can never disagree with the DB again.

What it derives (nothing is hand-written):
  - tables + row counts
  - columns: name, type, NOT NULL, default, PRIMARY KEY
  - relationships: DECLARED foreign keys (PRAGMA foreign_key_list) plus
    INFERRED star-schema links (a column whose name matches the primary key of
    a dimension table, e.g. kpi_id -> dim_kpi.kpi_id, company_id -> company.id)
  - table classification: raw_* = RAW, dim_*/company = DIM, fact_* = FACT
  - up to 3 sample rows per table (truncated)
  - KPI coverage matrix when dim_kpi / fact_kpi_monthly are present

Usage:
  cd backend && .venv/bin/python scripts/gen_erd.py \
      --db ../data/analysis_dbs/sunhing_kpi.db \
      --out ../data/analysis_dbs/sunhing_erd.html \
      --title "Sun Hing — Database ER Diagram" \
      --meta-db "data/analysis_dbs/sunhing_kpi.db" \
      --skills sunhing-analyst --entry detail --backup

The LangConfig Analysis panel reads the `LangConfig Dashboard Meta` comment in
the <head>, so --meta-db/--skills/--entry keep the dashboard wiring intact.
"""
from __future__ import annotations

import argparse
import html as _html
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ── Schema introspection ──────────────────────────────────────────────────

def _classify(table: str) -> str:
    if table.startswith("raw_"):
        return "RAW"
    if table.startswith("fact_"):
        return "FACT"
    if table.startswith("dim_") or table == "company":
        return "DIM"
    return "OTHER"


def introspect(db_path: str) -> Dict[str, Any]:
    """Read tables, columns, constraints, relationships and samples."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        names = [
            r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        tables: Dict[str, Dict[str, Any]] = {}
        pk_by_table: Dict[str, Optional[str]] = {}

        for name in names:
            cols = []
            for c in con.execute(f'PRAGMA table_info("{name}")'):
                cols.append({
                    "name": c["name"],
                    "type": (c["type"] or "").upper(),
                    "notnull": bool(c["notnull"]),
                    "default": c["dflt_value"],
                    "pk": bool(c["pk"]),
                })
            pk_cols = [c["name"] for c in cols if c["pk"]]
            pk_by_table[name] = pk_cols[0] if len(pk_cols) == 1 else None
            declared = [
                {"column": fk["from"], "ref_table": fk["table"], "ref_column": fk["to"]}
                for fk in con.execute(f'PRAGMA foreign_key_list("{name}")')
            ]
            try:
                count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.Error:
                count = None
            sample = []
            try:
                for row in con.execute(f'SELECT * FROM "{name}" LIMIT 3'):
                    sample.append({k: row[k] for k in row.keys()})
            except sqlite3.Error:
                pass
            tables[name] = {
                "name": name,
                "class": _classify(name),
                "columns": cols,
                "pk": pk_cols,
                "declared_fks": declared,
                "row_count": count,
                "sample": sample,
            }

        # Inferred star-schema links: a column named like a dimension's PK.
        dim_pks = {
            t: pk_by_table[t] for t in names
            if _classify(t) == "DIM" and pk_by_table.get(t)
        }
        rels: List[Dict[str, str]] = []
        for name, t in tables.items():
            declared_cols = {fk["column"] for fk in t["declared_fks"]}
            for fk in t["declared_fks"]:
                rels.append({
                    "from_table": name, "from_column": fk["column"],
                    "to_table": fk["ref_table"], "to_column": fk["ref_column"],
                    "kind": "declared",
                })
            for dim, dim_pk in dim_pks.items():
                if dim == name or dim_pk in declared_cols:
                    continue
                if any(c["name"] == dim_pk for c in t["columns"]):
                    rels.append({
                        "from_table": name, "from_column": dim_pk,
                        "to_table": dim, "to_column": dim_pk,
                        "kind": "inferred",
                    })
        return {"tables": tables, "relationships": rels, "pk_by_table": pk_by_table}
    finally:
        con.close()


# ── Rendering helpers ─────────────────────────────────────────────────────

_CSS = """
:root{--navy:#0B2344;--navy-mid:#1A3A5C;--gold:#B5935A;--gold-l:#D4AF70;
--slate:#4A5568;--mid:#718096;--line:#E2E8F0;--bg:#F7F8FA;--card:#FFFFFF;
--raw:#2563EB;--dim:#0F766E;--fact:#B45309;--other:#6B7280;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:var(--bg);color:var(--navy);font-size:14px;line-height:1.5}
header{background:var(--navy);color:#fff;padding:22px 28px}
header h1{font-size:20px;font-weight:700;letter-spacing:.02em}
header .sub{color:#B8C4D6;font-size:12.5px;margin-top:6px}
header code{background:rgba(255,255,255,.12);padding:1px 6px;border-radius:4px;font-size:12px}
main{padding:22px 28px 60px;max-width:1500px;margin:0 auto}
.summary{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:132px}
.stat .n{font-size:22px;font-weight:700}
.stat .l{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mid)}
.stat.raw .n{color:var(--raw)}.stat.dim .n{color:var(--dim)}.stat.fact .n{color:var(--fact)}
h2{font-size:15px;margin:26px 0 12px;padding-bottom:7px;border-bottom:2px solid var(--gold);display:inline-block}
.toolbar{margin:14px 0 8px}
.toolbar input{width:320px;padding:7px 10px;border:1px solid var(--line);border-radius:7px;font-size:13px;outline:none}
.toolbar input:focus{border-color:var(--gold)}
.diagram{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px;overflow:auto}
.legend{display:flex;gap:18px;font-size:12px;color:var(--mid);margin:8px 2px 0}
.legend b{font-weight:600}
.legend .k{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
table.grid{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:12.5px}
table.grid th{background:#EEF1F6;text-align:left;padding:7px 9px;font-weight:600;font-size:11.5px;color:var(--slate);white-space:nowrap}
table.grid td{padding:6px 9px;border-top:1px solid var(--line);vertical-align:top}
tr.hidden{display:none}
.badge{display:inline-block;font-size:10px;font-weight:700;padding:1px 6px;border-radius:10px;letter-spacing:.04em}
.b-RAW{background:#E7EEFF;color:var(--raw)}.b-DIM{background:#E2F4F1;color:var(--dim)}
.b-FACT{background:#FDF0DC;color:var(--fact)}.b-OTHER{background:#EEF0F2;color:var(--other)}
.tag{font-size:10px;padding:1px 5px;border-radius:4px;background:#F1F3F7;color:var(--slate);margin-right:3px}
.tag.pk{background:#FFF4D6;color:#8A6A1F;font-weight:700}
.tag.fk{background:#E4EDFF;color:#2C4E9A}
.tag.declared{background:#DCFCE7;color:#166534}
.tag.inf{background:#F3E8FF;color:#6B21A8}
.mono{font-family:"SF Mono",Menlo,monospace;font-size:11.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:12px;overflow:hidden}
.card>.hd{display:flex;align-items:center;gap:9px;padding:9px 13px;border-bottom:1px solid var(--line);background:#FBFCFD}
.card>.hd .nm{font-weight:700;font-size:13.5px}
.card>.hd .rc{font-size:11.5px;color:var(--mid);margin-left:auto}
.card .body{padding:10px 13px 13px}
.samples{margin-top:9px;overflow:auto;border:1px solid var(--line);border-radius:7px}
.samples table{width:100%;border-collapse:collapse;font-size:11.5px}
.samples th{background:#F5F7FA;padding:5px 7px;text-align:left;color:var(--slate);white-space:nowrap}
.samples td{padding:4px 7px;border-top:1px solid var(--line);white-space:nowrap;max-width:260px;overflow:hidden;text-overflow:ellipsis}
.note{font-size:11.5px;color:var(--mid);margin-top:7px;font-style:italic}
footer{border-top:1px solid var(--line);margin-top:34px;padding-top:12px;font-size:11.5px;color:var(--mid)}
"""


def _esc(v: Any) -> str:
    return _html.escape("" if v is None else str(v), quote=True)


def _fmt_cell(v: Any, limit: int = 60) -> str:
    if v is None:
        return '<span style="color:#9AA5B1">NULL</span>'
    s = str(v)
    if len(s) > limit:
        s = s[:limit] + "…"
    return _esc(s)


def _diagram_svg(tables: Dict[str, Dict[str, Any]], rels: List[Dict[str, str]]) -> Tuple[str, int]:
    """Three-column layout (RAW | DIM | FACT) with straight connector lines."""
    col_x = {"RAW": 30, "DIM": 470, "FACT": 910}
    box_w, head_h, row_h, pad = 400, 30, 17, 16
    order = ["RAW", "DIM", "FACT", "OTHER"]
    pos: Dict[str, Tuple[int, int, int]] = {}   # table -> (x, y, height)
    y_cursor = {c: 60 for c in order}

    for cls in order:
        for name in sorted(t for t, d in tables.items() if d["class"] == cls):
            t = tables[name]
            keys = [c for c in t["columns"] if c["pk"]]
            fk_cols = [r for r in rels if r["from_table"] == name]
            shown = keys + [c for c in t["columns"] if any(r["from_column"] == c["name"] for r in fk_cols) and not c["pk"]]
            height = head_h + row_h * max(1, len(shown)) + 6
            x = col_x.get(cls, 30)
            pos[name] = (x, y_cursor[cls], height)
            y_cursor[cls] += height + pad

    total_h = max(y_cursor.values()) + 30
    parts: List[str] = [
        f'<svg width="1360" height="{total_h}" viewBox="0 0 1360 {total_h}" '
        'xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,Segoe UI,sans-serif">',
        '<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#94A3B8"/></marker></defs>',
    ]
    for cls, label in (("RAW", "RAW — event / detail tables"),
                       ("DIM", "DIM — dimensions (incl. monthly aggregates)"),
                       ("FACT", "FACT — KPI measures")):
        parts.append(
            f'<text x="{col_x[cls]}" y="34" font-size="13" font-weight="700" fill="#4A5568">{label}</text>'
        )
    # connector lines first (behind the boxes)
    for r in rels:
        if r["from_table"] not in pos or r["to_table"] not in pos:
            continue
        fx, fy, fh = pos[r["from_table"]]
        tx, ty, th = pos[r["to_table"]]
        fy_c = fy + fh - 9
        ty_c = ty + th / 2
        if fx < tx:      # child left of parent
            x1, x2 = fx + box_w, tx
        elif fx > tx:
            x1, x2 = fx, tx + box_w
        else:
            continue
        mid = (x1 + x2) / 2
        dash = '' if r["kind"] == "declared" else ' stroke-dasharray="4 3"'
        parts.append(
            f'<path d="M {x1} {fy_c} C {mid} {fy_c}, {mid} {ty_c}, {x2} {ty_c}" fill="none" '
            f'stroke="#94A3B8" stroke-width="1.2"{dash} marker-end="url(#arw)"/>'
        )
    # boxes
    fills = {"RAW": "#EFF5FF", "DIM": "#E9F7F4", "FACT": "#FEF6E9", "OTHER": "#F3F4F6"}
    strokes = {"RAW": "#2563EB", "DIM": "#0F766E", "FACT": "#B45309", "OTHER": "#6B7280"}
    for name, (x, y, h) in pos.items():
        t = tables[name]
        cls = t["class"]
        parts.append(f'<rect x="{x}" y="{y}" width="{box_w}" height="{h}" rx="8" fill="{fills[cls]}" stroke="{strokes[cls]}" stroke-width="1.1"/>')
        parts.append(f'<text x="{x + 11}" y="{y + 20}" font-size="12.5" font-weight="700" fill="#0B2344">{_esc(name)}</text>')
        parts.append(f'<text x="{x + box_w - 11}" y="{y + 20}" font-size="10.5" fill="#718096" text-anchor="end">{t["row_count"]} rows</text>')
        keys = [c["name"] for c in t["columns"] if c["pk"]]
        fk_names = [r["from_column"] for r in rels if r["from_table"] == name]
        labels = ["PK " + k for k in keys] + ["FK " + f for f in fk_names if f not in keys]
        yy = y + head_h + 6
        for lab in labels:
            color = "#8A6A1F" if lab.startswith("PK") else "#2C4E9A"
            parts.append(f'<text x="{x + 14}" y="{yy + 9}" font-size="10.5" font-family="monospace" fill="{color}">{_esc(lab)}</text>')
            yy += row_h
        if not labels:
            parts.append(f'<text x="{x + 14}" y="{yy + 9}" font-size="10.5" fill="#9AA5B1">(no key columns)</text>')
    parts.append("</svg>")
    return "".join(parts), total_h


def _render_table_card(t: Dict[str, Any], rels: List[Dict[str, str]]) -> str:
    fk_map = {r["from_column"]: r for r in rels if r["from_table"] == t["name"]}
    rows = []
    for c in t["columns"]:
        tags = []
        if c["pk"]:
            tags.append('<span class="tag pk">PK</span>')
        if c["name"] in fk_map:
            r = fk_map[c["name"]]
            kind = "declared" if r["kind"] == "declared" else "inf"
            tags.append(f'<span class="tag fk">FK → {_esc(r["to_table"])}.{_esc(r["to_column"])}</span>')
            tags.append(f'<span class="tag {kind}">{kind}</span>')
        if c["notnull"]:
            tags.append('<span class="tag">NOT NULL</span>')
        if c["default"] is not None:
            tags.append(f'<span class="tag">DEFAULT {_esc(c["default"])}</span>')
        rows.append(
            f'<tr><td class="mono">{_esc(c["name"])}</td><td class="mono">{_esc(c["type"])}</td>'
            f'<td>{" ".join(tags) or "—"}</td></tr>'
        )
    cols_html = (
        '<table class="grid"><thead><tr><th>column</th><th>type</th><th>constraints / references</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )
    samples_html = ""
    if t["sample"]:
        keys = list(t["sample"][0].keys())
        head = "".join(f"<th>{_esc(k)}</th>" for k in keys)
        body = "".join(
            "<tr>" + "".join(f"<td>{_fmt_cell(r.get(k))}</td>" for k in keys) + "</tr>"
            for r in t["sample"]
        )
        samples_html = (
            '<div class="samples"><table><thead><tr>'
            f'{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<div class="note">first {len(t["sample"])} row(s) — sample data</div>'
        )
    return (
        f'<div class="card" data-table="{_esc(t["name"])}">'
        f'<div class="hd"><span class="badge b-{t["class"]}">{t["class"]}</span>'
        f'<span class="nm mono">{_esc(t["name"])}</span>'
        f'<span class="rc">{t["row_count"]} rows · {len(t["columns"])} columns</span></div>'
        f'<div class="body">{cols_html}{samples_html}</div></div>'
    )


def build_html(db_path: str, model: Dict[str, Any], title: str,
               meta_db: str, skills: str, entry: str, mode: str,
               kpi_rows: List[Dict[str, Any]]) -> str:
    tables = model["tables"]
    rels = model["relationships"]
    counts = {"RAW": 0, "DIM": 0, "FACT": 0, "OTHER": 0}
    total_rows = 0
    for t in tables.values():
        counts[t["class"]] += 1
        total_rows += t["row_count"] or 0
    declared = sum(1 for r in rels if r["kind"] == "declared")
    inferred = len(rels) - declared
    total_cols = sum(len(t["columns"]) for t in tables.values())

    svg, _h = _diagram_svg(tables, rels)

    kpi_html = ""
    if kpi_rows:
        body = "".join(
            f'<tr><td class="mono">{_esc(r["kpi_id"])}</td><td>{_esc(r["roe_factor"])}</td>'
            f'<td class="mono">{_esc(r["target"])}</td><td class="mono">{_esc(r["kpi_type"])}</td>'
            f'<td class="mono">{_esc(r["periods"])}</td>'
            f'<td>{"declared" if r.get("has_formula") else "<span style=\'color:#B45309\'>no formula</span>"}</td></tr>'
            for r in kpi_rows
        )
        kpi_html = (
            "<h2>KPI definitions → fact coverage</h2>"
            '<table class="grid"><thead><tr><th>kpi_id</th><th>ROE factor</th><th>target</th>'
            "<th>type</th><th>fact periods present</th><th>dim_kpi.formula</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )

    meta_lines = ["<!--", "  LangConfig Dashboard Meta", f"  db: {meta_db}"]
    if skills:
        meta_lines.append(f"  skills: {skills}")
    if mode:
        meta_lines.append(f"  Mode: {mode}")
    if entry:
        meta_lines.append(f"  entry: {entry}")
    meta_lines.append("-->")
    meta = "\n".join(meta_lines) + "\n"
    rel_rows = "".join(
        f'<tr><td class="mono">{_esc(r["from_table"])}.{_esc(r["from_column"])}</td>'
        f'<td class="mono">→ {_esc(r["to_table"])}.{_esc(r["to_column"])}</td>'
        f'<td><span class="tag {r["kind"] if r["kind"]=="declared" else "inf"}">{r["kind"]}</span></td></tr>'
        for r in rels
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
{meta}<title>{_esc(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <h1>{_esc(title)}</h1>
  <div class="sub">Generated from the live schema of <code>{_esc(db_path)}</code>
  · {len(tables)} tables · {total_cols} columns · {len(rels)} relationships
  ({declared} declared, {inferred} inferred) · {total_rows:,} rows
  · {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</header>
<main>
  <div class="summary">
    <div class="stat raw"><div class="n">{counts['RAW']}</div><div class="l">RAW tables</div></div>
    <div class="stat dim"><div class="n">{counts['DIM']}</div><div class="l">DIM tables</div></div>
    <div class="stat fact"><div class="n">{counts['FACT']}</div><div class="l">FACT tables</div></div>
    <div class="stat"><div class="n">{len(tables)}</div><div class="l">total tables</div></div>
    <div class="stat"><div class="n">{total_rows:,}</div><div class="l">total rows</div></div>
  </div>

  <h2>Relationship diagram (derived from the schema)</h2>
  <div class="diagram">{svg}</div>
  <div class="legend">
    <span><span class="k" style="background:#2563EB"></span>RAW — event/detail grain</span>
    <span><span class="k" style="background:#0F766E"></span>DIM — dimensions / monthly aggregates</span>
    <span><span class="k" style="background:#B45309"></span>FACT — KPI measures</span>
    <span><b>solid</b> = declared FK (PRAGMA foreign_key_list)</span>
    <span><b>dashed</b> = inferred star-schema link (column matches a dimension PK)</span>
  </div>

  <h2>Relationships</h2>
  <table class="grid"><thead><tr><th>child column</th><th>parent</th><th>kind</th></tr></thead>
  <tbody>{rel_rows or '<tr><td colspan="3">none</td></tr>'}</tbody></table>

  {kpi_html}

  <h2>Tables</h2>
  <div class="toolbar"><input id="q" type="search" placeholder="filter tables / columns…"></div>
  <div id="cards">
  {''.join(_render_table_card(tables[n], rels) for n in sorted(tables))}
  </div>

  <footer>
    This ERD is generated by <span class="mono">backend/scripts/gen_erd.py</span> — every table, column,
    constraint, row count and relationship is read from the live database at generation time.
    Re-run the script after any schema change; do not hand-edit this file.
  </footer>
</main>
<script>
var q = document.getElementById('q');
q.addEventListener('input', function () {{
  var term = q.value.trim().toLowerCase();
  document.querySelectorAll('#cards .card').forEach(function (card) {{
    var hit = !term || card.textContent.toLowerCase().indexOf(term) !== -1;
    card.style.display = hit ? '' : 'none';
  }});
}});
</script>
</body>
</html>"""


def kpi_matrix(db_path: str) -> List[Dict[str, Any]]:
    """dim_kpi rows + which fact periods exist (and whether a formula is set)."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"dim_kpi", "fact_kpi_monthly"} <= tables:
            return []
        has_formula = any(c[1] == "formula" for c in con.execute("PRAGMA table_info(dim_kpi)"))
        out = []
        for r in con.execute("SELECT * FROM dim_kpi ORDER BY kpi_id"):
            d = dict(r)
            periods = con.execute(
                "SELECT COUNT(*) AS n, MIN(period) AS mn, MAX(period) AS mx "
                "FROM fact_kpi_monthly WHERE kpi_id = ?", (d["kpi_id"],)
            ).fetchone()
            out.append({
                "kpi_id": d.get("kpi_id"),
                "roe_factor": d.get("roe_factor"),
                "target": d.get("target"),
                "kpi_type": d.get("kpi_type"),
                "periods": f'{periods["n"]} ({periods["mn"]}…{periods["mx"]})' if periods["n"] else "0",
                "has_formula": bool((d.get("formula") or "").strip()) if has_formula else False,
            })
        return out
    except sqlite3.Error:
        return []
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate an ERD dashboard from a live SQLite DB")
    ap.add_argument("--db", required=True, help="Path to the SQLite database")
    ap.add_argument("--out", required=True, help="Path of the HTML file to write")
    ap.add_argument("--title", default=None, help="Page title (default: derived from filename)")
    ap.add_argument("--meta-db", default=None, help="db: value for the LangConfig meta block")
    ap.add_argument("--skills", default="", help="skills: value for the meta block")
    ap.add_argument("--entry", default="", help="entry: value for the meta block (omit to list the dashboard in the Analysis panel)")
    ap.add_argument("--mode", default="", help="optional Mode: value for the meta block")
    ap.add_argument("--backup", action="store_true", help="Back up an existing --out file first")
    args = ap.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    if not db_path.exists():
        print(f"✗ database not found: {db_path}")
        return 1
    out_path = Path(args.out).expanduser().resolve()
    if args.backup and out_path.exists():
        bak = out_path.parent / "_backup" / (out_path.stem + ".pre-regen.html")
        shutil.copy2(out_path, bak)
        print(f"· backed up existing ERD → {bak}")

    model = introspect(str(db_path))
    title = args.title or f"ERD — {db_path.stem}"
    html_doc = build_html(
        db_path=str(db_path),
        model=model,
        title=title,
        meta_db=args.meta_db or str(db_path),
        skills=args.skills,
        entry=args.entry,
        mode=args.mode,
        kpi_rows=kpi_matrix(str(db_path)),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")

    counts = {"RAW": 0, "DIM": 0, "FACT": 0, "OTHER": 0}
    for t in model["tables"].values():
        counts[t["class"]] += 1
    declared = sum(1 for r in model["relationships"] if r["kind"] == "declared")
    print(f"✓ {out_path}")
    print(f"  tables: {len(model['tables'])} (raw={counts['RAW']}, dim={counts['DIM']}, "
          f"fact={counts['FACT']}, other={counts['OTHER']})")
    print(f"  relationships: {len(model['relationships'])} ({declared} declared, "
          f"{len(model['relationships']) - declared} inferred)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

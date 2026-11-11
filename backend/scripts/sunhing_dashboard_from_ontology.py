#!/usr/bin/env python3
"""Render the Sun Hing multi-page cockpit — hub + one page per ROE factor — FROM THE ONTOLOGY.

Why this exists
    The 2026-11 pages in `data/analysis_dbs/` were produced by a hand-written generator that read
    the SQLite copy directly. The same numbers are now declared as ontology metrics (`sunhing_v1`),
    so the pages can be re-rendered from the declaration instead of from a script that knows the
    schema. The LAYOUT is the original one, copied value-for-value: `templates/sunhing/hub.css` and
    `factor.css` are the original `<style>` blocks verbatim, and every element class below appears in
    the original pages with the same nesting.

What it will not do
    * It does not read `fact_kpi_monthly` for a displayed value. Values come from `run_metric`; the
      fact table is read only to CHECK the ontology (`[VALUE]` lines) — a disagreement is printed,
      never silently resolved in the page's favour.
    * It does not invent a number for a KPI the ontology does not answer. `kpi_map.json` says which
      KPI maps to which metric; a `null` metric is a refusal the page shows with its reason, and a
      metric that is not declared fails the run by name.
    * It does not reproduce the original hub's ROE slider simulation. That block multiplied three
      factors by hand-picked weights with no declaration behind them; this version keeps the visual
      band and prints the measured factor values instead of a model nobody declared.

    python sunhing_dashboard_from_ontology.py                     # render into data/analysis_dbs/ontology/
    python sunhing_dashboard_from_ontology.py --check             # values only, no files, exit != 0 on a problem
    python sunhing_dashboard_from_ontology.py --out /tmp/pages    # somewhere else
    python sunhing_dashboard_from_ontology.py --json              # the payload the pages were built from

Exit codes
    0  every mapped metric answered and agreed with the fact table
    1  something the page would have shown as a number is missing or disagrees (printed by name)
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import pathlib
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
FEATURE = REPO / "backend" / "features" / "ontology"
COMPILER = FEATURE / "compiler"
TEMPLATES = REPO / "backend" / "scripts" / "templates" / "sunhing"
DEFAULT_PROFILE = FEATURE / "profiles" / "sunhing_v1" / "sunhing_v1_settings.json"
DEFAULT_MAP = FEATURE / "profiles" / "sunhing_v1" / "kpi_map.json"
DEFAULT_OUT = REPO / "data" / "analysis_dbs"

# The ontology's unit vocabulary (metrics_ext.ttl) ↔ the catalogue's (dim_kpi.unit). The VALUE is
# formatted from the ontology, the TARGET from the catalogue, and the two families must agree —
# when they do not, the page says so instead of printing two numbers under one heading.
ONTOLOGY_UNIT = {
    "percent": ("pct", "{:.1f}%"),
    "count": ("count", "{:.0f}"),
    "money_wan": ("money", "{:.1f} 万"),
    "ratio": ("ratio", "{:.2f}x"),
    "score_1_10": ("score", "{:.2f}"),
    "score_0_10": ("score", "{:.2f}"),
    "score_0_100": ("score", "{:.1f}"),
}
CATALOGUE_UNIT = {
    "%": ("pct", "{:.1f}%"),
    "events": ("count", "{:.0f}"),
    "万元": ("money", "{:.1f} 万"),
    "ratio": ("ratio", "{:.2f}x"),
    "points": ("score", "{:.1f}"),
    "score(1-10)": ("score", "{:.1f}"),
    "score(0-100)": ("score", "{:.1f}"),
}

LINE_COLOUR = {"met": "#2ca02c", "near": "#ff7f0e", "miss": "#e74c3c"}
# page.dupont → the headline entry that carries that factor's raw value
DUPONT_METRIC = {"net_profit_margin": "margin", "asset_turnover": "turnover",
                 "equity_multiplier": "multiplier"}
TARGET_COLOUR = "#e74c3c"
PLOTLY = "https://cdn.plot.ly/plotly-2.35.2.min.js"


# --------------------------------------------------------------------------- the ontology

def _compiler():
    """Point the compiler at ONE profile and return (profile, graph, cursor, run_metric, _meta)."""
    for path in (COMPILER, FEATURE):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import ontology_profile          # noqa: PLC0415  (path set up above)
    import run_dashboard as rd       # noqa: PLC0415
    import sqlgen                    # noqa: PLC0415

    return ontology_profile, sqlgen, rd


class Ontology:
    def __init__(self, settings: pathlib.Path):
        mod, sqlgen, rd = _compiler()
        mod.use(settings)
        self.graph = sqlgen.load()
        self.declared = dict(sqlgen.metrics(self.graph))
        self._rd = rd
        self.conn = rd._conn()
        self.cur = self.conn.cursor()

    def meta(self, name: str) -> dict:
        return self._rd._meta(self.graph, name)

    def label(self, name: str) -> str | None:
        return self._rd.metric_label(self.graph, name)

    def run(self, name: str) -> dict:
        return self._rd.run_metric(self.cur, self.graph, name)

    def value(self, name: str) -> tuple[float | None, str | None, dict]:
        """One number from one declared metric. Returns (value, problem, meta)."""
        meta = self.meta(name)
        if not meta.get("declared"):
            return None, f"no metric :{name} declared in this ontology", meta
        res = self.run(name)
        if not res.get("ok"):
            return None, res.get("refused") or res.get("status"), meta
        rows = res.get("rows") or []
        if len(rows) != 1 or len(rows[0]) != 1:
            return None, f"expected 1 row × 1 column, got {len(rows)} row(s) — a snapshot metric is not a series", meta
        val = rows[0][0]
        if val is None:
            return None, "the metric answered NULL", meta
        return float(val), None, meta

    def series(self, name: str) -> tuple[list[tuple[str, float]], str | None, dict]:
        """A declared time series as [(period, value)] sorted by period."""
        meta = self.meta(name)
        if not meta.get("declared"):
            return [], f"no metric :{name} declared", meta
        res = self.run(name)
        if not res.get("ok"):
            return [], res.get("refused") or res.get("status"), meta
        rows = res.get("rows") or []
        if not rows or len(rows[0]) != 2:
            return [], f"expected key+value columns, got {res.get('columns')}", meta
        out = []
        for key, value in rows:
            if value is None:
                continue
            out.append((str(key), float(value)))
        out.sort(key=lambda kv: kv[0])
        return out, None, meta

    def catalogue(self) -> dict[str, dict]:
        self.cur.execute(
            "SELECT kpi_id, kpi_name, unit, target, lower_is_better, roe_factor FROM dim_kpi"
        )
        names = [d[0] for d in self.cur.description]
        return {row[0]: dict(zip(names, row)) for row in self.cur.fetchall()}

    def fact_series(self) -> dict[str, dict[str, float]]:
        """{kpi_id: {period: actual}} — the landed monthly values, for CHECKING a series."""
        self.cur.execute(
            "SELECT kpi_id, period, actual FROM fact_kpi_monthly"
        )
        out: dict[str, dict[str, float]] = {}
        for kpi, period, actual in self.cur.fetchall():
            out.setdefault(kpi, {})[str(period)] = (
                float(actual) if actual is not None else None)
        return out

    def fact(self, period: str) -> dict[str, float]:
        """The landed values, ONLY to check the ontology against them."""
        self.cur.execute(
            "SELECT kpi_id, actual FROM fact_kpi_monthly WHERE period = %s", (period,)
        )
        return {row[0]: (float(row[1]) if row[1] is not None else None) for row in self.cur.fetchall()}


# --------------------------------------------------------------------------- formatting

def fmt_value(value: float | None, unit: str | None) -> str:
    if value is None:
        return "—"
    spec = ONTOLOGY_UNIT.get(unit or "", (None, "{:.2f}"))
    return spec[1].format(value)


def fmt_target(target: float | None, unit: str | None) -> str:
    if target is None:
        return "—"
    spec = CATALOGUE_UNIT.get(unit or "", (None, "{:.2f}"))
    return spec[1].format(target)


CATALOGUE_TO_ONTOLOGY = {
    "%": "percent",
    "events": "count",
    "万元": "money_wan",
    "ratio": "ratio",
    "points": "score_0_100",
    "score(1-10)": "score_1_10",
    "score(0-100)": "score_0_100",
}


def fmt_gap(gap: float | None, unit: str | None) -> str:
    """The shortfall, in the KPI's own unit (it is computed from value and target, which share one)."""
    if gap is None:
        return "—"
    spec = ONTOLOGY_UNIT.get(CATALOGUE_TO_ONTOLOGY.get(unit or "", ""), (None, "{:.2f}"))[1]
    return ("+" if gap > 0 else "") + spec.format(gap)


def families(unit: str | None, table: dict) -> str | None:
    return table.get(unit or "", (None, None))[0]


def judge(value: float | None, target: float | None, direction: str, near_ratio: float
          ) -> tuple[str, float | None, float | None]:
    """(status, shortfall, normalised score 0–100). `shortfall` > 0 means *short of target*."""
    if value is None or target is None:
        return "unknown", None, None
    shortfall = (target - value) if direction == "higher" else (value - target)
    if shortfall <= 0:
        return "met", shortfall, 100.0
    if target == 0:
        return "miss", shortfall, 0.0
    span = abs(target)
    score = max(0.0, min(100.0, 100.0 * (1.0 - shortfall / span)))
    status = "near" if shortfall <= near_ratio * span else "miss"
    return status, shortfall, score


def grade(score: float | None) -> tuple[str, str]:
    if score is None:
        return "C", "KPI等级 —"
    if score >= 90:
        return "A", "KPI等级 A"
    if score >= 75:
        return "B", "KPI等级 B"
    return "C", "KPI等级 C"


def esc(text) -> str:
    return html.escape(str(text), quote=False)


def js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# --------------------------------------------------------------------------- data assembly

def build_payload(onto: Ontology, mapping: dict, *, verbose: bool = True) -> dict:
    """Everything the pages need, plus a list of problems. No HTML here."""
    period = mapping["observation_period"]
    near_ratio = float(mapping.get("near_miss_ratio", 0.1))
    suffix = mapping.get("series_suffix", "ByMonth")
    overrides = mapping.get("direction_overrides") or {}

    catalogue = onto.catalogue()
    fact = onto.fact(period)
    fact_series = onto.fact_series()
    problems: list[str] = []
    notes: list[str] = []

    rows = []
    for entry in mapping["kpis"]:
        kpi_id = entry["kpi_id"]
        cat = catalogue.get(kpi_id)
        if cat is None:
            problems.append(f"[CATALOGUE] {kpi_id} is in kpi_map.json but not in dim_kpi")
            cat = {"kpi_name": kpi_id, "unit": None, "target": None,
                   "lower_is_better": 0, "roe_factor": entry.get("page")}
        number, _, name = kpi_id.partition("_")
        direction = "lower" if overrides.get(kpi_id) else ("lower" if cat["lower_is_better"] else "higher")
        metric = entry.get("metric")

        row = {
            "kpi_id": kpi_id,
            "number": number,
            "name": cat["kpi_name"].lstrip("_"),
            "page": entry["page"],
            "factor": cat["roe_factor"],
            "unit": cat["unit"],
            "target": float(cat["target"]) if cat["target"] is not None else None,
            "direction": direction,
            "direction_overridden": bool(overrides.get(kpi_id)),
            "metric": metric,
            "no_series": bool(entry.get("no_series")),
            "no_series_why": entry.get("no_series_why") if entry.get("no_series") else None,
            "note": entry.get("note"),
            "refusal": entry.get("refusal"),
            "value": None,
            "ontology_unit": None,
            "series": [],
            "series_metric": None,
            "status": "unknown",
            "shortfall": None,
            "score": None,
        }

        if metric:
            value, problem, meta = onto.value(metric)
            row["ontology_unit"] = meta.get("unit")
            if problem:
                problems.append(f"[METRIC] {kpi_id} → :{metric} — {problem}")
            row["value"] = value
            if value is not None:
                landed = fact.get(kpi_id)
                if landed is None:
                    notes.append(f"[VALUE] {kpi_id} has no {period} row in fact_kpi_monthly")
                elif abs(landed - value) > 0.005:
                    problems.append(
                        f"[VALUE] {kpi_id} → :{metric} = {value:.6g} but fact_kpi_monthly "
                        f"@ {period} = {landed:.6g} (Δ {value - landed:+.6g})"
                    )
            fam_onto = families(row["ontology_unit"], ONTOLOGY_UNIT)
            fam_cat = families(row["unit"], CATALOGUE_UNIT)
            if fam_onto and fam_cat and fam_onto != fam_cat:
                problems.append(
                    f"[UNIT] {kpi_id} → :{metric} is {row['ontology_unit']} but dim_kpi.unit is "
                    f"{row['unit']}: the value and the target are not the same kind of number"
                )
            series_metric = entry.get("series") or (metric + suffix)
            row["series_metric"] = series_metric
            if series_metric in onto.declared:
                series, problem, _ = onto.series(series_metric)
                row["series"] = series
                if problem:
                    problems.append(f"[SERIES] {kpi_id} → :{series_metric} — {problem}")
            else:
                notes.append(f"[NO-SERIES] {kpi_id} → :{series_metric} is not declared "
                             f"(snapshot only; the page prints that instead of a chart)")
            row["status"], row["shortfall"], row["score"] = judge(
                value, row["target"], direction, near_ratio)
            # A 6-point line whose six points are equal is not a trend. Say WHY with evidence: if
            # the landed fact column is equally flat, the source has no monthly grain for this KPI
            # and the series is a snapshot tiled across periods — the reader must not read it as
            # "unchanged performance".
            values = [v for _, v in row["series"]]
            if len(values) >= 2 and len({round(v, 4) for v in values}) == 1:
                landed = [fact_series.get(kpi_id, {}).get(p) for p, _ in row["series"]]
                landed = [v for v in landed if v is not None]
                same_as_fact = landed and len({round(v, 4) for v in landed}) == 1
                row["series_flat"] = {
                    "value": values[0],
                    "why": ("六期同值，且库里 fact_kpi_monthly 也是同一个值平铺 6 期 —— 源表没有这条 KPI 的期间粒度，"
                            "曲线不是趋势，是快照按期间平铺" if same_as_fact else
                            "六期同值；库里 fact_kpi_monthly 的六期并不是同一个值，这条需要人来看"),
                }
                if not same_as_fact:
                    notes.append(f"[SERIES-FLAT] {kpi_id} → :{series_metric} 六期同值，但 fact 六期不同 —— 需要判断是口径还是数据")

        rows.append(row)

    headline = {}
    for key, decl in (mapping.get("headline") or {}).items():
        if not isinstance(decl, dict) or "metric" not in decl:
            headline[key] = dict(decl or {})
            continue
        value, problem, meta = onto.value(decl["metric"])
        if problem:
            notes.append(f"[HEADLINE] {key} → :{decl['metric']} — {problem}")
        series, sproblem, _ = (onto.series(decl["series"]) if decl.get("series") else ([], None, {}))
        headline[key] = {**decl, "value": value, "unit": meta.get("unit"),
                         "series": series, "series_problem": sproblem}

    summary = {}
    for key, decl in (mapping.get("summary") or {}).items():
        if isinstance(decl, str):
            decl = {"metric": decl}
        if decl.get("derive"):
            a, b = decl["derive"]
            va, pa, ma = onto.value(a)
            vb, pb, mb = onto.value(b)
            for name, problem in ((a, pa), (b, pb)):
                if problem:
                    notes.append(f"[SUMMARY] {key} ← :{name} — {problem}")
            value = (va - vb) if (va is not None and vb is not None) else None
            summary[key] = {"metric": f"{a} − {b}", "value": value, "unit": ma.get("unit"),
                            "label": decl.get("label")}
        else:
            value, problem, meta = onto.value(decl["metric"])
            if problem:
                notes.append(f"[SUMMARY] {key} → :{decl['metric']} — {problem}")
            summary[key] = {"metric": decl["metric"], "value": value, "unit": meta.get("unit"),
                            "label": decl.get("label")}

    # A KNOWN defect that has been written down is a note with a reason, not a silent pass. The
    # accepted entry keeps the finding (the page still shows the two disagreeing numbers) and only
    # stops it from failing the run — the reason lives in kpi_map.json, next to the mapping.
    accepted: list[str] = []
    declared_ok = mapping.get("accepted_issues") or {}
    if declared_ok:
        def _accepted(line: str) -> str | None:
            for kpi, why in declared_ok.items():
                kinds = why.get("kinds") or []
                if kpi in line and any(f"[{kind}]" in line for kind in kinds):
                    return why.get("why") or ""
            return None
        keep_problems = []
        for line in problems:
            why = _accepted(line)
            if why is None:
                keep_problems.append(line)
            else:
                accepted.append(f"{line}  [ACCEPTED] {why}")
        problems = keep_problems
        keep_notes = []
        for line in notes:
            why = _accepted(line)
            if why is None:
                keep_notes.append(line)
            else:
                accepted.append(f"{line}  [ACCEPTED] {why}")
        notes = keep_notes

    payload = {
        "period": period,
        "profile": mapping.get("profile"),
        "payload_rows": rows,
        "headline": headline,
        "summary": summary,
        "pages": mapping["pages"],
        "hub_file": mapping.get("hub_file") or "sunhing_ontology_hub.html",
        "problems": problems,
        "accepted": accepted,
        "notes": notes,
        "near_ratio": near_ratio,
    }
    if verbose:
        for line in problems:
            print(line)
        for line in accepted:
            print(line)
        for line in notes:
            print(line)
    return payload


# --------------------------------------------------------------------------- HTML

def _meta_block(entry: str, title: str, payload: dict | None = None) -> str:
    """The `LangConfig Dashboard Meta` comment the Analysis panel reads.

    Without it the page is an orphan: `api/analysis/dashboards` reports no db/skills/entry, the
    panel groups it by filename prefix, and `_pick_home` cannot see it as a hub — which is why the
    curated registry kept opening the 2026-09 hub and the new cockpit looked like "one more page".
    The format is matched by regex in `api/analysis/routes.py`; keep `db:` identical to the pages it
    lives beside so both generations stay in ONE database card.
    """
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        "<!--\n"
        f"  Generated: {stamp} | Source: sunhing_kpi | Mode: static-embed\n"
        "  LangConfig Dashboard Meta\n"
        "  db: data/analysis_dbs/sunhing_kpi.db\n"
        "  skills: sunhing-analyst\n"
        "  mode: static-embed\n"
        f"  entry: {entry}\n"
        f"  title: {title}\n"
        "  study: sunhing-transformation\n"
        f"  ontology: {(payload or {}).get('profile') or 'sunhing_v1'}\n"
        "-->\n"
    )


def _doc(title: str, css: pathlib.Path, body: str, script: str = "", *,
         meta: str = "") -> str:
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        + meta
        + "<meta charset=\"utf-8\">\n"
        f"<title>{esc(title)}</title>\n<script src=\"{PLOTLY}\"></script>\n<style>\n"
        + css.read_text(encoding="utf-8")
        + "</style>\n</head>\n<body>\n"
        + body
        + (f"\n<script>\n{script}</script>\n" if script else "")
        + "</body>\n</html>\n"
    )


#: Pages from the 2026-09 generation that this renderer does not produce. They are linked from the
#: hub under a labelled group so the app's one entry page still reaches them — and the label says
#: which data generation they show, because their numbers are the other dataset.
LEGACY_PAGES = [
    ("员工明细（2026-09 数据）", "sunhing_dashboard_employees.html"),
    ("历史负债追缴（2026-09 数据）", "sunhing_dashboard_liability.html"),
    ("原始数据表（2026-09 数据）", "sunhing_dashboard_data.html"),
    ("PMO 甘特（2026-09 数据）", "sunhing_gantt.html"),
    ("ERD（2026-09 数据）", "sunhing_erd.html"),
    ("研究介绍（2026-09 数据）", "sunhing_intro_cn.html"),
]


def _nav(pages: list[dict], current: str | None, extra: list[tuple[str, str]] | None = None,
         *, legacy: bool = False) -> str:
    """Absolute /api/files/... hrefs, as the original pages used.

    Relative hrefs also work when the file is opened straight off disk, but the Analysis panel
    frames these pages at `<API>/api/files/...` and the panel's own comment records the day a
    relative link resolved against the wrong origin. Absolute is the convention every other
    dashboard in this folder follows.
    """
    items = []
    for page in pages:
        cls = ' class="active"' if page["id"] == current else ""
        items.append(f'<a href="/api/files/{esc(page["file"])}"{cls}>{esc(page["nav"])}</a>')
    for label, href in (extra or []):
        href = href if href.startswith("/") else f"/api/files/{href}"
        items.append(f'<a href="{esc(href)}">{esc(label)}</a>')
    if legacy:
        items.append('<span style="opacity:.6;padding:6px 10px">|</span>')
        for label, href in LEGACY_PAGES:
            items.append(f'<a href="/api/files/{esc(href)}" style="opacity:.75">{esc(label)}</a>')
    return '  <div class="nav-links">\n    ' + "\n    ".join(items) + "\n  </div>\n"


def _status_label(status: str) -> tuple[str, str, str]:
    """(css class, hub label, factor-page label) — the original used 达标/关注 and Met/Near Miss."""
    return {
        "met": ("met", "达标", "✅ Met"),
        "near": ("miss", "关注", "⚠️ Near Miss"),
        "miss": ("miss", "关注", "❌ Miss"),
        "unknown": ("miss", "未定义", "未定义"),
    }[status]


def _kpi_card(row: dict) -> str:
    cls, hub_label, page_label = _status_label(row["status"])
    card = "ok" if cls == "met" else ("warn" if row["status"] == "near" else "danger")
    value = fmt_value(row["value"], row["ontology_unit"])
    target = fmt_target(row["target"], row["unit"])
    if row["value"] is None:
        note = "本体未给出该指标" if row.get("refusal") else "本体未注册该指标"
    elif row["status"] == "met":
        note = f"Target {target} ✅ Met"
    elif row["status"] == "near":
        note = f"Target {target} △ {fmt_gap(row['shortfall'], row['unit']).lstrip('+')} gap"
    else:
        note = f"Target {target} ❌ Miss"
    return (
        f'    <div class="kpi-card {card}"><div class="label">{esc(row["number"])} {esc(row["name"])}</div>'
        f'<div class="value">{esc(value)}</div><div class="note">{esc(note)}</div></div>\n'
    )


def _chart_card(row: dict) -> tuple[str, str]:
    """One chart card + its Plotly call. A KPI without a declared series gets a stated reason."""
    cid = f"c{row['number']}"
    title = f'{row["number"]}_{row["name"]}'
    if row["value"] is None:
        why = row.get("refusal") or "本体未注册该指标"
        return (
            f'    <div class="card"><div class="chart-title">{esc(title)}</div>'
            f'<div class="chart" style="display:flex;align-items:center;justify-content:center;'
            f'color:#999;font-size:13px;line-height:1.7;text-align:left;padding:0 28px">'
            f'<div><strong style="color:#c0392b">没有图：本体不回答这个数。</strong><br>{esc(why)}</div>'
            f'</div></div>\n',
            "",
        )
    if not row["series"]:
        why_snapshot = (
            f'这条 KPI 只有快照，没有月度序列：{row["no_series_why"]}'
            if row.get("no_series_why") else
            f'本体尚未声明 <code>:{esc(row["series_metric"])}</code>（快照只有一期读数）')
        return (
            f'    <div class="card"><div class="chart-title">{esc(title)}</div>'
            f'<div class="chart" style="display:flex;align-items:center;justify-content:center;'
            f'color:#999;font-size:13px;line-height:1.7;text-align:left;padding:0 28px">'
            f'<div><strong style="color:#b8860b">只有快照值，没有按月序列。</strong><br>'
            f'{why_snapshot}；当前月 {esc(fmt_value(row["value"], row["ontology_unit"]))} 是可用读数。</div>'
            f'</div></div>\n',
            "",
        )
    periods = [p for p, _ in row["series"]]
    values = [round(v, 4) for _, v in row["series"]]
    colour = LINE_COLOUR[row["status"]]
    target_line = ", ".join(f"{row['target']}" for _ in periods) if row["target"] is not None else None
    call = f"""
Plotly.newPlot('{cid}', [
  {{ x: {js(periods)}, y: {js(values)}, type: 'scatter', mode: 'lines+markers',
     line: {{ color: '{colour}', width: 3 }} }}
  {',' if target_line else ''}
  {f"""{{ x: {js(periods)}, y: [{target_line}], type: 'scatter', mode: 'lines', name: 'Target',
     line: {{ color: '{TARGET_COLOUR}', width: 1, dash: 'dash' }} }}""" if target_line else ''}
], {{ margin: {{ t: 36, b: 30, l: 40, r: 10 }}, hovermode: 'x unified', showlegend: false }});
"""
    flat = row.get("series_flat")
    caption = (f'<div style="font-size:11px;color:#b8860b;margin-top:-4px">{esc(flat["why"])}</div>'
               if flat else "")
    return (
        f'    <div class="card"><div class="chart-title">{esc(title)}</div>'
        f'<div id="{cid}" class="chart"></div>{caption}</div>\n',
        call,
    )


def _insight_box(rows: list[dict]) -> str:
    met = [r for r in rows if r["status"] == "met"]
    near = [r for r in rows if r["status"] == "near"]
    miss = [r for r in rows if r["status"] == "miss"]
    silent = [r for r in rows if r["value"] is None]
    lines = []
    if met:
        lines.append("<strong>已完成</strong>: " + "、".join(
            f'{esc(r["name"])} ({esc(fmt_value(r["value"], r["ontology_unit"]))})' for r in met))
    for r in sorted(near, key=lambda r: -(r["shortfall"] or 0)):
        lines.append(
            f'<strong>接近达标</strong>: {esc(r["name"])} {esc(fmt_value(r["value"], r["ontology_unit"]))} '
            f'vs {esc(fmt_target(r["target"], r["unit"]))} — 差距 {esc(fmt_gap(r["shortfall"], r["unit"]).lstrip("+"))}')
    if miss:
        worst = max(miss, key=lambda r: (r["shortfall"] or 0) / max(abs(r["target"] or 1), 1e-9))
        lines.append(
            f'<strong>需重点关注</strong>: {esc(worst["name"])} 仅 {esc(fmt_value(worst["value"], worst["ontology_unit"]))} '
            f'vs {esc(fmt_target(worst["target"], worst["unit"]))} — 差距较大')
        rest = [r for r in miss if r is not worst]
        if rest:
            lines.append("<strong>其他未达标</strong>: " + "、".join(
                f'{esc(r["name"])} {esc(fmt_value(r["value"], r["ontology_unit"]))}' for r in rest))
    if silent:
        lines.append("<strong>本体不回答</strong>: " + "、".join(
            f'{esc(r["number"])} {esc(r["name"])}' for r in silent) + " —— 理由写在对应卡片上")
    if not lines:
        lines.append("这一页没有可判读的读数。")
    return ('  <div class="insight-box">\n    <h3>关键洞察</h3>\n    <ul>\n'
            + "".join(f"<li>{line}</li>\n" for line in lines)
            + "    </ul>\n  </div>\n")


def _factor_score(rows: list[dict]) -> tuple[float | None, int, int]:
    """The factor's KPI average score and (met, total) — the meta line of a hub factor card."""
    scored = [r["score"] for r in rows if r["score"] is not None]
    met = sum(1 for r in rows if r["status"] == "met")
    total = len([r for r in rows if r["value"] is not None])
    return (sum(scored) / len(scored) if scored else None), met, total


def render_hub(payload: dict, css: pathlib.Path, mapping: dict) -> str:
    pages = payload["pages"]
    rows = payload["payload_rows"]
    period = payload["period"]
    headline = payload["headline"]
    summary = payload["summary"]

    roe = headline.get("roe") or {}
    baseline = headline.get("baseline_roe") or {}
    base_series = baseline.get("series") or []
    if not base_series:
        for key in ("roe",):
            base_series = (headline.get(key) or {}).get("series") or []
    base_value = base_series[0][1] if base_series else None
    # The hub's time range comes from whatever series the ontology actually answers, so it does not
    # claim a window the declaration cannot fill.
    span_periods = sorted({p for r in rows for p, _ in r["series"]}
                          | {p for p, _ in (roe.get("series") or [])})
    span = f"{span_periods[0]} → {span_periods[-1]}" if span_periods else period

    body = []
    body.append(
        '  <div class="header">\n    <div>\n'
        "      <h1>Sun Hing Vision Group ROE Executive Dashboard</h1>\n"
        f'      <div class="sub">一分为多重组执行驾驶舱 · 主仪表盘以 ROE 因子组织 {len(rows)} 项 KPI · 只读管理视图 · '
        f'数值来自本体 <code>{esc(payload.get("profile") or "")}</code></div>\n    </div>\n'
        '    <div style="font-size:13px;color:var(--gold-light)">'
        "ROE = 净利润率 × 资产周转率 × 权益乘数 · 观察月 " + esc(period) + "</div>\n  </div>\n"
    )
    recovered = headline.get("recovered") or {}
    recovered_label = recovered.get("label") or "追缴已化解"
    recovered_text = fmt_value(recovered.get("value"), recovered.get("unit") or "money_wan")
    body.append(
        '  <div class="baseline-bar">\n'
        f'    <div>时间范围 <span>{esc(span)}</span></div>\n'
        f'    <div>当前观察月 <span>{esc(period)}</span></div>\n'
        f'    <div>基准 ROE <span>{esc(fmt_value(base_value, baseline.get("unit") or "percent"))}</span></div>\n'
        f'    <div>当前 ROE <span>{esc(fmt_value(roe.get("value"), roe.get("unit") or "percent"))}</span></div>\n'
        f'    <div>{esc(recovered_label)} <span>{esc(recovered_text)}</span></div>\n'
        '  </div>\n'
    )
    body.append('<div class="container">\n')
    body.append(_nav(pages, None, legacy=True))

    # .dashboard — the three DuPont factor cards, exactly as the original
    dupont = [p for p in pages if p.get("dupont")]
    cards = []
    for page in dupont:
        rows_p = [r for r in rows if r["page"] == page["id"]]
        avg, met, total = _factor_score(rows_p)
        grade_key, grade_label = grade(avg)
        worst = None
        miss_rows = [r for r in rows_p if r["status"] in ("near", "miss")]
        if miss_rows:
            worst = max(miss_rows, key=lambda r: (r["shortfall"] or 0) / max(abs(r["target"] or 1), 1e-9))
        focus = (
            f'KPI层最弱项：<strong>{esc(worst["name"])}</strong><br>'
            f'低于目标 {esc(fmt_gap(worst["shortfall"], worst["unit"]).lstrip("+"))}'
            if worst else "KPI层最弱项：<strong>无</strong><br>本页全部达标"
        )
        score_text = fmt_value(avg, "percent").replace("%", "") if avg is not None else "—"
        # The original hub printed the DuPont RAW value here (净利润率 2.1%). That number is a metric
        # like any other, so it is printed only when the ontology declares it; until then the big
        # number is the KPI average and the meta line does not claim "DuPont 原始值".
        dupont_metric = DUPONT_METRIC.get(page.get("dupont") or "")
        dupont_decl = (headline.get(dupont_metric) if dupont_metric else None) or {}
        dupont_value = dupont_decl.get("value")
        if dupont_value is not None:
            score_text = fmt_value(dupont_value, dupont_decl.get("unit") or "percent")
            meta_text = (f'DuPont 原始值 · KPI 平均得分 {avg:.1f} · 达标 {met}/{total}'
                         if avg is not None else f'DuPont 原始值 · 达标 {met}/{total}')
        else:
            meta_text = (f'KPI 平均得分 {avg:.1f} · 达标 {met}/{total} · 无 DuPont 快照指标'
                         if avg is not None else f'达标 {met}/{total} · 无 DuPont 快照指标')
        cards.append(
            f'    <div class="factor-card {page["card_class"]}">\n'
            f'      <h3>{esc(page["title"].split(" ", 1)[-1].replace(" Factor Dashboard", ""))}</h3>\n'
            f'      <div class="score">{esc(score_text)}</div>\n'
            f'      <div class="meta">{esc(meta_text)}</div>\n'
            f'      <div><span class="grade-badge grade-{grade_key}">{esc(grade_label)}</span></div>\n'
            f'      <div class="focus">{focus}</div>\n'
            f'    </div>'
        )
    body.append('  <div class="dashboard">\n' + "\n".join(cards) + "\n  </div>\n")

    # .result-bar — the measured factor readings (the original had a hand-weighted simulation here)
    bar = (
        '  <div class="result-bar">\n'
        '    <div style="flex:1">\n'
        '      <div style="font-size:13px;color:var(--gold-light);margin-bottom:4px">'
        "当前 ROE（本体读数，未做加权模拟）</div>\n"
        f'      <div class="roe-value" id="roeDisplay">{esc(fmt_value(roe.get("value"), roe.get("unit") or "percent"))}</div>\n'
        f'      <div style="font-size:12px;color:#94a3b8;margin-top:2px">基准 {esc(fmt_value(base_value, baseline.get("unit") or "percent"))}'
        f' · 观察月 {esc(period)} · 原版的滑块模拟没有口径声明，这一版不重现</div>\n'
        "    </div>\n"
    )
    for page in dupont:
        rows_p = [r for r in rows if r["page"] == page["id"]]
        avg, met, total = _factor_score(rows_p)
        bar += (
            '    <div style="text-align:right;min-width:200px">\n'
            f'      <div style="font-size:11px;color:#94a3b8;line-height:2.0">'
            f'{esc(page["theme"])}<br><strong style="color:var(--gold-light);font-size:16px">'
            f'{esc(f"{avg:.1f}" if avg is not None else "—")}</strong> / 100 · 达标 {met}/{total}</div>\n'
            "    </div>\n"
        )
    bar += "  </div>\n"
    body.append(bar)

    # .summary-bar — the three facts the original boasted, now all from declared metrics
    met_all = sum(1 for r in rows if r["status"] == "met")
    scored_all = [r for r in rows if r["value"] is not None]
    pct = (100.0 * met_all / len(scored_all)) if scored_all else 0.0
    def s(key):
        entry = summary.get(key) or {}
        return fmt_value(entry.get("value"), entry.get("unit"))
    body.append(
        '  <div class="summary-bar">\n'
        f'    <div>最新月总体达标：<span class="total">{met_all}/{len(rows)}</span>'
        f'<span class="warn"> ({pct:.1f}%)</span>'
        f'{"<span>（{} 项本体不回答，不计入）</span>".format(len(rows) - len(scored_all)) if len(scored_all) != len(rows) else ""}'
        f'</div>\n'
        f'    <div>减员完成 <strong>{esc(s("severance_done"))}</strong> / {esc(s("severance_planned"))} · '
        f'赔偿已支出 <strong>{esc(s("severance_paid"))}</strong></div>\n'
        f'    <div>追缴已化解 <strong>{esc(s("liab_resolved"))}</strong> · 剩余 <strong>{esc(s("liab_remaining"))}</strong></div>\n'
        '  </div>\n'
    )

    # .overview-grid — ROE 修复趋势 + 杜邦三联因子得分
    body.append(
        '  <div class="overview-grid">\n'
        '    <div class="card">\n      <h3>ROE 修复趋势</h3>\n'
        '      <div id="roe-trend" class="chart"></div>\n    </div>\n'
        '    <div class="card">\n      <h3>杜邦三联因子得分</h3>\n'
        '      <div id="factor-score" class="chart"></div>\n    </div>\n'
        "  </div>\n"
    )

    # .section × 5 — the 28 KPIs inline, one collapsible section per factor
    for page in pages:
        rows_p = [r for r in rows if r["page"] == page["id"]]
        avg, met, total = _factor_score(rows_p)
        body.append(
            '  <div class="section">\n'
            f'    <div class="section-header {page["card_class"]}" onclick="toggleSection(this)">\n'
            f'      <span>{esc(page.get("section_title") or page["theme"])}</span>\n'
            '      <span class="toggle-icon">▼</span>\n    </div>\n'
            '    <div class="section-body open">\n'
            '      <div class="section-meta">\n'
            f'        <span>查看 {esc(page["nav"].split(" (")[0])} Dashboard · 达标 {met}/{total} · '
            f'平均得分 {esc(f"{avg:.1f}" if avg is not None else "—")}</span>\n'
            f'        <a href="{esc(page["file"])}">打开详情</a>\n      </div>\n'
            '      <div class="kpi-head"><div>#</div><div>指标</div><div>实际</div><div>目标</div>'
            "<div>得分</div><div>状态</div></div>\n"
        )
        for row in rows_p:
            cls, hub_label, _ = _status_label(row["status"])
            score = f'{row["score"]:.1f}' if row["score"] is not None else "—"
            note = row.get("refusal") or row.get("note") or ""
            if not note and row["value"] is not None:
                if row["status"] == "met":
                    while_met = row["shortfall"] or 0.0
                    note = (f'高于目标 {fmt_gap(-while_met, row["unit"]).lstrip("+")}'
                            if while_met < 0 else "刚好达标")
                elif row["shortfall"] is not None:
                    note = f'低于目标 {fmt_gap(row["shortfall"], row["unit"]).lstrip("+")}'
            body.append(
                '      <div class="kpi-row">\n'
                f'        <div class="kpi-id">{esc(row["number"])}</div>\n'
                f'        <div class="kpi-name">{esc(row["name"])}</div>\n'
                f'        <div class="kpi-value">{esc(fmt_value(row["value"], row["ontology_unit"]))}</div>\n'
                f'        <div class="kpi-target">{esc(fmt_target(row["target"], row["unit"]))}</div>\n'
                f'        <div class="kpi-score">{esc(score)}</div>\n'
                f'        <div class="kpi-status {cls}">{esc(hub_label)}</div>\n'
                "      </div>\n"
            )
            if note:
                body.append(f'      <div class="kpi-note">{esc(note)}</div>\n')
        body.append("    </div>\n  </div>\n")

    body.append(_insight_box(rows))
    body.append(
        '  <div class="kpi-note" style="margin-top:18px">'
        f'渲染源：本体 <code>{esc(payload.get("profile") or "")}</code> · 映射 <code>kpi_map.json</code> · '
        f'观察月 {esc(period)} · 由 backend/scripts/sunhing_dashboard_from_ontology.py 生成；'
        "同一份声明同时产出这 6 个页面，改数是改声明，不是改页面。</div>\n"
    )
    body.append("</div>\n")

    roe_series = roe.get("series") or []
    factor_bar = json.dumps(
        [{"short": p["theme"].split(" / ")[0], "score": round(_factor_score([r for r in rows if r["page"] == p["id"]])[0] or 0, 1),
          "accent": p["accent"]} for p in dupont], ensure_ascii=False)
    script = f"""
var roeRows = {js([{"period": p, "roe": round(v, 4)} for p, v in roe_series])};
var factorCards = {factor_bar};

function toggleSection(head) {{
  var body = head.nextElementSibling;
  body.classList.toggle('open');
  var icon = head.querySelector('.toggle-icon');
  if (icon) icon.textContent = body.classList.contains('open') ? '▼' : '▶';
}}

if (roeRows.length) {{
  Plotly.newPlot('roe-trend', [
    {{ x: roeRows.map(function(r) {{ return r.period; }}),
       y: roeRows.map(function(r) {{ return r.roe; }}),
       type: 'scatter', mode: 'lines+markers', name: 'ROE',
       line: {{ color: '#0B2344', width: 3 }}, marker: {{ size: 8 }} }},
    {{ x: roeRows.map(function(r) {{ return r.period; }}),
       y: roeRows.map(function() {{ return 0; }}),
       type: 'scatter', mode: 'lines', name: 'Break-even',
       line: {{ color: '#B5935A', width: 2, dash: 'dash' }} }}
  ], {{ margin: {{ t: 30, b: 40, l: 50, r: 20 }}, hovermode: 'x unified',
        legend: {{ orientation: 'h', y: -0.22 }}, yaxis: {{ ticksuffix: '%' }} }});
}} else {{
  document.getElementById('roe-trend').innerHTML =
    '<div style="padding:24px;color:#999;font-size:13px;line-height:1.7">' +
    '本体尚未声明 ROE 序列指标（<code>:roePctByMonth</code>），所以这里没有趋势线。' +
    '快照 ROE 也未被声明，因此 baseline-bar 里的 ROE 是空的——不是数据缺失，是声明缺失。</div>';
}}

Plotly.newPlot('factor-score', [{{
  x: factorCards.map(function(card) {{ return card.short; }}),
  y: factorCards.map(function(card) {{ return card.score; }}),
  type: 'bar',
  marker: {{ color: factorCards.map(function(card) {{ return card.accent; }}) }},
  text: factorCards.map(function(card) {{ return card.score.toFixed(1); }}),
  textposition: 'outside'
}}], {{ margin: {{ t: 30, b: 60, l: 50, r: 20 }}, yaxis: {{ range: [0, 110] }} }});
"""
    return _doc("Sun Hing Vision Group ROE Executive Dashboard", css, "".join(body), script,
                meta=_meta_block("hub", "Sun Hing 新溢眼镜 · ROE 转型驾驶舱（本体渲染）", payload))


def render_factor_page(payload: dict, page: dict, css: pathlib.Path) -> str:
    rows = [r for r in payload["payload_rows"] if r["page"] == page["id"]]
    period = payload["period"]
    periods = sorted({p for r in rows for p, _ in r["series"]})
    avg, met, total = _factor_score(rows)

    body = ['<div class="container">\n', _nav(payload["pages"], page["id"])]
    body.append(
        f'  <div class="page-title">{esc(page["title"])}</div>\n'
        f'  <div class="page-subtitle">{esc(page["subtitle"])} · 目标/进度读数在本体 <code>'
        f'{esc(payload.get("profile") or "")}</code></div>\n'
    )
    body.append(
        '  <div class="baseline-bar">\n'
        f'    <div>当前主题 <span>{esc(page["theme"])}</span></div>\n'
        f'    <div>观察期 <span>{esc(periods[0] if periods else period)} → {esc(periods[-1] if periods else period)}</span></div>\n'
        f'    <div>当前月 <span>{esc(period)}</span></div>\n'
        f'    <div>达标 <span>{met}/{total}</span></div>\n'
        f'    <div>平均得分 <span>{esc(f"{avg:.1f}" if avg is not None else "—")}</span></div>\n'
        "  </div>\n"
    )

    body.append('  <div class="kpi-row">\n' + "".join(_kpi_card(r) for r in rows) + "  </div>\n")

    # .kpi-table — same columns as the original (#, KPI, <period>, Target, Gap, Status)
    body.append('  <div class="card">\n    <table class="kpi-table">\n'
                f'      <tr><th>#</th><th>KPI</th><th>{esc(period)}</th><th>Target</th><th>Gap</th><th>Status</th></tr>\n')
    for row in rows:
        cls, _, page_label = _status_label(row["status"])
        body.append(
            f'    <tr><td>{esc(row["number"])}</td><td>{esc(row["name"])}</td>'
            f'<td>{esc(fmt_value(row["value"], row["ontology_unit"]))}</td>'
            f'<td>{esc(fmt_target(row["target"], row["unit"]))}</td>'
            f'<td>{esc(fmt_gap(row["shortfall"], row["unit"]))}</td>'
            f'<td class="{cls}">{esc(page_label)}</td></tr>\n'
        )
    body.append("    </table>\n  </div>\n")

    cards, calls = [], []
    for row in rows:
        card, call = _chart_card(row)
        cards.append(card)
        calls.append(call)
    body.append('  <div class="grid">\n' + "".join(cards) + "  </div>\n")
    body.append(_insight_box(rows))
    body.append(
        '  <div class="kpi-note" style="margin-top:18px">'
        f'渲染源：本体 <code>{esc(payload.get("profile") or "")}</code> · 映射 <code>kpi_map.json</code> · '
        f'观察月 {esc(period)} · 由 backend/scripts/sunhing_dashboard_from_ontology.py 生成</div>\n'
    )
    body.append("</div>\n")
    return _doc(page["title"], css, "".join(body), "".join(calls),
                meta=_meta_block("detail", page["title"], payload))


#: The names the 2026-09 generation used. The cockpit is written under BOTH names: the Analysis
#: panel, a bookmark and a hand-typed /api/files/sunhing_dashboard.html all have to land on the
#: same numbers, otherwise "I opened it and nothing changed" is a true statement about a stale file.
LEGACY_NAMES = {
    "hub": "sunhing_dashboard.html",
    "profit": "sunhing_dashboard_profit.html",
    "turnover": "sunhing_dashboard_turnover.html",
    "leverage": "sunhing_dashboard_leverage.html",
    "support": "sunhing_dashboard_support.html",
    "risk": "sunhing_dashboard_risk.html",
}
ARCHIVE = "archive-2026-09-28"


def _archive_once(out: pathlib.Path, name: str) -> pathlib.Path | None:
    """Keep the replaced page before the first overwrite — once, never over an archive.

    A page already rendered by this script carries `ontology:` in its meta; copying that over the
    archive on the second run would replace the only copy of the 2026-09 page.
    """
    target = out / name
    if not target.is_file():
        return None
    if "ontology: sunhing_v1" in target.read_text(encoding="utf-8")[:1200]:
        return None
    keep = out / ARCHIVE
    keep.mkdir(exist_ok=True)
    dst = keep / name
    if dst.exists():
        return None
    shutil.copy2(target, dst)
    return dst


def render_all(payload: dict, out: pathlib.Path, *,
               names: dict[str, str] | None = None, hub_name: str | None = None,
               archive: bool = False) -> list[pathlib.Path]:
    """Render the six pages. `names`/`hub_name` let one payload be written under two naming
    schemes (ontology_* and the 2026-09 legacy names) without duplicating the render."""
    out.mkdir(parents=True, exist_ok=True)
    hub_css = TEMPLATES / "hub.css"
    factor_css = TEMPLATES / "factor.css"
    names = names or {}
    local = dict(payload)
    local["pages"] = [{**page, "file": names.get(page["id"], page["file"])} for page in payload["pages"]]
    local["hub_file"] = hub_name or payload.get("hub_file") or "sunhing_ontology_hub.html"
    written = []
    hub_path = out / local["hub_file"]
    if archive:
        _archive_once(out, local["hub_file"])
    hub_path.write_text(render_hub(local, hub_css, {}), encoding="utf-8")
    written.append(hub_path)
    for page in local["pages"]:
        path = out / page["file"]
        if archive:
            _archive_once(out, page["file"])
        path.write_text(render_factor_page(local, page, factor_css), encoding="utf-8")
        written.append(path)
    return written


# --------------------------------------------------------------------------- publish state

def publish_state(profile: pathlib.Path, key: str | None) -> dict:
    """Where the declaration on disk stands relative to the publish ledger.

    The pages are rendered from the DECLARATION ON DISK. If an edit is staged but not applied, the
    page shows a number the ontology does not yet serve — so the state is printed, not assumed.
    """
    state: dict = {"key": key, "files": {}, "applied": None, "staged": None, "newest": None}
    for path in sorted(profile.parent.glob("*.ttl")):
        state["files"][path.name] = path.stat().st_mtime
    if not key:
        return state
    try:
        if str(REPO / "backend") not in sys.path:
            sys.path.insert(0, str(REPO / "backend"))
        from sqlalchemy import text            # noqa: PLC0415

        from db.database import SessionLocal   # noqa: PLC0415

        db = SessionLocal()
        try:
            rows = db.execute(text(
                # EXTRACT(EPOCH) — not to_char: the column is timestamptz and the session renders
                # it in UTC, so a formatted string compared against a local file mtime is off by the
                # UTC offset (measured: a file written at 21:38 "newer" than an apply at 13:45).
                "SELECT id, status, to_char(updated_at, 'YYYY-MM-DD HH24:MI'), "
                "       EXTRACT(EPOCH FROM updated_at) "
                "FROM ontology_publishes WHERE key = :k ORDER BY updated_at DESC LIMIT 20"
            ), {"k": key}).all()
        finally:
            db.close()
        for row in rows:
            entry = {"id": row[0], "status": row[1], "updated_at": row[2],
                     "epoch": float(row[3]) if row[3] is not None else None}
            state["newest"] = state["newest"] or entry
            if entry["status"] == "applied" and not state["applied"]:
                state["applied"] = entry
            if entry["status"] == "staged" and not state["staged"]:
                state["staged"] = entry
    except Exception as exc:                                    # noqa: BLE001
        state["error"] = f"{type(exc).__name__}: {exc}"
    return state


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE))
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--period", default=None, help="override kpi_map.json observation_period")
    ap.add_argument("--check", action="store_true", help="check the values, write no files")
    ap.add_argument("--json", action="store_true", help="print the payload as JSON")
    ap.add_argument("--also-ontology-names", action="store_true",
                    help="also write the sunhing_ontology_*.html alias set (default: canonical names only)")
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).expanduser().resolve()
    mapping = json.loads(pathlib.Path(args.map).expanduser().read_text(encoding="utf-8"))
    if args.period:
        mapping["observation_period"] = args.period
    mapping.setdefault("summary", {
        "severance_done": {"metric": "hrSeveranceCompletedCumulative", "label": "减员完成"},
        "severance_planned": {"metric": "hrSeverancePlanned", "label": "计划减员"},
        "severance_paid": {"metric": "hrSeverancePaidCumulativeWan", "label": "赔偿已支出"},
        "liab_resolved": {"metric": "liabResolvedWan", "label": "追缴已化解"},
        "liab_remaining": {"derive": ["liabTotalWan", "liabResolvedWan"], "label": "剩余"},
    })
    if not mapping.get("profile"):
        mapping["profile"] = profile.parent.name

    for needed in (profile, TEMPLATES / "hub.css", TEMPLATES / "factor.css"):
        if not needed.exists():
            print(f"[FATAL] missing {needed}", file=sys.stderr)
            return 2

    onto = Ontology(profile)
    state = publish_state(profile, mapping.get("profile"))
    print(f"[PROFILE] {profile}")
    print(f"[PROFILE] 盘上声明：{', '.join(sorted(state['files'])) or '（没有 .ttl）'}")
    applied, staged, newest = state.get("applied"), state.get("staged"), state.get("newest")
    if applied:
        print(f"[PROFILE] 已应用：{applied['id']} @ {applied['updated_at']}")
    elif newest:
        print(f"[PROFILE] 台账里没有 applied 行；最新一行是 {newest['status']} {newest['id']} @ {newest['updated_at']}")
    if staged:
        print(f"[PROFILE] 暂存未应用：{staged['id']} @ {staged['updated_at']}"
              "  ← 页面渲染的是盘上的（暂存）声明，apply 之前它还不等于线上本体")
    if state.get("error"):
        print(f"[PROFILE] 台账读不到：{state['error']}（不影响渲染，但无法判断盘上声明是否已应用）")
    # The declaration on disk is what these pages read. If it is newer than the last apply, the page
    # would show a number the served ontology does not have yet — say so, loudly, every run.
    if applied and state.get("files") and applied.get("epoch"):
        import datetime as _dt
        newest_mtime = max(state["files"].values())
        applied_at = applied["epoch"]
        if newest_mtime > applied_at + 1:

            stamp = _dt.datetime.fromtimestamp(newest_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"[PROFILE] [STAGED-ONLY] 盘上声明（{stamp}）比已应用的那一版（{applied['updated_at']}）新"
                  "  ← 页面渲染的是未应用的声明；要么 apply，要么把声明回退到已应用的状态")
    payload = build_payload(onto, mapping)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    if args.check:
        print(f"\n{'KPI':6s} {'指标':24s} {'值':>12s} {'目标':>10s} {'Gap':>10s} {'状态':6s} 序列")
        for row in payload["payload_rows"]:
            series = f"{len(row['series'])} 点" if row["series"] else (
                "—" if row["value"] is None else "无（快照）")
            print(f"{row['number']:6s} {row['name'][:22]:24s} "
                  f"{fmt_value(row['value'], row['ontology_unit']):>12s} "
                  f"{fmt_target(row['target'], row['unit']):>10s} "
                  f"{fmt_gap(row['shortfall'], row['unit']):>10s} {row['status']:6s} {series}")
        met = sum(1 for r in payload["payload_rows"] if r["status"] == "met")
        known = sum(1 for r in payload["payload_rows"] if r["value"] is not None)
        print(f"\n达标 {met}/{known}（另有 {len(payload['payload_rows']) - known} 条本体不回答）"
              f" · problems {len(payload['problems'])} · notes {len(payload['notes'])}")
    else:
        target = pathlib.Path(args.out).expanduser().resolve()
        # CANONICAL names, not prettier ones: the Analysis panel, the registry, every 2026-09
        # cross-link and every bookmark point at `sunhing_dashboard*.html`. A second set under a
        # nicer name doubles the family in the panel and leaves the old URLs serving stale bytes —
        # which is exactly how "I opened it and nothing changed" happened. The replaced pages are
        # archived under archive-2026-09-28/ instead of kept alive under the live names.
        written = render_all(payload, target, names=LEGACY_NAMES,
                             hub_name=LEGACY_NAMES["hub"], archive=True)
        if args.also_ontology_names:
            written += render_all(payload, target)
        for path in written:
            print(f"[WROTE] {path}  ({path.stat().st_size} bytes)")
        print(f"[OK] {len(written)} pages · problems {len(payload['problems'])} · notes {len(payload['notes'])}")
        if payload["problems"]:
            print("[NOTE] 页面已写，但上面列出的问题需要修声明/映射，而不是改页面。")

    return 1 if payload["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())

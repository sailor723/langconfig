"""Run a DASHBOARD DECLARATION: compile every metric it names, guard it, run it, and report
the ones that cannot be answered — by name.

The dashboard is a declaration (`<profile dir>/dashboard.json`), not code: it says *which*
declared metric to show, *by what* it is cut, and what a missing one costs. This runner is the
only place that turns that into SQL, so a panel cannot quietly invent a number the ontology
does not declare.

    python run_dashboard.py --profile ../../ontologies/logistics/logistics_settings.json
    python run_dashboard.py --profile ... --dashboard custom.json
    python run_dashboard.py --profile ... --metric overloadRateByRouteVersion   # one metric

Why `guard.apply(..., mode="declared")` and not the default: the default mode REWRITES a query
on a big table to `WHERE <time column> >= now() - 90 days`. Every number on this dashboard is a
measurement of a *fixed historical* population (2026-08-08 → 2026-11), and `now()` is not inside
it — the row-mode guard would silently turn 4,050 trips into 0. The declared mode bounds the scan
by the plan budget and REPORTS the unbounded scan instead of moving the question.

Exit codes
    0  every referenced metric answered (holes are refused, as declared)
    1  a declared hole is not a hole any more, or a live panel refuses  → the declaration is stale
    2  the dashboard or the profile cannot be resolved
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent          # the compiler directory
FEATURE = HERE.parent                                     # backend/features/ontology
# This file lives IN the compiler, so its own directory is the compiler's. The feature root goes on
# the path too, for `ontology_profile`. NOTHING from the learning mirror belongs here: this used to
# insert `<ONTOLOGY_REPO>/retail_graph`, so a copy of `actions.py` without `dsn()` could win over the
# one next door depending on sys.path order — a mirror silently serving stale code.
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(FEATURE))



def _early_profile() -> pathlib.Path | None:
    """`--profile` has to be applied BEFORE importing sqlgen/guard.

    Both read `$APP_SETTINGS` once, at import time, to pick the ontology directory and the
    overlay (`metrics_ext.ttl`). Handing the profile over afterwards left the graph WITHOUT its
    overlay: every declared metric answered `no metric :x declared` — 23 panels "missing", which
    looks exactly like a broken declaration. Same failure the samples reset gate hit.
    """
    argv = sys.argv[1:]
    raw = None
    for i, arg in enumerate(argv):
        if arg == "--profile" and i + 1 < len(argv):
            raw = argv[i + 1]
        elif arg.startswith("--profile="):
            raw = arg.split("=", 1)[1]
    if not raw:
        return None
    p = pathlib.Path(raw).expanduser()
    if not p.is_absolute():
        p = (pathlib.Path(__file__).resolve().parent / p).resolve()
    os.environ["APP_SETTINGS"] = str(p)
    return p


_PROFILE = _early_profile()

import guard                                            # noqa: E402
import sqlgen                                           # noqa: E402

RDF_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"


def _profile(path: str | None) -> pathlib.Path:
    """The profile file, from the argument or from APP_SETTINGS (what the workbench uses)."""
    raw = path or os.environ.get("APP_SETTINGS") or ""
    if not raw:
        raise SystemExit("run_dashboard: no --profile and no APP_SETTINGS")
    p = pathlib.Path(raw).expanduser()
    if not p.is_absolute():
        p = (pathlib.Path(__file__).resolve().parent / p).resolve()
    if not p.is_file():
        raise SystemExit(f"run_dashboard: no such profile {p}")
    return p


def dashboard_path(profile: pathlib.Path, override: str | None = None) -> pathlib.Path:
    if override:
        p = pathlib.Path(override).expanduser()
        return p if p.is_absolute() else (profile.parent / p).resolve()
    return profile.parent / "dashboard.json"


def metric_label(g, name: str) -> str | None:
    for s, _, _ in g.triples((None, None, None)):
        if str(s).split("#")[-1] == name:
            for _, _, label in g.triples((s, sqlgen.URIRef(RDF_LABEL), None)):
                return str(label)
    return None


def _meta(g, name: str) -> dict:
    """What the DECLARATION says about this metric — the UI reads it, it never guesses."""
    m = sqlgen.metrics(g).get(name)
    if m is None:
        return {"declared": False}
    return {
        "declared": True,
        "label": metric_label(g, name),
        "unit": m.unit,
        "grain": m.grain,
        "aggregate": m.aggregate,
        "group_by": list(m.group_by),
        "time_bucket": m.time_bucket,
        "keys": (1 if m.time_bucket else 0) + len(m.group_by),
        "ratio": bool(m.numerator and m.denominator),
        "scale": m.scale,
        "where": m.where or m.concept,
    }


def run_metric(cur, g, name: str, *, since=None, until=None,
               dim_filters: dict | None = None) -> dict:
    """Compile → guard (declared mode) → EXPLAIN budget → execute. One metric, one answer."""
    t0 = time.time()
    meta = _meta(g, name)
    if not meta["declared"]:
        return {"ok": False, "metric": name, "status": "missing_declaration",
                "refused": f"no metric :{name} declared in this ontology", **meta}
    try:
        compiled = sqlgen.compile_metric(g, name, since=since, until=until,
                                         dim_filters=dim_filters or None)
    except sqlgen.Refusal as exc:
        # a metric that refuses BECAUSE OF the active filter is different from one that always
        # refuses: the panel can then say "this view cannot be cut that way" instead of "broken".
        unsupported = "cannot filter :" in str(exc)
        return {"ok": False, "metric": name, "status": "refused", "refused": str(exc),
                "filter_unsupported": unsupported, **meta,
                "ms": round((time.time() - t0) * 1000)}
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "metric": name, "status": "error",
                "refused": f"{type(exc).__name__}: {exc}", **meta,
                "ms": round((time.time() - t0) * 1000)}
    try:
        guarded = guard.apply(compiled.sql, mode="declared")
    except guard.Refusal as exc:
        return {"ok": False, "metric": name, "status": "refused",
                "refused": f"guard: {exc}", **meta, "sql": compiled.sql,
                "ms": round((time.time() - t0) * 1000)}
    try:
        estimated = guard.plan_rows(cur, guarded["sql"])
    except Exception as exc:                                    # noqa: BLE001  (budget is advisory)
        estimated = None
        guarded["notes"].append(f"plan budget not checked ({type(exc).__name__})")
    try:
        cur.execute(guarded["sql"])
        raw = cur.fetchall()
        names = [d[0] for d in cur.description]
    except Exception as exc:                                    # noqa: BLE001
        # a failed statement leaves the transaction ABORTED, so every later metric would report
        # "commands ignored until end of transaction block" — one broken query must cost one panel
        try:
            cur.connection.rollback()
        except Exception:                                       # noqa: BLE001
            pass
        return {"ok": False, "metric": name, "status": "error",
                "refused": f"the query did not run ({type(exc).__name__}: {exc})", **meta,
                "sql": guarded["sql"], "ms": round((time.time() - t0) * 1000)}
    rows = []
    for row in raw:
        rows.append([_jsonable(v) for v in row])
    return {
        "ok": True, "metric": name, "status": "ok", **meta,
        "columns": names, "rows": rows, "sql": guarded["sql"],
        "guard_notes": guarded["notes"], "plan_rows": estimated,
        "ms": round((time.time() - t0) * 1000),
    }


def _jsonable(value):
    """Dates/Decimals are JSON numbers or ISO strings; NULL stays None (never 0)."""
    import datetime
    import decimal

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)


def panel_metric_refs(panel: dict) -> list[str]:
    """Every metric a panel needs, whatever channel it arrives on.

    A panel is not only `metric`/`metrics`: a Sankey's流量 lives on its LINKS, a bubble chart's four
    channels live on x/y/size/color. Reading only `metric`/`metrics` silently left both panels empty —
    the board showed a titled box with nothing in it, which is exactly the "silently drops a block"
    failure the refusal cards exist to prevent.
    """
    out = list(panel.get("metrics") or [])
    if panel.get("metric"):
        out.append(panel["metric"])
    for key in ("size_by", "x", "y", "size", "color"):
        # `x` is an AXIS spec on a slope panel ({"dimension": …}) and a METRIC on a bubble chart:
        # a dict is not a metric name, and treating it as one raised "unhashable type: 'dict'".
        if isinstance(panel.get(key), str):
            out.append(panel[key])
    for link in panel.get("links") or []:
        if link.get("metric"):
            out.append(link["metric"])
    for name in (panel.get("measurable_now") or {}).get("metrics") or []:
        out.append(name)
    return out


def normalise_policy(dash: dict) -> list[dict]:
    """`policy` in its two legal shapes, as ONE list of canonical entries.

    Declared as a list, an entry is `{"id", "metric", "op", "value", assumed|confirmed}` — the shape
    the assessment and the gate were written against. Declared as a MAPING, it is
    `{metric: {"threshold", "kind": "floor"|"ceiling", "source"}}`, which is how a builder naturally
    writes "8 个指标各有一条红线". Both are declarations; the reader normalises instead of crashing.

    Measured: `collect_metrics` iterated the mapping and called `.get()` on its KEYS, so a perfectly
    good dashboard 500'd on `/dashboard/panels` with `AttributeError: 'str' object has no attribute
    'get'` — the panel page was dead for a declaration the gate had already passed.

    `floor` means "at least the threshold is good", so a breach is `<`; `ceiling` means "at most",
    so a breach is `>`. `source` starting with `refused` is what marks a threshold as NOT confirmed
    by the business, which is exactly the `assumed` flag the gate wants marked.
    """
    raw = dash.get("policy")
    if isinstance(raw, dict):
        out = []
        for metric, spec in raw.items():
            if not isinstance(metric, str):
                continue
            spec = spec if isinstance(spec, dict) else {}
            kind = str(spec.get("kind") or "").lower()
            source = str(spec.get("source") or "")
            out.append({
                "id": metric,
                "metric": metric,
                "op": "<" if kind == "floor" else (">" if kind == "ceiling" else ">"),
                "value": spec.get("threshold", spec.get("value")),
                "assumed": source.lower().startswith(("refused", "assumed")) or spec.get("assumed") is True,
                "confirmed": spec.get("confirmed") is True or source.lower().startswith("confirmed"),
                "note": source or None,
            })
        return [x for x in out if x["value"] is not None]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def collect_metrics(dash: dict) -> list[tuple[str, str]]:
    """(metric, why-it-is-here) in FIRST-SEEN order, deduped — stable output, readable errors."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(name: str, why: str) -> None:
        if name and name not in seen:
            seen.add(name)
            out.append((name, why))

    for kpi in dash.get("kpis") or []:
        add(kpi.get("metric"), f"kpis:{kpi.get('metric')}")
    for panel in dash.get("panels") or []:
        pid = panel.get("id") or panel.get("kind")
        for name in panel_metric_refs(panel):
            add(name, f"panels:{pid}")
    for hole in dash.get("holes") or []:
        add(hole.get("metric"), f"holes:{hole.get('metric')}")
    for pol in normalise_policy(dash):
        add(pol.get("metric"), f"policy:{pol.get('id')}")
    for metric, _key in briefing_refs(dash):
        add(metric, "briefing")
    return out


# The names the CURRENT dashboard compiles; `briefing_refs` needs them to tell "a bare metric name in
# a list" from "a word in a sentence". Set by build(); reset per call so two ontologies never mix.
metrics_by_name: dict = {}


PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)(?::([^}]+?))?(#key)?\}")


def _strings(value, depth: int = 0):
    """Every string inside a declared value — str, list, or dict — without assuming which it is.

    A `briefing` is prose OR a structured index of what the board opens with. Measured on v5:
    `"headline": ["stopOnTimeRate", "tripFullyOnTimeRate"]` — a LIST of metric names — crashed
    `briefing_refs` with `TypeError: expected string or bytes-like object, got 'list'`, so a page
    whose declaration was fine returned 500. The reader walks the shape instead of dictating it.
    """
    if depth > 6:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, depth + 1)
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v, depth + 1)


def briefing_refs(dash: dict) -> list[tuple[str, str | None]]:
    """Every metric a briefing references — as a `{metric}` placeholder, or as a bare declared name.

    Both forms appear in real declarations: prose with placeholders, and `"headline": [names…]`
    (an index of the numbers the board opens with). A bare name that is not a declared metric is
    ignored here and reported by the gate, not by the renderer.
    """
    out: list[tuple[str, str | None]] = []
    names = set(metrics_by_name) if isinstance(metrics_by_name, dict) else set()
    for text in _strings(dash.get("briefing")):
        for metric, key, _echo in PLACEHOLDER.findall(text):
            if (metric, key) not in out:
                out.append((metric, key))
        if text in names and (text, None) not in out:
            out.append((text, None))
    return out


def _fmt(value, unit: str | None) -> str:
    """The same presentation rules the page uses — one implementation, so text and charts agree."""
    if value is None:
        return "—"
    v = float(value)
    if unit == "ratio":
        return f"{v * 100:.1f}%"
    if unit == "money":
        return f"¥{v:,.2f}"
    if abs(v - round(v)) < 1e-9:          # an integer count is not "50.0 条"
        return f"{v:,.0f}"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    if abs(v) >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def _lookup(results: dict, metric: str, key: str | None) -> tuple[float | None, str | None, str | None]:
    """(value, unit, why-not) for one placeholder. A named reason beats an empty spot in the text."""
    res = results.get(metric) or {}
    if res.get("status") != "ok":
        return None, None, f":{metric} {res.get('status') or 'is missing'}" + (
            f" — {res.get('refused')}" if res.get("refused") else "")
    rows = res.get("rows") or []
    unit = res.get("unit")
    if key is None:
        if res.get("keys"):
            return None, unit, f":{metric} is grouped ({res.get('keys')} key(s)) — the sentence needs a :key"
        return (rows[0][0] if rows and rows[0] else None), unit, None
    want = None if key.lower() in ("null", "none") else key
    for row in rows:
        keys = row[:-1]
        if len(keys) == 1:
            if (keys[0] is None and want is None) or (keys[0] is not None and want is not None
                                                      and str(keys[0]) == want):
                return row[-1], unit, None
        elif len(keys) > 1 and want is not None and "|" in want:
            # case-insensitive: a boolean group comes back as Python `True` and a declaration
            # writes "true" — comparing reprs made every 2-key Sankey link unresolvable.
            parts = [x.strip().lower() for x in want.split("|")]
            if [str(k).lower() for k in keys] == parts:
                return row[-1], unit, None
    return None, unit, f":{metric} has no group {key!r}"


def _breached(value, op: str, threshold) -> bool:
    if value is None:
        return False
    v, t = float(value), float(threshold)
    return {">": v > t, ">=": v >= t, "<": v < t, "<=": v <= t, "==": v == t}.get(op, False)


def resolve_briefing(dash: dict, results: dict) -> dict:
    """Fill the briefing's placeholders from the compiled numbers, then judge it against POLICY.

    A threshold is a business decision, so it must be declared with `assumed` or `confirmed`; the
    gate refuses an unmarked one. A claim whose metric refuses renders as "cannot be assessed" with
    the refusal in it — an assessment that quietly drops a failing dimension is the thing this whole
    dashboard exists to prevent.
    """
    brief = dash.get("briefing") or {}
    policy = normalise_policy(dash)

    pol_out = []
    for pol in policy:
        res = results.get(pol.get("metric")) or {}
        value = None
        if res.get("status") == "ok" and not res.get("keys"):
            rows = res.get("rows") or []
            value = rows[0][0] if rows and rows[0] else None
        hit = _breached(value, pol.get("op") or ">", pol.get("value"))
        pol_out.append({**pol, "current": value, "unit": res.get("unit"),
                        "current_text": _fmt(value, res.get("unit")),
                        "breached": hit, "level": "red" if hit else "green",
                        "status": res.get("status") or "missing",
                        "confirmed": bool(pol.get("confirmed")), "assumed": bool(pol.get("assumed"))})

    def fill(text: str) -> tuple[str, list[str]]:
        problems: list[str] = []

        def sub(m):
            metric, key, echo = m.group(1), m.group(2), m.group(3)
            value, unit, why = _lookup(results, metric, key)
            if why:
                problems.append(why)
                return f"⟪{why}⟫"
            if echo:                     # print the KEY, not the value
                return "未判定" if key is None or key.lower() in ("null", "none") else str(key)
            return _fmt(value, unit)

        return PLACEHOLDER.sub(sub, text or ""), problems

    claims = []
    for claim in brief.get("claims") or []:
        text, problems = fill(claim.get("text") or "")
        by = claim.get("verdict_by")
        pol = next((x for x in pol_out if x["id"] == by), None) if by else None
        claims.append({**claim, "rendered": text, "problems": problems,
                       "resolvable": not problems,
                       "verdict": (pol["level"] if pol else None),
                       "verdict_from": pol["id"] if pol else None,
                       "verdict_text": (f"{pol['label']} {pol['op']} {pol['value']}，当前 {pol['current_text']}"
                                        if pol else None)})

    headline, head_problems = fill(brief.get("headline") or "")
    level = "red" if any(p["breached"] for p in pol_out) else "green"
    return {
        "headline": headline, "headline_problems": head_problems,
        "claims": claims,
        "cannot_see": brief.get("cannot_see") or [],
        "next": fill(brief.get("next") or "")[0],
        "policy": pol_out,
        "verdict": {"level": level,
                    "breaches": [p["id"] for p in pol_out if p["breached"]],
                    "unconfirmed": [p["id"] for p in pol_out if p["assumed"] and not p["confirmed"]]},
        "resolvable": not head_problems and all(c["resolvable"] for c in claims),
    }


def _conn():
    """One connection, to the database of the profile the compiler is pointed at NOW.

    `actions.DSN` is a constant captured at import; in a process that serves several ontologies it
    still names whichever database was active first — measured: `FROM trips` against retail_db, which
    aborted the transaction and turned every later metric into "the query did not run".
    """
    import psycopg2

    import actions

    dsn = dict(actions.dsn())
    dsn.setdefault("password", "")
    return psycopg2.connect(**dsn)


def build(profile_path, *, dim_filters: dict | None = None,
          metrics: list[str] | None = None, dashboard: str | None = None,
          since=None, until=None) -> dict:
    """Run a dashboard declaration IN THIS PROCESS and return the payload.

    The CLI below is a thin wrapper over this function, so the app and the command line cannot
    disagree about what a board says. The caller is responsible for serialising calls: the
    compiler's state is process-wide (`profile.use()` is what points it here).
    """
    import ontology_profile as _profile_mod

    profile = pathlib.Path(profile_path).expanduser().resolve()
    path = dashboard_path(profile, dashboard)
    if not path.is_file():
        return {"ok": False, "error": f"no dashboard declaration at {path}"}
    dash = json.loads(path.read_text())
    _profile_mod.use(profile)                 # the compiler now compiles THIS ontology
    g = sqlgen.load()
    global metrics_by_name
    metrics_by_name = sqlgen.metrics(g)          # the NAMES this board may reference by bare name
    wanted = ([(m, "cli") for m in metrics] if metrics else collect_metrics(dash))
    return _execute(profile, path, dash, g, wanted, dict(dim_filters or {}),
                    since=since, until=until)


def _execute(profile, path, dash, g, wanted, dim_filters, *, since=None, until=None) -> dict:
    conn = _conn()
    cur = conn.cursor()
    results: dict[str, dict] = {}
    try:
        # VALIDATE the filter values against the DECLARED set before running anything: an unknown
        # value compiles fine and returns 0, which is a silent wrong answer ("v9 超载率 0%").
        allowed: dict[str, list] = {}
        for panel in dash.get("panels") or []:
            emit = panel.get("emit_filter") or {}
            dim = emit.get("dimension")
            metric = panel.get("metric") or (panel.get("metrics") or [None])[0]
            if dim and dim not in allowed and metric:
                probe = run_metric(cur, g, metric)
                if probe.get("status") == "ok":
                    allowed[dim] = list(dict.fromkeys(r[0] for r in (probe.get("rows") or [])))
        for prop, value in dim_filters.items():
            if prop not in allowed:
                return {"ok": False, "error": f"no declared panel emits a filter on {prop!r}",
                        "filterable": sorted(allowed)}
            if value not in allowed[prop]:
                return {"ok": False, "error": f"filter value {value!r} is not a value :{prop} takes",
                        "allowed": allowed[prop][:40]}
        for name, why in wanted:
            res = run_metric(cur, g, name, since=since, until=until, dim_filters=dim_filters)
            res["why"] = why
            results[name] = res
    finally:
        cur.close()
        conn.close()

    holes = []
    for hole in dash.get("holes") or []:
        name = hole.get("metric")
        res = results.get(name) or {}
        expect = hole.get("expect_refusal") or ""
        refused = res.get("status") == "refused"
        holes.append({
            "metric": name, "label": res.get("label"),
            "status": "refused" if refused else "answered",
            "reason": res.get("refused") or ("it answered — this declared hole is stale" if res else None),
            "expect_refusal": expect,
            "matches_declaration": bool(refused and expect and expect in (res.get("refused") or "")),
            **({"value": res["rows"][0][0]} if res.get("rows") else {}),
        })

    declared_holes = {h.get("metric") for h in dash.get("holes") or []}
    live_refused = [{"metric": n, "label": results[n].get("label"),
                     "status": results[n].get("status"),
                     "refused": results[n].get("refused"), "why": results[n].get("why")}
                    for n, _ in wanted
                    if results.get(n, {}).get("status") in ("refused", "error", "missing_declaration")
                    and n not in declared_holes
                    and not results[n].get("filter_unsupported")]

    value_sets: dict[str, list] = {}
    for panel in dash.get("panels") or []:
        emit = panel.get("emit_filter") or {}
        dim = emit.get("dimension")
        metric = panel.get("metric") or (panel.get("metrics") or [None])[0]
        res = results.get(metric or "") or {}
        if dim and res.get("status") == "ok":
            value_sets[dim] = list(dict.fromkeys(r[0] for r in (res.get("rows") or [])))
    for dim, values in allowed.items():
        value_sets.setdefault(dim, values)

    payload = {
        "ok": not live_refused,
        "profile": str(profile), "dashboard": str(path),
        "title": dash.get("title"), "subtitle": dash.get("subtitle"),
        "events": dash.get("events") or [],
        "kpis": [{"metric": k.get("metric"), "note": k.get("note"),
                  "result": results.get(k.get("metric"))} for k in dash.get("kpis") or []],
        "panels": [{**p, "resultset": None,
                    "results": {n: results[n] for n in panel_metric_refs(p) if n in results}}
                   for p in dash.get("panels") or []],
        "briefing": resolve_briefing(dash, results),
        "filters": dim_filters,
        "value_sets": value_sets,
        "holes": holes,
        "refused": live_refused,
        "metrics": results,
    }
    payload.pop("resultset", None)
    for panel in payload["panels"]:
        panel.pop("resultset", None)
    return payload


def exit_code(payload: dict) -> int:
    """0 when every panel answers and every hole still refuses; 1 when the declaration is stale."""
    if not payload.get("ok"):
        return 1
    stale = [h for h in payload.get("holes") or [] if h.get("status") != "refused"]
    return 1 if stale else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", help="profile path (default: $APP_SETTINGS)")
    ap.add_argument("--dashboard", help="dashboard.json (default: next to the profile)")
    ap.add_argument("--metric", action="append", help="run just these metrics (repeatable)")
    ap.add_argument("--since"), ap.add_argument("--until")
    ap.add_argument("--filter", action="append", default=[],
                    help="dimension:value (repeatable), e.g. --filter routeVersion:v2")
    args = ap.parse_args()

    profile = _profile(args.profile)
    dim_filters: dict[str, object] = {}
    for raw in args.filter or []:
        if ":" not in raw:
            print(json.dumps({"ok": False, "error": f"--filter {raw!r} must be dimension:value"},
                             ensure_ascii=False))
            return 2
        prop, value = raw.split(":", 1)
        dim_filters[prop.strip()] = (None if value.strip().lower() in ("null", "none")
                                    else value.strip())
    payload = build(profile, dim_filters=dim_filters, metrics=args.metric,
                    dashboard=args.dashboard, since=args.since, until=args.until)
    print(json.dumps(payload, ensure_ascii=False, default=str))
    return 2 if payload.get("error") and not payload.get("panels") else exit_code(payload)


if __name__ == "__main__":
    raise SystemExit(main())

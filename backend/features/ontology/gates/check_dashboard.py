"""D — DASHBOARD GATES. A dashboard is a claim about what a business can see; these check that
the claim is true of the declarations, not just true of the JSON.

    python check_dashboard.py                                  # $APP_SETTINGS
    python check_dashboard.py --profile ../ontologies/logistics/logistics_settings.json

What is checked, and why each one can actually fail:

  D0  the declaration parses and every metric it names is DECLARED
      (a panel naming a metric that does not exist is the "dashboard shows what it was coded
       to show" failure; it fails by name here)
  D1  every metric is the SHAPE its panel needs: kpi → 1 row, series → 1 key on a time axis,
      matrix → 2 keys, ranked → 1 key covered by its `size_by`, hole-panel `requires` → the
      class really is undeclared
  D2  each panel's declared `sort` is the order the rows actually arrive in — otherwise
      "the 20 worst vehicles" renders the 20 best (the compiler always orders grouped metrics
      DESC; a panel asking for the low end must SAY it sorts client-side)
  D3  the GROUPED numbers reproduce the UNGROUPED ones. A rate cut by vehicle/version/zone must
      weight back to the fleet value; counts must sum to the total. This is the only check that
      catches a join that fans out or a FILTER applied on one side only.
  D4  every declared HOLE is still a hole, and says what the declaration expects it to say
      (a hole that starts answering means the declaration is stale, and the panel is lying in
      the other direction)
  D5  independent SQL — written here, not compiled by the ontology — agrees with the compiled
      numbers for the headline panels. If both were derived from the same declaration, D3 would
      be checking arithmetic against itself.
  D6  every event marker names a metric that has a time axis (a marker drawn on a categorical
      axis is a lie about causality)

Exit 0 only when every check passes; NOT RUN items are printed by name, never silently skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
# The COMPILER lives in the ontology repository (sqlgen, guard, actions); the scripts that use it
# live here, with this skill. Both paths are explicit: a sibling script (HERE) and the compiler's
# own home (ONTOLOGY_REPO/retail_graph) — never "whichever directory this file happens to sit in".
ONTOLOGY_REPO = pathlib.Path(os.environ.get("ONTOLOGY_REPO") or "/Users/weiping/dev/Learn/ontology")
# The COMPILER lives one directory up (features/ontology/compiler) and its modules import each
# other by bare name, so its directory goes on sys.path — a path that never depends on where this
# repository happens to live.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "compiler"))
sys.path.insert(0, str(ONTOLOGY_REPO / "retail_graph"))



def _early_profile() -> None:
    """`--profile` must land in $APP_SETTINGS before sqlgen/guard are imported (see run_dashboard)."""
    argv = sys.argv[1:]
    raw = None
    for i, arg in enumerate(argv):
        if arg == "--profile" and i + 1 < len(argv):
            raw = argv[i + 1]
        elif arg.startswith("--profile="):
            raw = arg.split("=", 1)[1]
    if raw:
        p = pathlib.Path(raw).expanduser()
        os.environ["APP_SETTINGS"] = str(p if p.is_absolute() else (HERE / p).resolve())


_early_profile()

import actions                                          # noqa: E402
import psycopg2                                         # noqa: E402
import run_dashboard                                    # noqa: E402
import sqlgen                                           # noqa: E402
from rdflib import OWL, RDF                             # noqa: E402

FAILS: list[str] = []
NOT_RUN: list[str] = []
CHECKS = 0


def check(label: str, got, want) -> None:
    global CHECKS
    CHECKS += 1
    if got == want:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")
        FAILS.append(label)


def close(label: str, got, want, tol: float = 1e-9) -> None:
    """Float comparison that reports the numbers, not just 'not equal'."""
    global CHECKS
    CHECKS += 1
    ok = got is not None and want is not None and abs(float(got) - float(want)) <= tol * max(
        1.0, abs(float(want)))
    if ok:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}\n          got  {got!r}\n          want {want!r}")
        FAILS.append(label)


def skill(label: str) -> None:
    print(f"  NOT RUN  {label}")
    NOT_RUN.append(label)


def _names(res: dict) -> list[str]:
    return [r.get("metric") for r in res.values()]


def _value(res: dict):
    rows = res.get("rows") or []
    return rows[0][0] if rows and rows[0] else None


def _by_key(res: dict, width: int) -> dict[tuple, float | None]:
    """{key tuple: value} — keyed, never zipped by position: two grouped queries order
    differently (DESC by value vs DESC by count) and a positional zip silently compares
    the wrong pairs (measured: it invented a 45.5% overload rate against the real 36.8%)."""
    out: dict[tuple, float | None] = {}
    for row in res.get("rows") or []:
        out[tuple(row[:width])] = row[width]
    return out


def _weighted(values: dict[tuple, float | None], sizes: dict[tuple, float | None],
              width: int) -> float | None:
    num = den = 0.0
    for key, v in values.items():
        n = sizes.get(key)
        if v is None or n is None:
            return None
        num += float(v) * float(n)
        den += float(n)
    return num / den if den else None


def _classes(g) -> set[str]:
    return {str(s).split("#")[-1] for s in g.subjects(RDF.type, OWL.Class)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile")
    ap.add_argument("--dashboard")
    args, _ = ap.parse_known_args()

    profile = run_dashboard._profile(args.profile)
    path = run_dashboard.dashboard_path(profile, args.dashboard)
    print(f"D — dashboard gate · {path}")

    if not path.is_file():
        print(f"  FAIL  the declaration exists ({path})")
        print("\n1 check, 1 failed")
        return 1
    dash = json.loads(path.read_text())
    g = sqlgen.load()
    classes = _classes(g)

    conn = psycopg2.connect(**{**actions.DSN, "password": ""})
    cur = conn.cursor()
    try:
        results = {name: run_dashboard.run_metric(cur, g, name)
                   for name, _why in run_dashboard.collect_metrics(dash)}

        # ── D0 ────────────────────────────────────────────────────────────
        print("\nD0  every referenced metric is declared")
        holes = {h.get("metric") for h in dash.get("holes") or []}
        for name, why in run_dashboard.collect_metrics(dash):
            res = results[name]
            want = "refused" if name in holes else "ok"
            got = res.get("status")
            check(f"D0 {name} ({why}) → {want}", got, want)
            if got != want and res.get("refused"):
                print(f"          reason: {res['refused'][:160]}")

        # ── D1 ────────────────────────────────────────────────────────────
        print("\nD1  each panel's metric has the shape the panel needs")
        for kpi in dash.get("kpis") or []:
            res = results.get(kpi.get("metric")) or {}
            if res.get("status") != "ok":
                continue
            check(f"D1 kpi {kpi['metric']} is a single number", res.get("keys"), 0)
            check(f"D1 kpi {kpi['metric']} has exactly one row", len(res.get("rows") or []), 1)

        for panel in dash.get("panels") or []:
            pid, kind = panel["id"], panel["kind"]
            refs = list(panel.get("metrics")
                        or ([panel["metric"]] if panel.get("metric") else []))
            if panel.get("size_by"):
                refs.append(panel["size_by"])
            if kind == "hole":
                for cls in panel.get("requires") or []:
                    check(f"D1 {pid}: {cls} is still undeclared", cls.lstrip(":") in classes, False)
                for name in (panel.get("measurable_now") or {}).get("metrics") or []:
                    check(f"D1 {pid}: fallback {name} answers", results[name].get("status"), "ok")
                continue
            for name in refs:
                res = results.get(name) or {}
                if res.get("status") != "ok":
                    check(f"D1 {pid}: {name} answers", res.get("status"), "ok")
                    continue
                keys = res.get("keys")
                if kind == "kpi":
                    check(f"D1 {pid}/{name} single number", keys, 0)
                elif kind == "slope":
                    check(f"D1 {pid}/{name} cut by exactly one dimension", keys, 1)
                    order = (panel.get("x") or {}).get("order") or []
                    got_keys = [str(r[0]) for r in res.get("rows") or []]
                    check(f"D1 {pid}/{name} covers the declared axis {order}",
                          sorted(got_keys), sorted(order))
                elif kind in ("series", "ranked", "composition"):
                    check(f"D1 {pid}/{name} cut by exactly one dimension", keys, 1)
                elif kind == "matrix":
                    check(f"D1 {pid}/{name} cut by exactly two dimensions", keys, 2)
                elif kind == "treemap":
                    check(f"D1 {pid}/{name} cut by exactly two dimensions", keys, 2)
                elif kind == "parallel":
                    check(f"D1 {pid}/{name} is a single declared value", keys, 0)
                    check(f"D1 {pid}/{name} has exactly one row", len(res.get("rows") or []), 1)
                elif kind == "bubble":
                    check(f"D1 {pid}/{name} is cut by one dimension", keys, 1)
                elif kind == "sankey":
                    check(f"D1 {pid}/{name} is cut by one or two dimensions", keys in (1, 2), True)
            if kind == "series":
                res = results.get(refs[0]) or {}
                rows = res.get("rows") or []
                if res.get("time_bucket") and len(rows) > 1:
                    xs = [str(r[0]) for r in rows]
                    check(f"D1 {pid} time axis is ascending (a series sorted by its own value "
                          f"is not a series)", xs, sorted(xs))
                if len(rows) <= 1:
                    # one row is legitimate ONLY when the declaration says why (a constant column
                    # is a finding); otherwise it is an axis that does not exist.
                    check(f"D1 {pid} one-row series declares why", bool(
                        panel.get("expect") or panel.get("note")), True)
            if kind == "ranked":
                res = results.get(refs[0]) or {}
                sizes = results.get(panel.get("size_by") or "") or {}
                if sizes.get("status") == "ok":
                    missing = set(_by_key(res, 1)) - set(_by_key(sizes, 1))
                    check(f"D1 {pid}: every ranked key has a size", sorted(missing), [])
                    limit = panel.get("limit") or 0
                    check(f"D1 {pid}: at least {limit} rows to rank",
                          len(res.get("rows") or []) >= limit, True)
            if kind == "matrix" and panel.get("size_by"):
                sizes = results.get(panel["size_by"]) or {}
                if sizes.get("status") == "ok":
                    cells = set(_by_key(results[refs[0]], 2))
                    sized = set(_by_key(sizes, 2))
                    check(f"D1 {pid}: every cell has a size", sorted(cells - sized), [])
            if kind == "composition":
                res = results.get(refs[0]) or {}
                has_null = any(r[1] is None for r in res.get("rows") or [])
                if has_null:
                    # A NULL group is a real group (unjudged liability). It must be labelled, or a
                    # formatter will print it as 0 and turn 3,167 unjudged complaints into "no cost".
                    check(f"D1 {pid} labels its NULL group", bool(panel.get("null_label")), True)

            # ── D2 ────────────────────────────────────────────────────────
            if kind == "ranked":
                res = results.get(refs[0]) or {}
                # Read the ORDER BY direction, NOT the last token: `guard` appends `LIMIT 1000`
                # after it, so an endswith("DESC") test silently reported every panel as ASC.
                found = re.findall(r"ORDER\s+BY\s+[^;]*?\b(ASC|DESC)\b", (res.get("sql") or ""), re.I)
                want = (panel.get("sort") or "desc").lower()
                arrived = (found[-1] if found else "NONE").upper()
                if want == "asc":
                    check(f"D2 {pid} declares it re-sorts client-side (the compiler emitted "
                          f"{arrived})", bool(panel.get("client_sort")), True)
                else:
                    check(f"D2 {pid} asks for the high end and the rows arrive DESC",
                          arrived, "DESC")

        # ── D3 ────────────────────────────────────────────────────────────
        print("\nD3  grouped numbers reproduce the ungrouped ones")
        # The gate needs the whole-population totals too (a dashboard may show only rates and
        # never the raw counts). These are run here, not silently skipped: a comparison whose
        # baseline is absent is not a check.
        for name in ("stopCount",):
            if name not in results:
                results[name] = run_dashboard.run_metric(cur, g, name)
        data = {name: results[name] for name in results if results[name].get("status") == "ok"}

        def total(name: str) -> float | None:
            return _value(data[name]) if name in data else None

        def rows(name: str, width: int = 1) -> dict[tuple, float | None]:
            return _by_key(data[name], width) if name in data else {}

        identities = [
            ("trips by version sum to trips", "tripCountByRouteVersion", None, 1, "tripCount"),
            ("trips by week sum to trips", "tripCountByWeek", None, 1, "tripCount"),
            ("trips by vehicle sum to trips", "tripCountByVehicle", None, 1, "tripCount"),
            ("stops by vehicle sum to stops", "stopCountByVehicle", None, 1, "stopCount"),
            ("stops by zone×version sum to stops", "stopCountByZoneVersion", None, 2, "stopCount"),
            ("complaints by liability sum to complaints", "complaintCountByLiability", None, 1,
             "complaintCount"),
        ]
        for label, grouped, _n, width, whole in identities:
            missing = [m for m in (grouped, whole) if m not in data]
            if missing:
                check(f"D3 {label}: every metric it compares is declared and answers",
                      sorted(missing), [])
                continue
            close(f"D3 {label}", sum(v or 0 for v in rows(grouped, width).values()),
                  total(whole))

        weighted = [
            ("overload rate by version weights to the fleet rate", "overloadRateByRouteVersion",
             "tripCountByRouteVersion", 1, "overloadRate"),
            ("overload rate by vehicle weights to the fleet rate", "overloadRateByVehicle",
             "tripCountByVehicle", 1, "overloadRate"),
            ("on-time rate by vehicle weights to the fleet rate", "stopOnTimeRateByVehicle",
             "stopCountByVehicle", 1, "stopOnTimeRate"),
            ("damage per 1k stops by vehicle weights to the fleet rate", "damagePer1kStopsByVehicle",
             "stopCountByVehicle", 1, "damagePer1kStops"),
            ("on-time rate by zone×version weights to the fleet rate", "stopOnTimeRateByZoneVersion",
             "stopCountByZoneVersion", 2, "stopOnTimeRate"),
            ("damage per 1k stops by zone×version weights to the fleet rate",
             "damagePer1kStopsByZoneVersion", "stopCountByZoneVersion", 2, "damagePer1kStops"),
        ]
        for label, value_m, size_m, width, whole in weighted:
            missing = [m for m in (value_m, size_m, whole) if m not in data]
            if missing:
                check(f"D3 {label}: every metric it compares is declared and answers",
                      sorted(missing), [])
                continue
            close(f"D3 {label}", _weighted(rows(value_m, width), rows(size_m, width), width),
                  total(whole), tol=1e-6)

        # a PARTIAL count can never exceed its whole — the check that catches an EXISTS which
        # matches everything (the classic broken object restriction)
        if "tripsWithDecisionRecord" in data and "tripCount" in data:
            check("D3 trips with a decision record never exceed trips",
                  total("tripsWithDecisionRecord") <= total("tripCount"), True)
        if "decisionCoverage" in data and "tripsWithDecisionRecord" in data and "tripCount" in data:
            whole = total("tripCount")
            close("D3 coverage is the record count over trips", total("decisionCoverage"),
                  total("tripsWithDecisionRecord") / whole if whole else None, tol=1e-12)

        # ── D4 ────────────────────────────────────────────────────────────
        print("\nD4  every declared hole is still a hole")
        for hole in dash.get("holes") or []:
            name = hole.get("metric")
            res = results.get(name) or {}
            check(f"D4 {name} is refused", res.get("status"), "refused")
            expect = hole.get("expect_refusal") or ""
            check(f"D4 {name} refuses for the declared reason",
                  bool(expect) and expect in (res.get("refused") or ""), True)

        # ── D5 ────────────────────────────────────────────────────────────
        print("\nD5  independent SQL agrees (not compiled by the ontology)")
        independent = {
            "trips": "SELECT count(*) FROM trips",
            "trips_v1": "SELECT count(*) FROM trips JOIN routes r ON r.id = trips.route_id "
                        "WHERE r.version = 'v1'",
            "trips_v2": "SELECT count(*) FROM trips JOIN routes r ON r.id = trips.route_id "
                        "WHERE r.version = 'v2'",
            "stops": "SELECT count(*) FROM stops",
            "complaints": "SELECT count(*) FROM complaints",
            "unjudged": "SELECT count(*) FROM complaints WHERE liability IS NULL",
            "claims_labourer": "SELECT round(sum(amount), 2) FROM complaints "
                               "WHERE liability = 'labourer'",
            "claims_driver": "SELECT round(sum(amount), 2) FROM complaints WHERE liability = 'driver'",
            "worst_vehicle_damage": (
                "SELECT round(1000.0 * sum(s.damaged_boxes) / count(*), 6) FROM stops s "
                "JOIN trips t ON t.id = s.trip_id JOIN vehicles v ON v.id = t.vehicle_id "
                "GROUP BY v.plate ORDER BY 1 DESC LIMIT 1"),
            "decision_rows": "SELECT count(*) FROM dispatch_decisions",
            "trips_with_decision": (
                "SELECT count(*) FROM trips t WHERE EXISTS (SELECT 1 FROM dispatch_decisions d "
                "WHERE d.trip_id = t.id)"),
            "overload_v2": (
                "SELECT round(1.0 * count(*) FILTER (WHERE t.load_boxes >= t.box_capacity_snapshot "
                "OR t.load_volume >= t.volume_capacity_snapshot "
                "OR t.load_weight >= t.weight_capacity_snapshot) / count(*), 9) FROM trips t "
                "JOIN routes r ON r.id = t.route_id WHERE r.version = 'v2'"),
        }
        truth: dict[str, float | None] = {}
        for label, sql in independent.items():
            cur.execute(sql)
            row = cur.fetchone()
            truth[label] = run_dashboard._jsonable(row[0]) if row else None

        if "tripCount" in data:
            close("D5 trips", total("tripCount"), truth["trips"])
            v = rows("tripCountByRouteVersion", 1)
            close("D5 trips v1", v.get(("v1",)), truth["trips_v1"])
            close("D5 trips v2", v.get(("v2",)), truth["trips_v2"])
        if "stopCount" in data:
            close("D5 stops", total("stopCount"), truth["stops"])
        if "complaintCount" in data:
            close("D5 complaints", total("complaintCount"), truth["complaints"])
        if "unjudgedComplaints" in data:
            close("D5 unjudged complaints", total("unjudgedComplaints"), truth["unjudged"])
        if "complaintCountByLiability" in data:
            c = rows("complaintCountByLiability", 1)
            close("D5 unjudged appears as its own group", c.get((None,)), truth["unjudged"])
        if "claimAmountByLiability" in data:
            a = rows("claimAmountByLiability", 1)
            close("D5 claims to labourer", a.get(("labourer",)), truth["claims_labourer"], tol=1e-9)
            close("D5 claims to driver", a.get(("driver",)), truth["claims_driver"], tol=1e-9)
            check("D5 the unjudged group has no amount (NULL, not 0)",
                  a.get((None,)) is None, True)
        if "damagePer1kStopsByVehicle" in data:
            d = rows("damagePer1kStopsByVehicle", 1)
            close("D5 worst vehicle damage", max(d.values()), truth["worst_vehicle_damage"],
                  tol=1e-6)
        if "dispatchDecisionCount" in data:
            close("D5 decision rows", total("dispatchDecisionCount"), truth["decision_rows"])
        if "tripsWithDecisionRecord" in data:
            close("D5 trips with a decision record", total("tripsWithDecisionRecord"),
                  truth["trips_with_decision"])
        if "overloadRateByRouteVersion" in data:
            o = rows("overloadRateByRouteVersion", 1)
            close("D5 overload rate v2", o.get(("v2",)), truth["overload_v2"], tol=1e-9)

        # ── D7: the opening assessment ─────────────────────────────────────
        print("\nD7  the briefing quotes nothing it did not compile")
        if not dash.get("briefing"):
            skill("D7 the declaration has no briefing")
        else:
            brief = run_dashboard.resolve_briefing(dash, results)
            PH = run_dashboard.PLACEHOLDER
            # scan the DECLARATION (placeholders intact). Scanning the rendered text would flag the
            # very numbers the placeholders exist to supply — the first version of this check did
            # exactly that and failed on all seven sentences.
            src = dash.get("briefing") or {}
            texts = ([("headline", src.get("headline") or "")]
                     + [(f"claim {c.get('id')}", c.get("text") or "") for c in src.get("claims") or []]
                     + [(f"cannot_see[{i}]", t) for i, t in enumerate(src.get("cannot_see") or [])]
                     + [("next", src.get("next") or "")])
            # a hand-typed "81%" is a lie the moment the data moves: every number must be a
            # placeholder that this run filled from a compiled value.
            bare = [(where, re.sub(r"\d", "#", t)[:60]) for where, t in texts
                    if re.search(r"\d", PH.sub("", t))]
            check("D7 no number is typed by hand (every digit came from a placeholder)",
                  [w for w, _ in bare], [])
            check("D7 every claim resolved", [c["id"] for c in brief["claims"] if not c["resolvable"]], [])
            check("D7 the headline resolved", brief["headline_problems"], [])
            for pol in brief["policy"]:
                check(f"D7 policy {pol['id']} says whether it is a confirmed decision",
                      bool(pol.get("assumed") or pol.get("confirmed")), True)
                # re-run the comparison HERE: a payload that says "not breached" is a claim too
                value = pol.get("current")
                op, threshold = pol.get("op") or ">", pol.get("value")
                expected = False if value is None else {
                    ">": float(value) > float(threshold), ">=": float(value) >= float(threshold),
                    "<": float(value) < float(threshold), "<=": float(value) <= float(threshold),
                    "==": float(value) == float(threshold)}.get(op, False)
                check(f"D7 policy {pol['id']} verdict is the comparison, recomputed", pol["breached"], expected)
            ids = {pol["id"] for pol in brief["policy"]}
            unknown = [c["id"] for c in brief["claims"] if c.get("verdict_by") and c["verdict_by"] not in ids]
            check("D7 every claim is judged against a declared policy", unknown, [])
            worst = "red" if any(p["breached"] for p in brief["policy"]) else "green"
            check("D7 the overall verdict is the worst policy", brief["verdict"]["level"], worst)
            print(f"       verdict {brief['verdict']['level']} · breaches {brief['verdict']['breaches']}"
                  f" · assumed {brief['verdict']['unconfirmed']}")

        # ── D8: a Sankey whose flow is declared, not computed ─────────────
        for panel in [x for x in dash.get("panels") or [] if x.get("kind") == "sankey"]:
            pid = panel["id"]
            print(f"\nD8  {pid}: every band is a declared group, and the flow is conserved")
            nodes = {n["id"] for n in panel.get("nodes") or []}
            known = set(panel.get("results") or {})
            edges = []
            for link in panel.get("links") or []:
                label = f"{link.get('from')}→{link.get('to')} ({link.get('metric')}:{link.get('key')})"
                check(f"D8 {pid} link {label} joins declared nodes",
                      link.get("from") in nodes and link.get("to") in nodes, True)
                value, _unit, why = run_dashboard._lookup(results, link.get("metric"), link.get("key"))
                check(f"D8 {pid} link {label} has a compiled value", why, None)
                if value is not None:
                    edges.append((link["from"], link["to"], float(value)))

            def total(node: str, direction: str) -> float:
                pairs = [(a, b, v) for a, b, v in edges]
                return sum(v for a, b, v in pairs
                           if (b == node if direction == "in" else a == node))

            mids = [n for n in nodes if n != (panel.get("nodes") or [{}])[0].get("id")]
            for mid in mids:
                inflow, outflow = total(mid, "in"), total(mid, "out")
                # conservation is a statement about INTERNAL nodes: a source has no inflow and a
                # sink has no outflow, and demanding equality there failed the two terminal nodes
                # (准时 47,920 in / 0 out) — the check was measuring the wrong thing.
                if inflow == 0 or outflow == 0:
                    continue
                close(f"D8 {pid} node {mid}: inflow equals outflow", inflow, outflow, tol=1e-9)
            for rule in panel.get("conservation") or []:
                node = rule["node"]
                if rule.get("whole"):
                    whole = _value(results.get(rule["whole"]) or {})
                    close(f"D8 {pid} {node} outflow equals :{rule['whole']}", total(node, "out"),
                          whole, tol=1e-9)
                else:
                    close(f"D8 {pid} {node}: inflow equals outflow", total(node, "in"),
                          total(node, "out"), tol=1e-9)

        # ── D9: a bubble chart's four channels must describe the same objects ─
        for panel in [x for x in dash.get("panels") or [] if x.get("kind") == "bubble"]:
            pid = panel["id"]
            print(f"\nD9  {pid}: x / y / size / color cover the same keys")
            channels = {k: panel.get(k) for k in ("x", "y", "size", "color") if panel.get(k)}
            keysets = {}
            for role, name in channels.items():
                res = results.get(name) or {}
                if res.get("status") != "ok":
                    check(f"D9 {pid} channel {role} ({name}) answers", res.get("status"), "ok")
                    continue
                if role == "color":
                    # a colour channel is a (key → category) map, so it may itself be a 2-key
                    # grouped count (plate × permit) — the object key is still the FIRST key.
                    check(f"D9 {pid} channel {role} ({name}) is a key→category map",
                          res.get("keys") in (1, 2), True)
                    keysets[role] = {tuple([r[0]]) for r in (res.get("rows") or [])}
                else:
                    check(f"D9 {pid} channel {role} ({name}) is cut by one dimension",
                          res.get("keys"), 1)
                    keysets[role] = {tuple(r[:-1]) for r in (res.get("rows") or [])}
            if len(keysets) == len(channels) and keysets:
                base_role, base = next(iter(keysets.items()))
                for role, ks in keysets.items():
                    missing = base - ks
                    if missing:
                        # a gap is allowed only when the panel SAYS it will report it: the chart
                        # then draws the object without the missing channel and counts the holes.
                        check(f"D9 {pid} {role} covers every {base_role} ({len(missing)} missing) "
                              f"— declare allow_missing to draw it anyway",
                              bool(panel.get("allow_missing")), True)

        # ── F1: cross-filter, on the compiler ──────────────────────────────
        print("\nF1  a filter narrows the same declaration, and the parts add up to the whole")
        dims = {}
        for panel in dash.get("panels") or []:
            emit = panel.get("emit_filter") or {}
            dim = emit.get("dimension")
            metric = panel.get("metric") or (panel.get("metrics") or [None])[0]
            if dim and dim not in dims and metric:
                res = results.get(metric) or {}
                if res.get("status") == "ok":
                    # dedupe: a 2-key emitter lists the same zone once per cell, and a
                    # duplicated value silently doubled the Σ identity (102,420 vs 51,210)
                    dims[dim] = {"source": metric,
                                 "values": list(dict.fromkeys(r[0] for r in (res.get("rows") or [])))}
        for dim, info in dims.items():
            declared = any(dim in (sqlgen.metrics(g).get(name).group_by or [])
                           for name in sqlgen.metrics(g) if sqlgen.metrics(g)[name])
            check(f"F1a {dim} is a declared :groupBy (its value set is a declaration)", declared, True)
            check(f"F1a {dim} offers at least two values to filter by", len(info["values"]) >= 2, True)

        def filtered_total(name: str, dim: str) -> tuple[float | None, list]:
            """Σ over the declared values, and the per-value numbers, through the compiler."""
            parts, total = [], 0.0
            for value in dims[dim]["values"]:
                res = run_dashboard.run_metric(cur, g, name, dim_filters={dim: value})
                if res.get("status") != "ok":
                    return None, [f"{dim}={value!r}: {res.get('refused')}"]
                v = res["rows"][0][0]
                parts.append((value, v))
                total += float(v or 0)
            return total, parts

        for name, dim, whole in (("tripCount", "routeVersion", "tripCount"),
                                 ("stopCount", "storeZone", "stopCount"),
                                 ("complaintCount", "liability", "complaintCount")):
            if dim not in dims:
                skill(f"F1b no panel emits a filter on {dim}")
                continue
            total, parts = filtered_total(name, dim)
            if total is None:
                check(f"F1b {name} filtered by {dim} answers for every value", parts, [])
                continue
            base = run_dashboard.run_metric(cur, g, whole)
            close(f"F1b Σ({name} | {dim}=v) over v equals the unfiltered {whole}", total,
                  (base.get("rows") or [[None]])[0][0], tol=1e-9)

        # the identity that catches "the filter reached the numerator only": a RATE cut by version must
        # equal the version-grouped row of the same rate
        if "routeVersion" in dims and "overloadRateByRouteVersion" in results:
            grouped = {str(r[0]): r[1] for r in (results["overloadRateByRouteVersion"].get("rows") or [])}
            for value, expected in grouped.items():
                res = run_dashboard.run_metric(cur, g, "overloadRate", dim_filters={"routeVersion": value})
                close(f"F1c :overloadRate filtered {value!r} equals its grouped row",
                      (res.get("rows") or [[None]])[0][0] if res.get("status") == "ok" else None,
                      expected, tol=1e-9)

        # a dimension the metric's grain cannot reach must REFUSE, by name
        unreachable = run_dashboard.run_metric(cur, g, "tripCountByRouteVersion",
                                              dim_filters={"storeZone": "core"})
        check("F1d an unreachable dimension is refused", unreachable.get("status"), "refused")
        check("F1d ... and the refusal says 'cannot filter'",
              "cannot filter :" in (unreachable.get("refused") or ""), True)

        # a value the declaration does not offer must be refused by the RUNNER (a silent 0 is worse)
        import subprocess
        probe = subprocess.run(
            [sys.executable, str(pathlib.Path(__file__).resolve().parents[1] / "compiler"
                                 / "run_dashboard.py"), "--profile", str(profile),
             "--filter", f"{next(iter(dims))}:__not_a_value__"],
            capture_output=True, text=True,
            cwd=str(pathlib.Path(__file__).resolve().parents[1] / "compiler"), timeout=180,
            env={**os.environ, "APP_SETTINGS": str(profile)})
        check("F1e an unknown filter value is refused (not answered as 0)", probe.returncode, 2)
        check("F1e ... and the refusal lists the allowed values",
              "allowed" in (probe.stdout or ""), True)

        events = dash.get("events") or []
        for ev in events:
            name = ev.get("metric") or ""
            print(f"\nD6  event marker {ev.get('id')!r} → {name} ({ev.get('at')})")
            res = results.get(name)
            if res is None:
                meta = run_dashboard.run_metric(cur, g, name)
                results[name] = meta
                res = meta
            check(f"D6 {name} is declared", res.get("status"), "ok")
            check(f"D6 {name} has a time axis", bool(res.get("time_bucket")), True)
            at = (ev.get("at") or "")[:10]
            xs = [str(r[0])[:10] for r in (res.get("rows") or [])]
            if xs:
                before = [x for x in xs if x <= at]
                after = [x for x in xs if x > at]
                check(f"D6 {name} has buckets on both sides of {at}",
                      bool(before) and bool(after), True)
    finally:
        cur.close()
        conn.close()

    print()
    for label in NOT_RUN:
        print(f"NOT RUN: {label}")
    print(f"\n{CHECKS} checks, {len(FAILS)} failed")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Per-ontology samples gate: every question the ontology offers must ANSWER, or refuse BY NAME.

The profile's `samples` are the questions a user is offered first — they are the ontology's front door.
A sample that rots (a metric renamed, an alias lost, a label reworded) is worse than no sample: the user
clicks it, gets a refusal, and concludes the ontology is broken.

So a sample is a GATE, not a suggestion. `samples.json` sits next to the profile and says what each
question must produce:

    {"samples": [
      {"question": "行程数", "expect": {"metric": "tripCount", "value": "4050"}},
      {"question": "按门店区域看破损箱数",
       "expect": {"metric": "damagedBoxesByStoreZone", "rows": {"core": "5496", "suburb": "2648"}}},
      {"question": "高风险司机数",
       "expect": {"refused_by_name": "AtRiskDriver has no owl:equivalentClass"}},
      {"question": "准时率", "expect": {"metric": "stopOnTimeRate", "value": "0.9357547354",
                                        "tolerance": 1e-6}}
    ]}

The numbers must be written from a SECOND route — a hand-written SQL, not this pipeline's own output —
otherwise the gate only proves "it still returns what it returned".

Usage:
    PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
    $PY check_samples.py --profile ontologies/logistics/logistics_settings.json
    $PY check_samples.py --profile … --file /some/other/samples.json

Exit: 0 all samples behave, 1 a sample failed, 2 nothing to check (no samples.json).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
# The COMPILER lives one directory up (features/ontology/compiler) and its modules import each
# other by bare name, so its directory goes on sys.path — a path that never depends on where this
# repository happens to live.
import pathlib as _pathlib
import sys as _sys
sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "compiler"))

# `nl` must be imported AFTER APP_SETTINGS is set: sqlgen applies the profile at import time, so a
# gate that imports it first measures the RETAIL ontology whatever --profile says. (Measured: the first
# run of this file answered '运费收入' with retail's orderRevenue, i.e. it gated the wrong ontology.)
nl = None  # imported in main()

OK = True


def check(label: str, got, want) -> None:
    global OK
    state = "PASS" if got == want else "FAIL"
    OK = OK and got == want
    print(f"  [{state}] {label}: got {got!r}, want {want!r}")


def _num(text) -> float | None:
    try:
        return float(str(text))
    except (TypeError, ValueError):
        return None


def _same(got, want, tol: float) -> bool:
    if got == want:
        return True
    a, b = _num(got), _num(want)
    return a is not None and b is not None and abs(a - b) <= max(tol, 1e-9 * max(abs(a), abs(b), 1.0))


def _run_route(route_sql: str) -> list[tuple]:
    """Run the sample's OWN hand-written SQL — the second route — on the profile's database.

    A sample whose expectation is a frozen number stops biting the moment the data moves: the gate
    then compares the pipeline to a number from last month. Declaring the ROUTE instead (`"route":
    "SELECT v.plate, sum(s.damaged_boxes)*1000.0/count(*) FROM … GROUP BY 1"`) keeps the check a
    comparison of two independent derivations at gate time, and nothing is copied by hand into a
    declaration (measured: a 60-row per-vehicle map was pasted into samples.json, which is exactly
    the kind of value that rots silently).
    """
    import psycopg2  # noqa: PLC0415 — the gate only needs it when a route is declared
    import actions   # noqa: PLC0415
    conn = psycopg2.connect(**actions.dsn())
    try:
        cur = conn.cursor()
        cur.execute(route_sql)
        return cur.fetchall()
    finally:
        conn.close()


def _rows_of(result: dict) -> dict[str, str]:
    """Grouped answers, in either of the two shapes the pipeline produces.

    A one-key GROUP BY comes back as `[{"key": "core", "value": 5496}, …]`; a metric with several keys
    comes back as row lists whose key columns come first and whose measure is last. Both are normalised
    here, because "the gate did not understand the answer" must not look like "the answer is wrong".
    """
    rows = result.get("rows") or []
    out: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict):
            key = row.get("key")
            if "key2" in row:
                key = f"{key} / {row.get('key2')}"
            if key is not None:
                out[str(key)] = "" if row.get("value") is None else str(row.get("value"))
            continue
        if not isinstance(row, (list, tuple)) or not row:
            continue
        key = " / ".join("" if c is None else str(c) for c in row[:-1])
        out[key] = "" if row[-1] is None else str(row[-1])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="the ontology's *_settings.json")
    ap.add_argument("--file", default="", help="samples.json (default: next to the profile)")
    args = ap.parse_args()

    profile = pathlib.Path(args.profile).expanduser().resolve()
    if not profile.is_file():
        print(f"no profile at {profile}")
        return 1
    spec_path = pathlib.Path(args.file).expanduser() if args.file else profile.parent / "samples.json"
    if not spec_path.is_file():
        print(f"NOT RUN — no samples.json at {spec_path}")
        print("  The profile's samples are still offered to users; they are just not gated yet.")
        return 2

    # Point the process at THIS ontology before anything imports the compiler.
    os.environ["APP_SETTINGS"] = str(profile)
    # FORCED, not setdefault: a gate must be deterministic. "温度趋势怎么样？" is a question the
    # ontology refuses by name, but with a local model reachable the pipeline asked the model
    # instead and the refusal turned into prose — so the same gate passed on one machine and
    # failed on another (measured: a box with qwen2.5:3b pulled vs one without). The gate
    # measures the RULES path; the model path is measured where it belongs.
    os.environ["NL_ANSWER_LLM"] = "0"
    global nl
    import nl as _nl                                       # noqa: PLC0415
    nl = _nl

    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    samples = spec.get("samples") or []
    if not samples:
        print(f"NOT RUN — {spec_path} declares no samples")
        return 2

    offered = json.loads(profile.read_text(encoding="utf-8")).get("samples") or []
    print(f"profile: {profile}")
    print(f"spec:    {spec_path}")
    print(f"samples: {len(samples)} gated · {len(offered)} offered by the profile")
    print()

    gated = {s.get("question") for s in samples}
    for question in offered:
        if question not in gated:
            print(f"  [WARN] offered but not gated: {question!r} — add it to {spec_path.name} "
                  f"(a sample nobody checks is the one that rots)")
    print()

    for entry in samples:
        question = entry.get("question") or ""
        expect = entry.get("expect") or {}
        tol = float(expect.get("tolerance") or 1e-9)
        resolved, out, refusal = False, None, ""
        try:
            out = nl.ask(question, confirm=True, record=False)
            resolved = True
        except Exception as exc:                                # noqa: BLE001
            refusal = str(exc)

        if expect.get("unresolved"):
            # A DOCUMENTED BACKLOG ITEM: the profile offers this question, the ontology cannot honour it
            # yet, and the reason says which declaration is missing — with the number a second route
            # gives, so the future declaration can be verified. Printed on every run; never counted as
            # a pass. The observed behaviour is appended, because "it fails" and "it answers wrongly"
            # are different backlog items.
            observed = "now answers" if resolved else "now refuses"
            print(f"  [UNRESOLVED] {question!r} ({observed}): "
                  f"{expect['unresolved'].splitlines()[0][:150]}")
            continue

        wants = expect.get("refused_by_names") or (
            [expect["refused_by_name"]] if expect.get("refused_by_name") else [])
        if wants:
            # ANY of the declared sentences is a refusal BY NAME. Measured: the same question,
            # against the same declarations, refuses as "metric 'telemetryTrend' is not on the menu"
            # on one machine and as "I can answer about: …" on another — the sentence depends on
            # which detection path fired, and pinning one machine's wording made the gate
            # environment-dependent. A refusal is a refusal; the set says which ones are acceptable.
            hit = next((w for w in wants if w in refusal), None)
            check(f"{question!r} refused BY NAME ({' | '.join(w[:28] for w in wants)})",
                  bool(hit), True)
            continue
        if not resolved:
            check(f"{question!r} answers", f"REFUSED: {refusal.splitlines()[0][:90]}", "answered")
            continue

        intent_name = (out.get("intent") or {}).get("name")
        if expect.get("metric"):
            check(f"{question!r} resolves to :{expect['metric']}", intent_name, expect["metric"])
        result = out.get("result") or {}
        if "value" in expect:
            got = result.get("value")
            check(f"{question!r} value", expect["value"] if _same(got, expect["value"], tol) else got,
                  expect["value"])
        if expect.get("route"):
            # the SECOND route is run NOW, not remembered
            try:
                route_rows = _run_route(str(expect["route"]))
            except Exception as exc:                            # noqa: BLE001
                check(f"{question!r} route runs", f"{type(exc).__name__}: {exc}"[:120], "ran")
                continue
            if len(route_rows) == 1 and len(route_rows[0]) == 1:
                want = route_rows[0][0]
                got = result.get("value")
                check(f"{question!r} value == the hand SQL", got if _same(got, want, tol) else got,
                      want)
            else:
                want_rows = {str(r[0]): "" if r[1] is None else str(r[1]) for r in route_rows}
                got_rows = _rows_of(result)
                same = set(got_rows) == set(want_rows) and all(
                    _same(got_rows[k], want_rows[k], tol) for k in want_rows)
                check(f"{question!r} rows == the hand SQL ({len(want_rows)} group(s))",
                      "match" if same else got_rows, "match")
            continue
        if "rows" in expect:
            got_rows = _rows_of(result)
            want_rows = {str(k): str(v) for k, v in (expect["rows"] or {}).items()}
            same = set(got_rows) == set(want_rows) and all(
                _same(got_rows[k], want_rows[k], tol) for k in want_rows)
            check(f"{question!r} rows ({len(want_rows)} group(s))", "match" if same else got_rows, "match")
            print(f"        [WARN] this expectation is a FROZEN number map — declare a \"route\" SQL "
                  f"instead so the gate compares two derivations at run time, not to last month's number")

    print()
    unresolved = [s for s in samples if (s.get("expect") or {}).get("unresolved")]
    if unresolved:
        print(f"{len(unresolved)} sample(s) UNRESOLVED — offered by the profile, not answerable yet. "
              "Each line says which declaration is missing (and the number a second route gives, so the "
              "future declaration can be verified).")
        print()
    if OK:
        print("ALL SAMPLES PASS" + (" (with UNRESOLVED items)" if unresolved else ""))
        return 0
    print("SOME SAMPLES FAILED — a sample a user clicks must answer or refuse by name; "
          "fix the declaration, the alias or the label (not the expected number).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

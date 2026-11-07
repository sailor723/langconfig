#!/usr/bin/env python3
"""Ask one business question through the ontology and print the whole trace.

The five stages, in the order the trace below proves they happened:

    1 menu       what exists (metrics / classes / actions), built from the compiled ontology
    2 interpret  rules first (0 ms), a model only when the rules are unsure — never SQL
    3 validate   the chosen name and parameters are on the menu, else REFUSED BY NAME
    4 execute    the ontology's own compiler turns the intent into SQL; the guard bounds it
    5 answer     a model may rewrite the prose — and is verified against the numbers, else the
                 deterministic template answers

Why a script and not a curl: the pipeline lives in the ontology repo and knows its own profile, so the
honest way to ask a question is to run it there — with the same refusal culture (`NOT RUN` named, never
faked) that the rest of this repo holds.

The pipeline is PER ONTOLOGY: each ontology's own workbench serves its Query section
(`<workbench>/query`) backed by `POST /api/nl`, and the assets that make matching work are that
ontology's profile (samples, aliases), its TTL labels and its tutorial. So this script targets an
ontology three ways — by key, by a profile file, or by a running workbench:

    --key logistics         ontologies/logistics/logistics_settings.json (or retail_graph/…)
    --profile <path>        an explicit profile file
    --workbench URL         the ontology's OWN Query surface: POST URL/api/nl (the same pipeline the
                            page uses, so the answer here is the answer the user sees)

Usage (from anywhere; PY must have psycopg2 + rdflib + langchain):

    PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
    $PY scripts/ask.py --profile <a *_settings.json> "行程数是多少"
    $PY scripts/ask.py --profile … "按门店区域看破损箱数" --json
    $PY scripts/ask.py --profile … "每千公里破损箱数" --no-polish     # deterministic prose only

Exit: 0 answered, 2 refused (a refusal is a result, printed by name), 1 the pipeline itself failed.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

REPO = pathlib.Path(os.environ.get("ONTOLOGY_REPO") or "/Users/weiping/dev/Learn/ontology").expanduser()


def _profile_for_key(key: str) -> pathlib.Path | None:
    """An ontology is a folder with a profile: `ontologies/<key>/<key>_settings.json`."""
    for candidate in (REPO / "ontologies" / key / f"{key}_settings.json",
                      REPO / "ontologies" / key / "settings.json",
                      REPO / "retail_graph" / f"{key}_settings.json",
                      REPO / "retail_graph" / "settings.json" if key == "retail" else None):
        if candidate and candidate.is_file():
            return candidate
    return None


def _ask_workbench(args) -> int:
    """Ask the ontology's own Query surface — the same call the /query page makes."""
    import urllib.error
    import urllib.request

    url = args.workbench.rstrip("/") + "/api/nl"
    body = json.dumps({"question": args.question, "confirm": bool(args.confirm)}).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as res:
            data = json.loads(res.read().decode() or "{}")
    except urllib.error.HTTPError as exc:                       # 4xx/5xx: the body is the answer
        raw = exc.read().decode()
        try:
            data = json.loads(raw)
        except Exception:                                       # noqa: BLE001
            print(f"ERROR: HTTP {exc.code} from {url}: {raw[:300]}")
            return 1
    except Exception as exc:                                    # noqa: BLE001
        print(f"ERROR: could not reach {url} ({type(exc).__name__}: {exc}). "
              "Is that ontology's workbench running?")
        return 1

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    elif not data.get("ok"):
        print("REFUSED (this is the answer, not an error):\n  "
              + str(data.get("refused") or data.get("error") or "see the trace"))
    else:
        print(f"question: {args.question}")
        print(f"workbench: {args.workbench}")
        for step in data.get("steps") or []:
            print(f"  {step.get('step')} · {step.get('ms')} ms  "
                  + str(step.get("detail") or "")[:140])
        result = data.get("result") or {}
        print(f"\nintent:  {(data.get('intent') or {}).get('kind')} "
              f"{(data.get('intent') or {}).get('name')}")
        if result:
            print(f"value:   {result.get('value')}")
            if result.get("sql"):
                print("sql:     " + str(result["sql"]).replace("\n", " ")[:300])
        if data.get("answer"):
            print(f"answer ({data.get('answer_source')}):\n  "
                  + str(data["answer"]).replace("\n", "\n  "))
        if data.get("needs_confirmation"):
            print("\nneeds_confirmation — re-run with --confirm")
    return 0 if data.get("ok") else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--key", help="the ontology's folder name under ontologies/ (e.g. logistics)")
    ap.add_argument("--profile", help="the ontology profile (*_settings.json) — overrides --key")
    ap.add_argument("--json", action="store_true", help="print the raw response as JSON")
    ap.add_argument("--workbench", help="a running workbench URL; asks through its own /api/nl")
    ap.add_argument("--confirm", action="store_true",
                    help="answer a question that involves slots (time window / customer)")
    ap.add_argument("--no-polish", action="store_true",
                    help="skip the LLM polish: the deterministic template answers")
    args = ap.parse_args()

    if args.workbench:
        return _ask_workbench(args)

    if not args.profile and not args.key:
        print("ERROR: pass --key <ontology>, --profile <profile.json>, or --workbench <url>")
        return 1
    if args.profile:
        profile = pathlib.Path(args.profile).expanduser().resolve()
    else:
        profile = _profile_for_key(args.key)
    if profile is None or not profile.is_file():
        print(f"ERROR: no profile for {args.profile or args.key!r}"
              + (f" (looked for ontologies/{args.key}/{args.key}_settings.json and "
                 f"retail_graph/{args.key}_settings.json)" if args.key else ""))
        return 1
    if not (REPO / "retail_graph").is_dir():
        print(f"ERROR: no compiler at {REPO / 'retail_graph'} (set ONTOLOGY_REPO)")
        return 1

    os.environ["APP_SETTINGS"] = str(profile)
    if args.no_polish:
        os.environ["NL_ANSWER_LLM"] = "0"
    sys.path.insert(0, str(REPO / "retail_graph"))

    try:
        import nl  # noqa: PLC0415
    except Exception as exc:                                    # noqa: BLE001
        print(f"ERROR: the pipeline did not import ({type(exc).__name__}: {exc})")
        return 1

    try:
        out = nl.ask(args.question, confirm=args.confirm, record=False)
    except nl.NlRefusal as exc:
        # A refusal is an ANSWER here: it names what is missing. Exit 2 keeps it distinct from a
        # crash, because "off-menu" and "the database fell over" are not the same event.
        text = getattr(exc, "polished", None) or str(exc)
        if args.json:
            print(json.dumps({"ok": False, "refused": str(exc), "text": text}, ensure_ascii=False,
                             indent=1))
        else:
            print("REFUSED (this is the answer, not an error):\n  " + str(text))
        return 2
    except Exception as exc:                                    # noqa: BLE001
        print(f"ERROR: the pipeline failed ({type(exc).__name__}: {exc})")
        return 1

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        return 0

    steps = out.get("steps") or []
    print(f"question: {args.question}")
    print(f"profile:  {profile}")
    print()
    for step in steps:
        ms = step.get("ms")
        where = step.get("backend") or step.get("path") or ""
        detail = str(step.get("detail") or "").replace("\n", " ")
        print(f"  {step.get('step')} · {ms} ms  {detail[:150]}"
              + (f"   [{where}]" if where else ""))
    intent = out.get("intent") or {}
    print()
    print(f"intent:  {intent.get('kind')} {intent.get('name')}"
          + (f" slots={intent['slots']}" if intent.get("slots") else ""))
    result = out.get("result") or {}
    if result:
        print(f"value:   {result.get('value')}")
        notes = result.get("notes") or []
        if notes:
            print("guard:   " + " · ".join(str(n) for n in notes)[:300])
        if result.get("sql"):
            print("sql:     " + str(result["sql"]).replace("\n", " ")[:400])
    # `answer` is the prose itself and `answer_source` says who wrote it (llm or template) — the
    # polish is only accepted when the numbers survive, so the source is part of the evidence.
    answer = out.get("answer") or ""
    source = out.get("answer_source") or ""
    if answer:
        print(f"answer ({source}):")
        print("  " + str(answer).replace("\n", "\n  "))
    if out.get("needs_confirmation"):
        print("\nneeds_confirmation: the intent has slots — re-run with --confirm to run it")
        understanding = out.get("understanding") or {}
        if understanding.get("text"):
            print("  it understood: " + str(understanding["text"]).replace("\n", " "))
    print(f"\ntotal: {out.get('total_ms')} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

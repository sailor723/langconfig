#!/usr/bin/env python3
"""Smoke test a LangConfig install: database, seed content, API, and a live turn.

Run it after `scripts/seeds/seed_all.py` and after starting the backend.

    cd backend
    .venv/bin/python scripts/smoke_test.py                    # DB + seed + API
    .venv/bin/python scripts/smoke_test.py --chat 112         # also run one real turn
    .venv/bin/python scripts/smoke_test.py --api http://localhost:8765

Every check prints PASS/FAIL with the value it saw, so a failure says what is
wrong rather than just that something is. Exit code is non-zero if any check
fails, which makes it usable in a fresh-machine checklist.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text                      # noqa: E402
from db.database import SessionLocal             # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    results.append((PASS if ok else FAIL, label, detail))
    print(f"  [{PASS if ok else FAIL}] {label}{' — ' + detail if detail else ''}")
    return ok


def skip(label: str, why: str) -> None:
    results.append((SKIP, label, why))
    print(f"  [SKIP] {label} — {why}")


def get(url: str, timeout: int = 10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode() or "null")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default="http://localhost:8765", help="backend base URL")
    ap.add_argument("--chat", type=int, metavar="AGENT_ID",
                    help="also send one real turn to this agent (costs API tokens)")
    ap.add_argument("--no-api", action="store_true", help="database checks only")
    args = ap.parse_args()

    # ── 1. Database reachable, and what the seed put in it ───────────────
    print("\n[1] database")
    db = SessionLocal()
    counts: dict[str, int] = {}
    try:
        for table in ("deep_agent_templates", "custom_tools", "models", "skills",
                      "settings_documents", "projects", "chat_sessions"):
            counts[table] = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
        check("connected to PostgreSQL", True, ", ".join(f"{k}={v}" for k, v in counts.items()))

        # ── 2. the five migrated legs ────────────────────────────────────
        print("\n[2] seed content (agents · tools · models · skills · settings)")
        check("agents present", counts["deep_agent_templates"] > 0,
              f"{counts['deep_agent_templates']} agent(s)")
        check("tools present", counts["custom_tools"] > 0,
              f"{counts['custom_tools']} tool(s)")
        check("model catalog present", counts["models"] >= 25,
              f"{counts['models']} model(s)")

        vision = db.execute(text(
            "SELECT count(*) FROM models WHERE capabilities->>'vision' = 'true'")).scalar()
        flash = db.execute(text(
            "SELECT capabilities->>'vision' FROM models WHERE model_id = 'deepseek-flash'")).scalar()
        check("a vision model exists", vision > 0, f"{vision} model(s) with capabilities.vision")
        check("deepseek-flash carries vision (model preset step ran)", str(flash).lower() == "true",
              f"deepseek-flash vision={flash}")

        reader = db.execute(text(
            "SELECT count(*) FROM custom_tools WHERE tool_id = 'read_any_file'")).scalar()
        check("read_any_file tool seeded", reader == 1,
              "1 row" if reader == 1 else f"{reader} row(s) — run scripts/seed_read_any_file_tool.py")

        check("skills indexed from disk", counts["skills"] > 0,
              f"{counts['skills']} skill(s)")
        check("settings documents seeded", counts["settings_documents"] > 0,
              f"{counts['settings_documents']} namespace(s)")

        ws = db.execute(text(
            "SELECT document FROM settings_documents WHERE ns = 'workspace'")).scalar() or {}
        check("workspace points at an existing directory",
              bool(ws.get("workspace_path")) and Path(ws["workspace_path"]).exists(),
              str(ws.get("workspace_path")))
    except Exception as exc:                      # noqa: BLE001
        check("database checks", False, f"{type(exc).__name__}: {exc}")
    finally:
        db.close()

    # ── 3. API surface ───────────────────────────────────────────────────
    print("\n[3] backend API")
    if args.no_api:
        skip("API checks", "--no-api")
    else:
        for label, path, ok_test in [
            ("health", "/api/chat/health", lambda d: True),
            ("setup status", "/api/settings/setup-status", lambda d: True),
            ("agents list", "/api/deepagents/?public_only=false", lambda d: len(d) > 0),
            ("model catalog", "/api/settings/models", lambda d: len(d) > 0),
        ]:
            try:
                status, data = get(f"{args.api}{path}")
                check(f"GET {path}", status == 200 and bool(ok_test(data)),
                      f"HTTP {status}")
            except Exception as exc:              # noqa: BLE001
                check(f"GET {path}", False, f"{type(exc).__name__}: {exc}")

        # A live turn proves the model wiring, credentials and agent build.
        if args.chat:
            print("\n[4] live turn")
            try:
                body = json.dumps({"agent_id": args.chat,
                                   "message": "Reply with the single word: ready"}).encode()
                req = urllib.request.Request(
                    f"{args.api}/api/chat/start", data=body,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    session = json.loads(r.read().decode())
                sid = session.get("session_id")
                check("session created", bool(sid), str(sid))
                post = json.dumps({"message": "Reply with the single word: ready"}).encode()
                req = urllib.request.Request(
                    f"{args.api}/api/chat/{sid}/message", data=post,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=180) as r:
                    reply = json.loads(r.read().decode())
                text_out = json.dumps(reply)[:120]
                check("agent answered", bool(reply), text_out)
            except Exception as exc:              # noqa: BLE001
                check("live turn", False, f"{type(exc).__name__}: {exc}")
        else:
            skip("live turn", "pass --chat <agent_id> to include one")

    failed = [r for r in results if r[0] == FAIL]
    print(f"\n=== {len(results) - len(failed)} passed, {len(failed)} failed, "
          f"{len([r for r in results if r[0] == SKIP])} skipped ===")
    for _, label, detail in failed:
        print(f"  FAILED: {label} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

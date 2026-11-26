"""Register a NEW ontology key from inside a conversation.

The four-rung flow a customer actually asks for — 「这是我们的 Excel，做成库、做成本体、做成看板」 — used to
stop dead after the database was built: a key needs a profile directory, a `gates.json` declaration, a
Settings row and a version number, and all four live in the repository, which an agent may not write. So
the missing rung was always a person at a shell running `add_ontology_builder.py --no-agent`.

This module is that rung, as a service the `ontology_register` builtin tool calls. It writes exactly what
that script writes, in the same order, with two deliberate differences:

* **the version comes from `features/ontology/versioning.py`** — the customer supplies the name, the
  platform assigns `<name>_v<N>`, and a number is never reused;
* **no `.env` line and no new secret.** The database was built on this deployment's own server, so the
  profile's dsn references the platform's existing `${ONTOLOGY_DB_*}` variables. Appending
  `SOMETHING_V2_DB_PASSWORD=` would be a second place for one password to be blank.

What it refuses, and why each refusal is a real failure:

* a name that is not a slug (`[a-z][a-z0-9_]*`) — the key becomes a directory, a URL fragment and a
  turtle prefix;
* a database that does not answer — registering an ontology over a typo produces an empty build that
  looks like "the data was thin";
* a key whose profile directory already has content — that key belongs to a build that already ran;
* `kind` outside `customer | demo | trial | tutorial`.

Idempotent in the case that matters: if the family's latest build is registered but **not built** (no
`01-structure.ttl` yet), a second call returns THAT key instead of minting v2. A retry is not a new
version.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import pathlib

from features.ontology import versioning as V

FEATURE = pathlib.Path(__file__).resolve().parent.parent / "features" / "ontology"
PROFILES = FEATURE / "profiles"
GATES = FEATURE / "gates.json"
REPO = FEATURE.parents[2]

_GATE_FAMILIES = ["check_structure", "check_ontology_generic", "check_samples", "check_dashboard"]
_BUILT = "01-structure.ttl"


class RegisterError(ValueError):
    """A registration that cannot be made as asked — the message is what the agent repeats to the user."""


def _gates_doc() -> dict:
    try:
        return json.loads(GATES.read_text(encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        return {}


def _gate_keys() -> set[str]:
    return {str(k) for k in _gates_doc() if V.KEY_RE.fullmatch(str(k))}


def _db_reachable(datasource: str, dsn: dict | None = None) -> tuple[bool, str]:
    """Does this database answer to the agent's own credential? A typo here is a silent empty build.

    `dsn` is the profile-style connection the caller declared (`{"host": "${TPCH_DB_HOST:-127.0.0.1}",
    "port": ..., "user": ..., "password": ...}`, `dbname` ignored — `datasource` is the database).
    Measured on TPC-H: its SF0.1 database lives on a SECOND local server (:5432, role weiping) while the
    platform's own ontology database is :5433 / role langconfig, so a registration that only ever tried
    the platform credentials refused a database that was running fine. A registration is the moment the
    ontology is bound to a server, so it has to be able to state one.
    """
    import os

    import psycopg2

    if dsn:
        sys.path.insert(0, str(FEATURE / "compiler"))
        import dsn as _dsn                                      # noqa: PLC0415

        resolved = _dsn.resolved({"dsn": dict(dsn, dbname=datasource)})
        params = {
            "host": resolved.get("host") or "127.0.0.1",
            "port": int(resolved.get("port") or 5432),
            "user": resolved.get("user") or None,
            "password": resolved.get("password") or None,
            "dbname": datasource,
            "connect_timeout": 5,
        }
    else:
        params = {
            "host": os.environ.get("ONTOLOGY_DB_HOST") or os.environ.get("PGHOST") or "127.0.0.1",
            "port": int(os.environ.get("ONTOLOGY_DB_PORT") or os.environ.get("PGPORT") or 5432),
            "user": os.environ.get("ONTOLOGY_DB_USER") or os.environ.get("PGUSER") or None,
            "password": os.environ.get("ONTOLOGY_DB_PASSWORD") or os.environ.get("PGPASSWORD") or None,
            "dbname": datasource,
            "connect_timeout": 5,
        }
    try:
        conn = psycopg2.connect(**params)
    except Exception as exc:                                         # noqa: BLE001
        return False, str(exc).strip()
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*) from information_schema.tables where table_schema='public'")
            n = cur.fetchone()[0]
        return True, f"{n} table(s) in public"
    finally:
        conn.close()


def _profile_skeleton(key: str, datasource: str, theme: str, *, note: str,
                      dsn: dict | None = None) -> dict:
    """The smallest profile the gates can run against; the builder fills the rest.

    Every value here is either a platform-wide default (`${ONTOLOGY_DB_*}`) or a fact this call was told.
    Nothing is invented about the data: `guard.big_tables` and `default_window_days` stay absent on
    purpose — they are DECISIONS that belong to the build (S0/S4), and a skeleton that guessed them would
    hand the agent a wrong answer it never had to justify.
    """
    return {
        "_profile": (f"{key} —— {theme or key}：由 ontology_register 登记（{note}）。"
                     f"guard.big_tables / default_window_days / samples 由构建阶段（S0/S4/S5）按实测决定，"
                     f"登记时不预设。"),
        "title": theme or key,
        "ns": f"https://cube.local/ontology/{key}#",
        "ontology_dir": "ontology",
        "overlay": "metrics_ext.ttl",
        "dsn": (dict(dsn, dbname=datasource) if dsn else {
            "host": "${ONTOLOGY_DB_HOST:-127.0.0.1}",
            "port": "${ONTOLOGY_DB_PORT:-5432}",
            "dbname": datasource,
            "user": "${ONTOLOGY_DB_USER}",
            "password": "${ONTOLOGY_DB_PASSWORD}",
        }),
        "guard": {"enabled": True, "max_rows": 500, "statement_timeout_ms": 8000,
                  "max_plan_rows": 5000000},
        "features": {"actions": False, "lane_b": False, "tutorial": True},
    }


def _brief(key: str, *, name: str, datasource: str, theme: str, kind: str, actor: str,
           now: str) -> str:
    """`_brief.md` — the facts a build must not re-derive, in the words of whoever registered it."""
    return (
        f"# {key}\n\n"
        f"登记于 {now}" + (f"（{actor}）" if actor else "") + "，由 `ontology_register` 写入。\n\n"
        f"| 事实 | 值 |\n|---|---|\n"
        f"| 客户给的名字 | `{name}` |\n"
        f"| 本体 key（平台给版本） | `{key}` |\n"
        f"| 数据库 | `{datasource}` |\n"
        f"| 主题 | {theme or '（未填：问用户）'} |\n"
        f"| 存在形式 | {kind} |\n\n"
        "## 这份文件是什么\n\n"
        "它是这个本体的**输入**（客户/运维签过的事实），不是声明的一部分，也不参与编译。构建时先读它，\n"
        "把这里已经答过的问题当成已答；这里没写的（粒度、阈值、什么算\"正常\"）仍然要问人，或写成拒绝。\n"
    )


def register(name: str, datasource: str, *, theme: str = "", kind: str = "customer",
             actor: str = "", note: str = "", probe: bool = True, dsn: dict | None = None) -> dict:
    """Register `name` as a new ontology family member and return what was written.

    Returns `{"ok": True, "key": ..., "version": ..., "in_progress": bool, "wrote": [...],
    "next": "..."}` or raises `RegisterError` with a sentence that says what to fix.
    """
    raw = (name or "").strip()
    base = raw.lower()
    ds = (datasource or "").strip()
    # Case is a typing habit ("Sun Hing"), so it is normalised. Everything else is NOT translated: a
    # hyphen or a space turned into "_" would quietly accept a typo as a plausible key, and a Chinese
    # name cannot be a directory name / URL fragment / turtle prefix at all — both must go back to the
    # user, who is the only one who knows the customer's short English name.
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", raw):
        raise RegisterError(
            f"name {name!r} is not usable as a key: it becomes a directory, a URL fragment and a turtle "
            f"prefix, so it must be ASCII letters/digits/underscore starting with a letter "
            f"(e.g. 'sunhing'). Translating 「新鸿」 or 'sun-hing' silently would register a key nobody "
            f"asked for — ask the user for the customer's short English name.")
    if not V.KEY_RE.fullmatch(base):
        raise RegisterError(f"name {name!r} does not produce a valid key ({base!r})")
    if kind not in V.KINDS:
        raise RegisterError(f"kind {kind!r} is not one of {sorted(V.KINDS)}")
    if not ds or not V.KEY_RE.fullmatch(ds):
        raise RegisterError(f"datasource {datasource!r} must be a database name (lowercase, digits, "
                            f"underscore) — the name `db_build_from_file` created")

    registry = V.load(PROFILES / V.REGISTRY_NAME)
    known = V.existing_keys(PROFILES, gate_keys=_gate_keys())

    # A RETRY IS NOT A NEW VERSION. If the family's latest build was registered and never built, the
    # right answer is that key — minting v2 here would leave an empty v1 nobody will ever finish.
    latest = V.latest_of(base, registry=registry)
    if latest:
        latest_dir = PROFILES / latest
        if latest_dir.is_dir() and not (latest_dir / _BUILT).exists():
            return {"ok": True, "key": latest, "version": V.parse_key(latest)[1], "in_progress": True,
                    "wrote": [], "datasource": ds,
                    "next": (f"{latest} 已经登记但还没建（没有 {_BUILT}）。继续建它，不要新开版本："
                             f"ontology_open(ontology_key=\"{latest}\", dest=\"work/{latest}\") 之后按阶梯走。")}

    key, version = V.key_for(base, registry=registry, known=known)
    target = V.profile_dir(key, root=PROFILES)
    if target.exists() and any(target.iterdir()):
        raise RegisterError(f"{target.name} already has content — that key belongs to a build that ran; "
                            f"pick another name (a version is never reused)")

    if probe:
        reachable, detail = _db_reachable(ds, dsn)
        if not reachable:
            raise RegisterError(f"database {ds!r} does not answer from this deployment: {detail}. "
                                f"Registering over a typo produces an empty ontology that looks like thin data.")

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wrote: list[str] = []

    target.mkdir(parents=True, exist_ok=True)
    profile_path = target / f"{key}_settings.json"
    profile_path.write_text(
        json.dumps(_profile_skeleton(key, ds, theme, note=note or kind, dsn=dsn),
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    wrote.append(str(profile_path.relative_to(REPO)))
    brief_path = target / "_brief.md"
    brief_path.write_text(_brief(key, name=base, datasource=ds, theme=theme, kind=kind, actor=actor, now=now),
                          encoding="utf-8")
    wrote.append(str(brief_path.relative_to(REPO)))

    gates = _gates_doc()
    if key not in gates:
        gates[key] = {
            "why": (f"{key}：{theme or base}（{kind}），由 ontology_register 登记；"
                    f"构建中，发布前不参与仓库门禁。"),
            "pending_install": f"registered by ontology_register — not built yet ({now})",
            "profile": list(_GATE_FAMILIES),
        }
        GATES.write_text(json.dumps(gates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        wrote.append(str(GATES.relative_to(REPO)))

    entry = V.record(registry, key=key, kind=kind, theme=theme or base, datasource=ds)
    V.save(registry, PROFILES / V.REGISTRY_NAME)
    wrote.append(str((PROFILES / V.REGISTRY_NAME).relative_to(REPO)))

    settings_ok, settings_msg = _register_in_settings(key, theme or key, kind, entry["version"])
    return {
        "ok": True, "key": key, "version": version, "in_progress": False, "datasource": ds,
        "kind": kind, "wrote": wrote,
        "settings": settings_msg, "settings_written": settings_ok,
        "next": (f"用 ontology_open(ontology_key=\"{key}\", dest=\"work/{key}\") 打开骨架，按 "
                 f"build-ontology-from-db 的阶梯建（S0 之后要先停下来给人看草图）；"
                 f"仪表盘在 S6（dashboard.json），发布走 ontology_publish(ontology_key=\"{key}\", …)。"),
    }


def _register_in_settings(key: str, label: str, kind: str, version: int) -> tuple[bool, str]:
    """Add the row the workbench lists. A failure here is reported, never fatal: the files are the
    artefact and the Settings document can be re-written by re-running just this step."""
    try:
        from core import settings as cs                                     # noqa: PLC0415
        from core.settings.store import OWNER_USER_ID, put_document         # noqa: PLC0415
        from db.database import SessionLocal                                # noqa: PLC0415

        db = SessionLocal()
        try:
            doc = dict(cs.resolve(db, "ontology").value or {})
            items = [dict(x) for x in (doc.get("items") or [])]
            row = {"key": key, "label": label, "url": "",
                   "profile": f"{key}/{key}_settings.json",
                   "note": "registered by ontology_register", "enabled": True,
                   "version": version, "kind": kind, "latest": True, "superseded_by": ""}
            existing = next((i for i in items if str(i.get("key")) == key), None)
            if existing is not None:
                existing.update({k: v for k, v in row.items() if k != "note"})
            else:
                items.append(row)
            doc["items"] = items
            doc.setdefault("show_sql", True)
            put_document(db, "ontology", doc, user_id=OWNER_USER_ID)
            return True, f"Settings → Ontology row {'refreshed' if existing is not None else 'added'}"
        finally:
            db.close()
    except Exception as exc:                                                # noqa: BLE001
        return False, f"Settings row NOT written ({type(exc).__name__}: {exc}) — re-run the registration"


if __name__ == "__main__":                                                  # a manual dry run
    import sys

    if len(sys.argv) < 3:
        print("usage: ontology_register.py <name> <datasource> [--apply]")
        print(f"next version for a name: python -c 'from features.ontology import versioning as V; "
              f"print(V.key_for(\"<name>\"))'")
        raise SystemExit(2)
    apply_ = "--apply" in sys.argv
    if not apply_:
        reg = V.load(PROFILES / V.REGISTRY_NAME)
        print(V.key_for(sys.argv[1], registry=reg, known=V.existing_keys(PROFILES, gate_keys=_gate_keys())))
        raise SystemExit(0)
    print(json.dumps(register(sys.argv[1], sys.argv[2], kind="trial"), ensure_ascii=False, indent=2))

#!/usr/bin/env python3
"""Register a new ontology BUILDER: one command for the five things a new theme+dataset needs.

Why a script: building an ontology for a new business theme needs more than "point the agent at
another database". Five artefacts have to agree, and forgetting any one of them fails in a way that
looks unrelated (an agent that writes into the previous key's directory, a repo-wide red gate suite,
a 500 from the dashboard endpoint, an ontology missing from Settings). Measured on sunhing_v1:

    1. the builder agent          skill_params (datasource + ontology_key), the prompt text that
                                  names both, and its own `datasource` binding
    2. gates.json                 a declaration for the key, or `ontology_gates.py` reports
                                  "has no gate declaration" and the whole repo goes red
    3. Settings → Ontology        the ontology namespace document (`items[]`), or the app has no
                                  row and the workbench never lists it
    4. .env                       the password variable the profile's dsn will reference
    5. the profile directory      `profiles/<key>/` — created by the BUILDER when it runs, so this
                                  script only checks it does not already exist with content

What this script does NOT do: create the database, or invent the theme. The dataset must already be
reachable from this machine (Postgres), because the builder reads it read-only.

    # dry run: print every change, touch nothing
    python backend/scripts/seeds/in/add_ontology_builder.py \
        --key chinook_v1 --datasource chinook --theme "音乐零售"

    # apply
    python backend/scripts/seeds/in/add_ontology_builder.py \
        --key chinook_v1 --datasource chinook --theme "音乐零售" --apply

Idempotent: an existing agent row is updated in place, an existing gates.json entry is left alone
(and reported), an existing Settings row is updated. Exit codes: 0 ok, 1 a problem it will not
paper over, 2 bad arguments.

NAMING (decided 2026-11-12, option A): the customer supplies a NAME, the platform assigns the
version. `--base sunhing` becomes `sunhing_v<N>` with N = one past the highest N that already
exists anywhere (registry, profiles/, gates.json) — so a build is never overwritten in place and
a number is never reused. `--key` still works for a name that has no version to assign (legacy
`abc`, `tpch`). See `features/ontology/versioning.py` for the rules and `--kind` for why the key
exists (customer | demo | trial | tutorial).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve()
BACKEND = HERE.parents[3]                      # backend/
REPO = BACKEND.parent
GATES = BACKEND / "features" / "ontology" / "gates.json"
PROFILES = BACKEND / "features" / "ontology" / "profiles"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from features.ontology import versioning as V  # noqa: E402  (the numbering rules, and the registry)
#: Which seed writes the agent row. A DOCUMENT builder starts from uploaded files instead of an existing
#: database, so its prompt and tool list differ; everything else about registration is identical. Overriding
#: this env var is how the document wrapper keeps ONE definition of "a builder is registered" without
#: overwriting the agent it just created (measured: the DB seed ran last and replaced the document prompt).
SEED = pathlib.Path(os.environ.get("ONTOLOGY_SEED_SCRIPT")
                    or (BACKEND / "scripts" / "seeds" / "in" / "seed_ontology_build_agent.py"))
ENV = REPO / ".env"


def _ok(msg: str) -> None:
    print(f"  OK   {msg}")


def _warn(msg: str) -> None:
    print(f"  WARN {msg}")


def _todo(msg: str) -> None:
    print(f"  PLAN {msg}")


def _dotenv() -> dict:
    """`.env` as a dict — the probe must use the deployment's own credentials, not bare defaults."""
    out = {}
    if not ENV.is_file():
        return out
    for raw in ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _db_exists(datasource: str) -> tuple[bool, str]:
    """Is the database reachable from THIS machine? Read-only probe, no password guessing."""
    env = dict(os.environ)
    for k, v in _dotenv().items():
        env.setdefault(k, v)
    env.setdefault("PGPASSWORD", env.get("POSTGRES_PASSWORD", ""))
    try:
        p = subprocess.run(
            ["psql", "-h", env.get("PGHOST") or env.get("POSTGRES_HOST") or "127.0.0.1",
             "-p", env.get("PGPORT") or env.get("POSTGRES_PORT") or "5432",
             "-U", env.get("PGUSER") or env.get("POSTGRES_USER") or "postgres",
             "-d", "postgres", "-At",
             "-c", f"SELECT 1 FROM pg_database WHERE datname = '{datasource}'"],
            capture_output=True, text=True, timeout=20, env=env)
    except Exception as exc:                                    # noqa: BLE001
        return False, f"probe failed ({type(exc).__name__}: {exc})"
    if p.returncode != 0:
        return False, (p.stderr or "").strip().splitlines()[0][:200]
    return p.stdout.strip() == "1", ""


def _env_var_for(key: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", key.upper()).strip("_") + "_DB_PASSWORD"


def _gate_keys() -> set[str]:
    """Keys already declared in gates.json — a new number has to clear those too, not only profiles/."""
    try:
        return {str(k) for k in json.loads(GATES.read_text(encoding="utf-8"))}
    except Exception:                                                   # noqa: BLE001
        return set()


def step_agent(key: str, datasource: str, theme: str, *, apply: bool) -> bool:
    print("\n[1] builder agent")
    if not SEED.is_file():
        _warn(f"missing seed script {SEED}")
        return False
    env = dict(os.environ)
    env.update({
        "ONTOLOGY_KEY": key,
        "DATASOURCE": datasource,
        # setdefault, not assign: a DOCUMENT builder names itself "Document Ontology Builder (key)", and
        # overwriting that made the registration create a SECOND row next to the one it had just written
        # (measured: agents 402 and 403 for the same key).
        "BUILDER_AGENT_NAME": env.get("BUILDER_AGENT_NAME") or f"Ontology Builder ({key})",
        "THEME": theme,
    })
    if not apply:
        _todo(f"{SEED.name}  ONTOLOGY_KEY={key} DATASOURCE={datasource} "
              f"BUILDER_AGENT_NAME='Ontology Builder ({key})'")
        return True
    p = subprocess.run([sys.executable, str(SEED)], capture_output=True, text=True, env=env,
                       cwd=str(BACKEND))
    for line in (p.stdout or "").strip().splitlines()[-6:]:
        print("   " + line)
    if p.returncode != 0:
        _warn((p.stderr or "").strip()[-400:])
        return False
    _ok(f"agent 'Ontology Builder ({key})' seeded (datasource={datasource})")
    return True


def step_agent_note(key: str, *, base: str, version: int, kind: str) -> bool:
    """The registration is versioned per key; say so where a human reads the summary."""
    print(f"   key {key} = {base} v{version} ({kind}) — a rebuild of {base} becomes "
          f"{base}_v{version + 1}, never a rewrite of this one")
    return True


def step_gates(key: str, *, apply: bool, family_extra: set[str] | None = None) -> bool:
    print("\n[2] gates.json declaration")
    try:
        decl = json.loads(GATES.read_text(encoding="utf-8"))
    except Exception as exc:                                    # noqa: BLE001
        _warn(f"gates.json unreadable: {exc}")
        return False
    if key in decl:
        _ok(f"already declared ({', '.join(decl[key].get('profile') or []) or 'no families'})")
        return True
    entry = {
        "why": (f"{key}：新建本体。构建中的声明在发布前不参与仓库门禁；apply 之后清掉 "
                f"pending_install，并写上门禁的实测数字。"),
        "pending_install": "staged by add_ontology_builder.py — not built yet",
        "profile": ["check_structure", "check_ontology_generic", "check_samples", "check_dashboard"],
    }
    # A profile built over an ABox needs the two reasoning families too, and forgetting them here is
    # exactly how a gate goes silently unrun: `publish` runs the families this declaration names, so an
    # ABox profile declared with four SQL families would stage and apply without any reasoning checked.
    # The families are added when the profile actually carries `abox.ttl` — decided here by an argument
    # rather than by looking at a directory the builder has not created yet.
    if "abox" in family_extra:
        entry["profile"] = entry["profile"] + ["check_abox", "check_abox_sync"]
    if not apply:
        _todo(f"would add {key} → families {entry['profile']}")
        return True
    decl[key] = entry
    GATES.write_text(json.dumps(decl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _ok(f"declared {key} with 4 families")
    return True


def step_settings(key: str, theme: str, *, apply: bool,
                  meta: dict | None = None) -> bool:
    print("\n[3] Settings → Ontology (the `ontology` namespace document)")
    sys.path.insert(0, str(BACKEND))
    try:
        from core import settings as cs                                 # noqa: PLC0415
        from core.settings.store import OWNER_USER_ID, put_document     # noqa: PLC0415
        from db.database import SessionLocal                            # noqa: PLC0415
    except Exception as exc:                                    # noqa: BLE001
        _warn(f"settings store unavailable: {exc}")
        return False
    db = SessionLocal()
    try:
        doc = dict(cs.resolve(db, "ontology").value or {})
        items = [dict(x) for x in (doc.get("items") or [])]
        row = {"key": key, "label": theme or key, "url": "", "profile": f"{key}/{key}_settings.json",
               "note": "registered by add_ontology_builder.py", "enabled": True}
        # version/bookkeeping is additive: the workbench reads key/label/url/profile/enabled and
        # ignores the rest, while an audit can answer "is this the build the customer runs?" from
        # the document itself instead of from a directory listing.
        if meta is not None:
            row.update(meta)
        existing = next((i for i in items if str(i.get("key")) == key), None)
        if existing is not None:
            existing.update({k: v for k, v in row.items() if k != "note"})
            _ok("already listed — refreshed its label/profile")
            if not apply:
                return True
        else:
            if not apply:
                _todo(f"would add item {row}")
                return True
            items.append(row)
            _ok("added to the ontology list")
        doc["items"] = items
        doc.setdefault("show_sql", True)
        put_document(db, "ontology", doc, user_id=OWNER_USER_ID)
    finally:
        db.close()
    return True


def _family_password_var(base: str) -> str | None:
    """The variable an existing build of this family already declares in its profile's dsn.

    A rebuild of `sunhing` reads the SAME database, so it must not invent
    `SUNHING_V2_DB_PASSWORD`: two variables for one password is how a deployment ends up with one
    of them blank, and the profile's dsn is what the gates execute against.
    """
    for cand in sorted(PROFILES.glob(f"{base}*/")):
        if not cand.is_dir() or not cand.name.startswith(base):
            continue
        for prof in cand.glob("*_settings.json"):
            try:
                dsn = (json.loads(prof.read_text(encoding="utf-8")) or {}).get("dsn") or {}
            except Exception:                                        # noqa: BLE001
                continue
            pw = str(dsn.get("password") or "")
            if pw.startswith("${") and pw.endswith("}"):
                return pw[2:-1]
    return None


def step_env(key: str, *, apply: bool, base: str = "") -> bool:
    print("\n[4] .env — the variable the profile's dsn will reference")
    shared = _family_password_var(base or key) if base else None
    if shared:
        _ok(f"reuses {shared} — an existing build of {base} already declares it")
        return True
    var = _env_var_for(key)
    text = ENV.read_text(encoding="utf-8") if ENV.is_file() else ""
    if re.search(rf"(?m)^{var}=", text):
        _ok(f"{var} already set")
        return True
    if not apply:
        _todo(f"would append `{var}=` (fill it in; the dsn template will reference it)")
        return True
    with ENV.open("a", encoding="utf-8") as fh:
        fh.write(f"\n# {key}: password for the ontology profile's dsn (${var})\n{var}=\n")
    _warn(f"appended `{var}=` — set its value before the builder publishes")
    return True


def step_tools(*, apply: bool) -> bool:
    """The builder's tool rows must exist, or the agent it just created cannot publish.

    Measured on talent_v1 (2026-11-14): the agent row listed `ontology_open / ontology_inspect /
    ontology_publish`, `custom_tools` held none of them, and the agent reported "ontology_publish 不在我的
    工具集里" after doing a whole ladder step it could not land. The four ontology tools live in their own
    seed scripts, not in `SEEDABLE_TOOL_META`, so nothing here ever created them — a sixth artefact that
    has to agree and had no step of its own.
    """
    print("\n[5] the ontology tool rows (agent cannot publish without them)")
    import importlib.util

    here = pathlib.Path(__file__).resolve().parent
    wanted = ("seed_ontology_open_tool", "seed_ontology_inspect_tool",
              "seed_ontology_publish_tool", "seed_ontology_ask_tool")
    missing = []
    if not apply:
        from db.database import SessionLocal                        # noqa: PLC0415
        from models.custom_tool import CustomTool                   # noqa: PLC0415

        db = SessionLocal()
        try:
            for name in wanted:
                tool_id = name.replace("seed_", "").replace("_tool", "")
                if db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first() is None:
                    missing.append(tool_id)
        finally:
            db.close()
        if missing:
            _todo(f"would seed tool rows: {missing}")
        else:
            _ok("all four ontology tool rows exist")
        return True

    for name in wanted:
        path = here / f"{name}.py"
        spec = importlib.util.spec_from_file_location(f"_seed_{name}", path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        module.main() if hasattr(module, "main") else module.seed()
    _ok("ontology tool rows seeded (open / inspect / publish / ask)")
    return True


def step_profile_dir(key: str, *, apply: bool) -> bool:
    print("\n[6] profile directory")
    path = PROFILES / key
    if path.is_dir() and any(path.iterdir()):
        _warn(f"{path} already has content — the builder will update it, not start from scratch")
        return True
    _ok(f"{path} does not exist yet (the builder creates it)")
    return True


def _preview_version(key: str, *, base: str, kind: str, theme: str, datasource: str) -> dict:
    """What the Settings row will say about the version — computed without writing the registry."""
    try:
        reg = V.load(PROFILES / V.REGISTRY_NAME)
        entry = V.record(reg, key=key, kind=kind, theme=theme, datasource=datasource)
    except V.VersionError as exc:
        _warn(f"version facts unavailable: {exc}")
        return {}
    return {"version": entry["version"], "kind": kind, "latest": True, "superseded_by": ""}


def _previous_build(key: str) -> str | None:
    """The build this key replaced, if any (read from the registry, never guessed)."""
    try:
        reg = V.load(PROFILES / V.REGISTRY_NAME)
    except V.VersionError:
        return None
    base = V.parse_key(key)[0]
    fam = (reg.get("families") or {}).get(base) or {}
    latest = fam.get("latest")
    if latest and latest != key:
        return str(latest)                       # the build this one supersedes (dry run too)
    for v in fam.get("versions") or []:
        if str(v.get("superseded_by")) == key and str(v.get("key")) != key:
            return str(v["key"])
    return None


def step_versions(key: str, *, base: str, kind: str, theme: str, datasource: str,
                  apply: bool) -> tuple[bool, dict]:
    """Record the build in `profiles/_versions.json` and return the fields for the Settings row."""
    print("\n[7] version registry (profiles/_versions.json)")
    try:
        reg = V.load(PROFILES / V.REGISTRY_NAME)
    except V.VersionError as exc:
        _warn(f"registry unreadable: {exc}")
        return False, {}
    before = V.latest_of(base, registry=reg) or ""
    try:
        entry = V.record(reg, key=key, kind=kind, theme=theme, datasource=datasource)
    except V.VersionError as exc:
        _warn(str(exc))
        return False, {}
    meta = {"version": entry["version"], "kind": kind, "latest": True, "superseded_by": ""}
    if not apply:
        _todo(f"would record {key} as {base} v{entry['version']} (kind={kind})"
              + (f"; latest {before} → {key}" if before and before != key else ""))
        return True, meta
    try:
        path = V.save(reg)
    except OSError as exc:
        _warn(f"could not write the registry: {exc}")
        return False, meta
    _ok(f"recorded {key} as {base} v{entry['version']} (kind={kind}) — "
        f"{path.relative_to(REPO)}")
    if before and before != key:
        _ok(f"latest moved {before} → {key}; {before} now carries superseded_by={key}")
    else:
        _ok(f"latest is {key} (first build of {base})")
    return True, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="",
                    help="the customer's NAME, e.g. `sunhing` — the script assigns sunhing_v<N>")
    ap.add_argument("--key", default="",
                    help="an exact key for a name that carries no version (abc, tpch, logistics)")
    ap.add_argument("--kind", default="customer", choices=sorted(V.KINDS),
                    help="why this key exists: customer | demo | trial | tutorial "
                         "(nothing deletes a customer or tutorial key)")
    ap.add_argument("--no-agent", action="store_true",
                    help="register gates/Settings/registry only — for handing the key to the single "
                         "builder template instead of minting a per-key agent row")
    ap.add_argument("--datasource", required=True, help="database name the builder reads")
    ap.add_argument("--theme", default="", help="human label for Settings → Ontology")
    ap.add_argument("--family", action="append", default=[], choices=["abox"],
                    help="extra gate families this profile needs (abox → check_abox + check_abox_sync)")
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--skip-db-probe", action="store_true")
    ap.add_argument("--require-db", action="store_true",
                    help="treat an unreachable dataset as a problem (default: warn only, since a "
                         "dev laptop may use a different role than the deployment)")
    args = ap.parse_args()

    ds = args.datasource.strip()
    base = args.base.strip().lower()
    key = args.key.strip().lower()
    if bool(base) == bool(key):
        print("[FATAL] pass exactly one of --base (the customer's name, a version is assigned) "
              "or --key (an exact, unversioned key)", file=sys.stderr)
        return 2
    try:
        if base:
            known = V.existing_keys(PROFILES, gate_keys=_gate_keys())
            key, version = V.key_for(base, known=known)
        else:
            base, version = V.parse_key(key)
    except V.VersionError as exc:
        print(f"[FATAL] {exc}", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
        print(f"[FATAL] key {key!r} must be lowercase letters/digits/underscore", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9_]+", ds):
        print(f"[FATAL] datasource {ds!r} is not a database name", file=sys.stderr)
        return 2

    print(f"ontology builder: {base} v{version} → key={key}  datasource={ds}  kind={args.kind}  "
          f"theme={args.theme or '(none)'}  mode={'APPLY' if args.apply else 'DRY RUN'}")

    problems = 0
    if not args.skip_db_probe:
        print("\n[0] the dataset")
        ok, why = _db_exists(ds)
        if ok:
            _ok(f"database {ds!r} answers on this host")
        else:
            _warn(f"database {ds!r} does not answer here: {why}")
            if args.require_db:
                problems += 1
            else:
                print("       (advisory: pass --require-db to make this fatal)")

    # The version facts are computed FIRST (in memory, nothing written) so the Settings row carries
    # the same numbers the registry will record; the registry itself is written LAST, so its output is
    # the last thing a human reads before the summary.
    meta = _preview_version(key, base=base, kind=args.kind, theme=args.theme, datasource=ds)
    for fn in (lambda: True if args.no_agent else step_agent(key, ds, args.theme, apply=args.apply),
               lambda: True if args.no_agent else
               step_agent_note(key, base=base, version=version, kind=args.kind),
               lambda: step_gates(key, apply=args.apply, family_extra=set(args.family or [])),
               lambda: step_settings(key, args.theme, apply=args.apply, meta=meta),
               lambda: step_env(key, apply=args.apply, base=base),
               lambda: step_tools(apply=args.apply),
               lambda: step_profile_dir(key, apply=args.apply),
               lambda: step_versions(key, base=base, kind=args.kind, theme=args.theme,
                                     datasource=ds, apply=args.apply)[0]):
        try:
            if not fn():
                problems += 1
        except Exception as exc:                                # noqa: BLE001
            print(f"  FAIL {type(exc).__name__}: {exc}")
            problems += 1

    print("\n=== summary ===")
    if problems:
        print(f"  {problems} problem(s) — fix them before building; the dry run lists plain plans, "
              f"warnings are real.")
        return 1
    print("  ready." + ("" if args.apply else "  Re-run with --apply to write these changes."))
    if args.no_agent:
        print(f"  next: hand {key} to the single 'Ontology Builder' template (no per-key agent row "
              f"was created); it reads {ds} read-only, writes profiles/{key}/, then publishes "
              f"through the channel (staged → gates → human apply).")
    else:
        print(f"  next: chat with 'Ontology Builder ({key})' — it reads {ds} read-only, writes "
              f"profiles/{key}/, then publishes through the channel (staged → gates → human apply).")
    prev = _previous_build(key)
    if prev:
        print(f"  version: {base} v{version} → {key} is the family's latest; {prev} keeps "
              f"superseded_by={key} so the old build is still readable and gateable.")
    else:
        print(f"  version: {base} v{version} → {key} is the family's first build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""actions.py — the VERB layer: declared, validated, audited writes for the retail ontology.

A read is compiled from the TTL by graph_view.py. A WRITE is never a free SQL statement:
every write is an ACTION TYPE declared in `schema/actions.yml`, and this engine compiles it
against the same TTL the read lane uses:

    property -> :physicalColumn      (the ontology owns the column name)
    object   -> :physicalTable / :primaryKey
    guard    -> `:state "action"`    (an action may only write action-owned properties)

One action run = one transaction:

    1. SELECT ... FOR UPDATE        (the object row, locked; also the "before" snapshot)
    2. preconditions                (exists / class / state / params — compiled from the declaration;
                                     `class` derives the predicate from the class's equivalentClass
                                     axiom, so the reasoner's definition gates the write)
    3. effect                       (UPDATE ... RETURNING, or INSERT ... RETURNING)
    4. audit_events INSERT          (append-only: action, actor, params, before, after, SQL)

A refused precondition is a RESULT (exit 2, no write, no audit row), same rule as the read
lane's Refusal. `check_actions.py` proves each of these promises can fail.

Usage (cube-tutorial venv python: psycopg2 + rdflib + pyyaml):
    actions.py list
    actions.py compile [--action NAME]
    actions.py run --action PromoteCustomer --params '{"customer_id": 2}' --actor demo
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys

import psycopg2
import json
import os

import yaml
from rdflib import RDF, OWL

BASE = pathlib.Path(__file__).resolve().parent
# Where the action DECLARATIONS live. `APP_ACTIONS` wins; otherwise the PROFILE's `actions_file`; only
# then retail's own file. Reading it from the profile matters because `APP_ACTIONS` is set by whoever
# spawns a child (serve_ui does), so any process that was merely pointed at a profile — the samples
# gate, nl.py building its menu — compiled RETAIL's verbs against another ontology's graph and refused
# the whole declaration set: every sample became "cannot compile action declarations".
# The fallback is resolved at CALL time by `actions_path()` (APP_ACTIONS → the profile's
# `actions_file` → retail's own file). This constant is only a last resort for code that reads
# it directly, so it points at the RETAIL PROFILE's declaration rather than at a directory that
# happens to sit next to this module.
SCHEMA = pathlib.Path(os.environ.get("APP_ACTIONS")
                       or (BASE.parent / "profiles" / "retail" / "schema" / "actions.yml"))
sys.path.insert(0, str(BASE))
import sqlgen  # noqa: E402

P = sqlgen.P
SETTINGS = pathlib.Path(os.environ.get("APP_SETTINGS") or (BASE / "settings.json"))


def _settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def dsn() -> dict:
    """The DSN of the ACTIVE profile, read at call time.

    This used to be a module constant captured at import — the one binding that made "one process,
    two ontologies" impossible: `actions.py` would connect to whichever database happened to be
    active the first time it was imported.
    """
    import dsn as _dsn

    return _dsn.resolved({"dsn": _settings().get("dsn") or {
        "host": "127.0.0.1", "port": 15432, "dbname": "retail_db",
        "user": "postgres", "password": "postgres"}})


# kept for callers that read the name directly (the CLI, the gates); `connect()` uses dsn()
DSN = dsn()
AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS audit_events (
    id         bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    action     text NOT NULL,
    actor      text,
    params     jsonb,
    before_row jsonb,
    after_row  jsonb,
    statements jsonb
);
"""

IDENT = re.compile(r"[a-z_][a-z0-9_]*")
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class Refusal(Exception):
    """A result, not an error: the action declined, nothing was written."""


#: Set by `profile.use()` when this process is pointed at a profile explicitly (the app's in-process
#: path). It WINS over the environment, because the environment is process-wide and outlives a request.
ACTIVE_PROFILE: pathlib.Path | None = None


def actions_path() -> pathlib.Path | None:
    """The declaration file for the ontology this process is pointed at — read at CALL time.

    `SETTINGS` (and therefore `_settings()`) is a PATH bound at import, so a caller that sets
    `APP_SETTINGS` after importing `actions` — a gate that switches profile mid-run, which
    `check_ontology_generic` rightly does — would still be told retail's declarations. Resolving the
    profile from the live environment at call time is the only version that cannot go stale.
    """
    if ACTIVE_PROFILE is not None:
        profile = ACTIVE_PROFILE
        settings: dict = {}
        try:
            settings = json.loads(profile.read_text(encoding="utf-8"))
        except Exception:                                      # noqa: BLE001
            settings = {}
        raw = (settings.get("actions_file") or "").strip()
        if raw:
            p = pathlib.Path(raw).expanduser()
            return p if p.is_absolute() else (profile.parent / p).resolve()
        conventional = profile.parent / "schema" / "actions.yml"
        if conventional.is_file():
            return conventional.resolve()
        # A profile that declares no write verbs HAS no actions file. Returning retail's here is how
        # PromoteCustomer ended up being compiled against clinic's graph and surfaced as a 500 —
        # "this ontology has no writes" is a fact, not a fallback.
        return None
    if os.environ.get("APP_ACTIONS"):
        return pathlib.Path(os.environ["APP_ACTIONS"])
    live = os.environ.get("APP_SETTINGS") or ""
    profile = pathlib.Path(live).expanduser() if live else SETTINGS
    settings: dict = {}
    try:
        settings = json.loads(pathlib.Path(profile).read_text(encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        settings = {}
    raw = (settings.get("actions_file") or "").strip()
    if raw:
        p = pathlib.Path(raw).expanduser()
        return p if p.is_absolute() else (BASE / p).resolve()
    return SCHEMA


def load_config(path: pathlib.Path | None = None) -> dict:
    """The verb declarations. An ontology with no verbs declares an EMPTY set, not an error."""
    if path is None:
        path = actions_path()       # default bound HERE, not at definition time
    if path is None:
        return {"namespace": None, "actions": []}
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_graph():
    """Load the ontology this process was pointed at (APP_SETTINGS), not a hard-coded folder.

    This used to force `BASE/ontology` (retail), which quietly gave the TPCH profile the
    retail graph — the same class names with the wrong tables. sqlgen already knows its
    profile, so ask it instead of re-deciding here.
    """
    return sqlgen.load()


# ------------------------------------------------------------------ compilation
def class_table(graph, cls: str) -> tuple[str, list[str]]:
    node = P(cls)
    table = sqlgen._one(graph, node, P("physicalTable"))
    if not table:
        raise Refusal(f":{cls} has no :physicalTable — a write needs a table")
    pk = sqlgen._one(graph, node, P("primaryKey"))
    keys = [c.strip() for c in (pk or "").split(",") if c.strip()]
    return table, keys


def effect_property(graph, prop: str) -> str:
    """The column an effect writes. A FOREIGN KEY counts: writing `dispatch_decisions.trip_id` is
    writing a column, and the ontology declares that column as an `owl:ObjectProperty`.

    Refusing ObjectProperty targets made a decision log undeclarable without re-declaring the FK as a
    DatatypeProperty — which the structure file forbids (a FK column appears exactly once, on the
    ObjectProperty, so the read join graph and the write effect read the SAME declaration). The
    `:state "action"` check below is unchanged: it is still the only thing that lets a write in.
    """
    node = P(prop)
    if (node, RDF.type, OWL.DatatypeProperty) not in graph and \
            (node, RDF.type, OWL.ObjectProperty) not in graph:
        raise Refusal(f":{prop} is neither an owl:DatatypeProperty nor an owl:ObjectProperty — "
                      f"an action effect must name one")
    column = sqlgen._one(graph, node, P("physicalColumn"))
    if not column:
        raise Refusal(f":{prop} has no :physicalColumn — nothing to write")
    if sqlgen._one(graph, node, P("state")) != "action":
        raise Refusal(f":{prop} is not action-owned (:state \"action\" missing) — "
                      f"only an action may write it")
    return column


def _placeholder(name: str, params: set[str], where: str) -> str:
    if name not in params:
        raise Refusal(f"{where}: parameter '{{{name}}}' is not declared in `parameters`")
    return f"%({name})s"


def _value_sql(spec, params: set[str], where: str) -> tuple[str, list[str]]:
    """A literal ('PREMIUM', 5000), or a "{param}" reference."""
    if isinstance(spec, (int, float)):
        return str(spec), []
    m = PLACEHOLDER.fullmatch(str(spec))
    if m:
        return _placeholder(m.group(1), params, where), [m.group(1)]
    return "'" + str(spec).replace("'", "''") + "'", []


def _state_expr(expr: str, columns: set[str], where: str) -> str:
    """A condition over the OBJECT's current row: identifiers must be its columns."""
    def sub(m):
        ident = m.group(0)
        if ident in columns:
            return ident
        raise Refusal(f"{where}: '{ident}' names no column of the object type "
                      f"(columns: {sorted(columns)})")
    return IDENT.sub(sub, expr)


def _params_expr(expr: str, params: set[str], where: str) -> tuple[str, list[str]]:
    """A condition over the REQUEST parameters: every identifier becomes a placeholder."""
    used: list[str] = []

    def sub(m):
        name = m.group(0)
        if name not in params:
            raise Refusal(f"{where}: '{name}' is not a declared parameter")
        used.append(name)
        return f"%({name})s"
    return IDENT.sub(sub, expr), sorted(set(used))


TYPES = {"integer", "number", "string", "boolean"}


def _param_specs(name: str, act: dict) -> dict[str, dict]:
    """Validate the parameter DECLARATION itself, then keep it for run-time checking.

    A metadata field the engine never reads is a lying declaration. `type` and `required`
    are part of the action's interface contract, so the compiler either OBEYS them (types
    are checked at run time, required=false must be meaningful) or REFUSES them by name —
    it never silently ignores them.
    """
    out: dict[str, dict] = {}
    for pname, spec in (act.get("parameters") or {}).items():
        if not isinstance(spec, dict):
            raise Refusal(f"{name}.parameters.{pname}: expected a mapping like "
                          f"{{type: integer, required: true}}")
        ptype = spec.get("type")
        if ptype not in TYPES:
            raise Refusal(f"{name}.parameters.{pname}: type must be one of {sorted(TYPES)} "
                          f"(got {ptype!r}) — an untyped parameter is an unenforced contract")
        required = spec.get("required", True)
        if required is not True:
            raise Refusal(f"{name}.parameters.{pname}: required: {str(required).lower()} is not "
                          f"supported by this engine (it would be ignored); declare required: true")
        out[pname] = {"type": ptype, "required": True}
    return out


def _validate_params(name: str, act: dict, params: dict) -> None:
    """Refuse a value that does not satisfy the declared type. Runs before any SQL."""
    for pname, spec in (act.get("param_specs") or {}).items():
        if pname not in params:
            continue                     # missing parameters are refused separately
        value = params[pname]
        ptype = spec["type"]
        ok = (
            (ptype == "integer" and isinstance(value, int) and not isinstance(value, bool)) or
            (ptype == "number" and isinstance(value, (int, float)) and not isinstance(value, bool)) or
            (ptype == "string" and isinstance(value, str)) or
            (ptype == "boolean" and isinstance(value, bool))
        )
        if not ok:
            raise Refusal(f"{name}: parameter {pname!r} must be {ptype}, "
                          f"got {value!r} ({type(value).__name__}) — nothing was written")


def compile_action(graph, act: dict) -> dict:
    name = act["name"]
    param_specs = _param_specs(name, act)
    params = set(param_specs)
    audit = act.get("audit", "required")
    if audit != "required":
        raise Refusal(f"{name}: audit:{audit!r} — audit is the floor of the verb layer; "
                      f"only 'required' is accepted")
    spec_hash = hashlib.sha256(
        json.dumps(act, sort_keys=True, default=str).encode()).hexdigest()[:16]
    cls = act["applies_to"]
    table, keys = class_table(graph, cls)
    if len(keys) != 1:
        raise Refusal(f"{name}: only single-column primary keys are supported "
                      f"(got {keys or 'none'})")
    pk = keys[0]
    columns = set(sqlgen.class_columns(graph, cls).values()) | {pk}

    key_param = None
    for pre in act.get("preconditions") or []:
        if pre.get("kind") == "exists" and pre.get("object_type") == cls:
            m = PLACEHOLDER.fullmatch(str(pre["key"]))
            if m and m.group(1) in params:
                key_param = m.group(1)
    if key_param is None and pk in params:
        key_param = pk

    checks = []
    for i, pre in enumerate(act.get("preconditions") or []):
        kind = pre.get("kind")
        where = f"{name}.preconditions[{i}]"
        if kind == "exists":
            otable, okeys = class_table(graph, pre["object_type"])
            if len(okeys) != 1:
                raise Refusal(f"{where}: exists needs a single-column key")
            key, used = _value_sql(pre["key"], params, where)
            checks.append({"kind": "exists", "used": used,
                           "template": f"SELECT 1 FROM {otable} WHERE {okeys[0]} = {key}"})
        elif kind == "state":
            if key_param is None:
                raise Refusal(f"{where}: a state precondition needs the object key "
                              f"parameter (add an exists precondition or a parameter named {pk!r})")
            expr = _state_expr(pre["expression"], columns, where)
            checks.append({"kind": "state",
                           "template": f"SELECT 1 FROM {table} WHERE {pk} = %({key_param})s "
                                       f"AND ({expr})"})
        elif kind == "class":
            # A guard DERIVED from the reasoner's definition: the predicate comes from the
            # named class's owl:equivalentClass axiom (sqlgen.concept_sql), so the same
            # axiom that makes lane A/B list a customer as :PremiumCustomer also gates the
            # write. Change the axiom and the guard follows — no YAML edit, no two-copy drift.
            if key_param is None:
                raise Refusal(f"{where}: a class precondition needs the object key "
                              f"parameter (add an exists precondition or a parameter named {pk!r})")
            pred = sqlgen.concept_sql(graph, pre["class"])   # Refusal if no axiom
            inner = f"({pred})" if pre.get("member", False) else f"NOT ({pred})"
            checks.append({"kind": "class", "class": pre["class"],
                           "template": f"SELECT 1 FROM {table} WHERE {pk} = %({key_param})s "
                                       f"AND {inner}"})
        elif kind == "params":
            expr, used = _params_expr(pre["expression"], params, where)
            checks.append({"kind": "params", "used": used, "template": f"SELECT ({expr})"})
        else:
            raise Refusal(f"{where}: unknown precondition kind {kind!r}")

    effect = act.get("effect") or {}
    if "create" in effect:
        c_cls = effect["create"]
        c_table, c_keys = class_table(graph, c_cls)
        if len(c_keys) != 1:
            raise Refusal(f"{name}: create needs a single-column primary key")
        cpk = c_keys[0]
        cols, vals, used = [], [], []
        for prop, spec in (effect.get("values") or {}).items():
            cols.append(effect_property(graph, prop))
            v, u = _value_sql(spec, params, f"{name}.effect.{prop}")
            vals.append(v)
            used += u
        sql = (f"INSERT INTO {c_table} ({cpk}, {', '.join(cols)}) "
               f"SELECT coalesce(max({cpk}), 0) + 1, {', '.join(vals)} FROM {c_table} "
               f"RETURNING *")
        return {"name": name, "applies_to": cls, "object_type": c_cls, "table": c_table,
                "pk": cpk, "kind": "create", "parameters": sorted(params),
                "checks": checks, "effect_sql": sql, "effect_used": sorted(set(used)),
                "key_param": None,
                "permission": act.get("permission"), "audit": act.get("audit", "required")}

    if effect.get("kind") == "class":
        # ONTOLOGY-DRIVEN WRITE: the effect names a CLASS, not a column. The assignment is
        # derived from the same owl:equivalentClass axiom lane A/B compile for reads, so a
        # definition change moves the guard AND the write together (mutation M2).
        if effect.get("member", True) is False:
            raise Refusal(f"{name}: effect kind class with member:false — the axiom pins "
                          f"membership to ONE property value, so the complement has no single "
                          f"assignment; declare an explicit `property: …, value: …` instead")
        prop, column, value_sql = sqlgen.class_assignment(graph, effect["class"])
        used: list[str] = []
    else:
        prop = effect.get("property")
        if not prop:
            raise Refusal(f"{name}: effect must name a :property (edit), :class (membership) "
                          f"or :create (insert)")
        if key_param is None:
            raise Refusal(f"{name}: cannot derive the object key parameter — declare an "
                          f"exists precondition `key: \"{{<param>}}\"` or a parameter named {pk!r}")
        column = effect_property(graph, prop)
        value_sql, used = _value_sql(effect.get("value"), params, f"{name}.effect")
    sql = (f"UPDATE {table} SET {column} = {value_sql} "
           f"WHERE {pk} = %({key_param})s RETURNING *")
    return {"name": name, "applies_to": cls, "object_type": cls, "table": table, "pk": pk,
            "kind": "edit", "property": prop, "column": column, "state": "action",
            "parameters": sorted(params), "checks": checks, "effect_sql": sql,
            "effect_used": sorted(set(used)), "key_param": key_param,
            "param_specs": param_specs, "spec_hash": spec_hash,
            "permission": act.get("permission"), "audit": audit}


def compile_actions(graph, cfg: dict) -> dict[str, dict]:
    out, errors = {}, []
    for act in cfg.get("actions") or []:
        try:
            out[act["name"]] = compile_action(graph, act)
        except (Refusal, sqlgen.Refusal) as exc:
            errors.append(f"{act.get('name')}: {exc}")
    if errors:
        raise Refusal("cannot compile action declarations:\n  " + "\n  ".join(errors))
    return out


# ------------------------------------------------------------------ execution
def connect():
    conn = psycopg2.connect(**dsn())
    cur = conn.cursor()
    cur.execute(AUDIT_DDL)
    conn.commit()
    return conn


def _jsonable(v):
    """A row value that survives json.dumps — used for the audit row, so a miss here is a
    ROLLED-BACK write, not a cosmetic problem.

    `numeric` columns come back as Decimal, which json refuses; the first action writing a
    numeric column (loan_pressure, 2026-11) died on exactly this after the INSERT, and the
    transaction rolled back — correct behaviour, invisible failure. `Decimal` and `time` are
    handled here rather than left to each caller's `default=str`.
    """
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)          # last resort: keep the audit row writable, keep the value readable


def _bound(cur, sql: str, params: dict) -> str:
    """The compiled statement with the parameters bound, for display.

    A dry-run/report that prints `%(customer_id)s` makes the reader translate placeholders by
    hand; the point of the guard is that you can SEE what it checks, so bind the values.
    """
    try:
        return cur.mogrify(sql, params).decode()
    except Exception:  # noqa: BLE001 — display aid only, never let it break a check
        return sql


def run_action(name: str, params: dict, actor: str | None, *, conn=None,
               compiled: dict | None = None) -> dict:
    if compiled is None:
        compiled = compile_actions(load_graph(), load_config())
    if name not in compiled:
        raise Refusal(f"unknown action {name!r} (declared: {sorted(compiled)})")
    act = compiled[name]
    missing = [p for p in act["parameters"] if p not in params]
    if missing:
        raise Refusal(f"{name}: missing parameter(s) {missing}")
    _validate_params(name, act, params)

    own_conn = conn is None
    if own_conn:
        conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(AUDIT_DDL)
        before = None
        if act["kind"] == "edit":
            cur.execute(f"SELECT * FROM {act['table']} WHERE {act['pk']} = "
                        f"%({act['key_param']})s FOR UPDATE", params)
            row = cur.fetchone()
            if row is None:
                raise Refusal(f"{name}: no {act['applies_to']} with {act['pk']}="
                              f"{params.get(act['key_param'])!r} — nothing was written")
            before = dict(zip([d[0] for d in cur.description], row))

        for check in act["checks"]:
            cur.execute(check["template"], params)
            got = cur.fetchone()
            if check["kind"] == "params":
                if not (got and got[0]):
                    raise Refusal(f"{name}: precondition '{_bound(cur, check['template'], params)}'"
                                  f" is false — nothing was written")
            elif got is None:
                raise Refusal(f"{name}: precondition {check['kind']} failed "
                              f"({_bound(cur, check['template'], params)}) — nothing was written")

        cur.execute(act["effect_sql"], params)
        row = cur.fetchone()
        after = dict(zip([d[0] for d in cur.description], row))

        cur.execute(
            "INSERT INTO audit_events(action, actor, params, before_row, after_row, statements) "
            "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb) RETURNING id",
            (name, actor,
             json.dumps({k: _jsonable(v) for k, v in params.items()}),
             json.dumps({k: _jsonable(v) for k, v in (before or {}).items()}),
             json.dumps({k: _jsonable(v) for k, v in after.items()}),
             json.dumps({"preconditions": [c["template"] for c in act["checks"]],
                         "effect": act["effect_sql"],
                         "spec": act.get("spec_hash")})))
        audit_id = cur.fetchone()[0]
        conn.commit()
        return {"ok": True, "action": name, "actor": actor, "audit_id": audit_id,
                "before": {k: _jsonable(v) for k, v in (before or {}).items()},
                "after": {k: _jsonable(v) for k, v in after.items()}}
    except Refusal:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


def check_action(name: str, params: dict, *, compiled: dict | None = None) -> dict:
    """Read-only dry-run of an action's preconditions: WOULD this action be admitted now?

    Runs the SAME compiled checks `run_action` runs, inside a transaction that is always
    rolled back — a dry-run must not write and must not audit. This turns the write guard
    into something you can ASK: PromoteCustomer's guard is compiled from the :PremiumCustomer
    axiom, so "would promote be admitted for customer N?" is a query, not only a write.
    """
    if compiled is None:
        compiled = compile_actions(load_graph(), load_config())
    if name not in compiled:
        raise Refusal(f"unknown action {name!r} (declared: {sorted(compiled)})")
    act = compiled[name]
    missing = [p for p in act["parameters"] if p not in params]
    if missing:
        raise Refusal(f"{name}: missing parameter(s) {missing}")
    _validate_params(name, act, params)

    out = {"ok": True, "action": name, "admitted": None,
           "checks": [], "effect": act["effect_sql"], "effect_bound": act["effect_sql"]}
    conn = psycopg2.connect(**dsn())
    try:
        cur = conn.cursor()
        if act["kind"] == "edit":
            # lock the row so the dry-run answers against the state the write would see
            cur.execute(f"SELECT * FROM {act['table']} WHERE {act['pk']} = "
                        f"%({act['key_param']})s FOR UPDATE", params)
            row = cur.fetchone()
            if row is None:
                out["admitted"] = False
                out["checks"].append({"kind": "exists", "sql": "row lookup", "pass": False,
                                      "detail": f"no {act['applies_to']} with "
                                                f"{act['pk']}={params.get(act['key_param'])!r}"})
                return out
            out["target"] = {k: _jsonable(v)
                             for k, v in zip([d[0] for d in cur.description], row)}
        ok = True
        for check in act["checks"]:
            cur.execute(check["template"], params)
            got = cur.fetchone()
            passed = bool(got and got[0]) if check["kind"] == "params" else got is not None
            ok = ok and passed
            out["checks"].append({"kind": check["kind"], "sql": check["template"],
                                  "sql_bound": _bound(cur, check["template"], params),
                                  "pass": passed})
        out["admitted"] = ok
        out["effect_bound"] = _bound(cur, act["effect_sql"], params)
        return out
    finally:
        conn.rollback()   # a dry-run always rolls back: no write, no audit row
        conn.close()


def recent_audit(limit: int = 50) -> list[dict]:
    conn = psycopg2.connect(**dsn())
    try:
        cur = conn.cursor()
        cur.execute(AUDIT_DDL)
        cur.execute("SELECT id, ts, action, actor, params, before_row, after_row "
                    "FROM audit_events ORDER BY id DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        return [{k: _jsonable(v) for k, v in zip(cols, row)} for row in cur.fetchall()]
    finally:
        conn.close()


def list_actions(compiled: dict | None = None) -> list[dict]:
    if compiled is None:
        compiled = compile_actions(load_graph(), load_config())
    return [{"name": k, "applies_to": v["applies_to"], "kind": v["kind"],
             "parameters": v["parameters"], "spec_hash": v.get("spec_hash"),
             "preconditions": [c["template"] for c in v["checks"]],
             "effect": v["effect_sql"], "audit": v.get("audit")}
            for k, v in compiled.items()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["list", "run", "compile", "audit", "check"])
    ap.add_argument("--action")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--actor", default="cli")
    args = ap.parse_args()
    try:
        compiled = compile_actions(load_graph(), load_config())
        if args.command == "list":
            print(json.dumps(list_actions(compiled), indent=2))
            return 0
        if args.command == "audit":
            print(json.dumps(recent_audit(), indent=2, default=str))
            return 0
        if args.command == "compile":
            if args.action:
                print(json.dumps(compiled[args.action], indent=2, default=str))
            else:
                print(json.dumps(compiled, indent=2, default=str))
            return 0
        if args.command == "check":
            print(json.dumps(check_action(args.action, json.loads(args.params),
                                          compiled=compiled), indent=2, default=str))
            return 0
        print(json.dumps(run_action(args.action, json.loads(args.params), args.actor,
                                    compiled=compiled), indent=2, default=str))
        return 0
    except Refusal as exc:
        print(json.dumps({"ok": False, "refused": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())

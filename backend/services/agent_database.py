"""Where an agent's database is, and what may be said about it.

Two levels, deliberately different jobs:

  * **Settings → Databases** is the CATALOGUE. It is admin-managed, its own ``test`` button opens a real
    connection, and it is the right home for a database several agents share. Its credentials are
    Fernet-encrypted and redacted from every response (``core/settings/secrets.py``).
  * **An agent's own config** may now carry the connection itself (``config.database``,
    ``mode="custom"``). That is the case the catalogue could not serve: an agent pointed at a database
    nobody listed. Same discipline applies — the password is encrypted at rest, stripped from every API
    response, and delivered to a run as ``PGPASSWORD``, never into the prompt.

Resolution order for ONE agent, first hit wins:

    1. ``config.database`` with mode="custom" (its own host/dbname/user/password)
    2. ``config.database`` with mode="catalog" (its ``name``, looked up in the catalogue)
    3. legacy ``config.datasource`` (a catalogue name) — every agent written before this existed

A missing or half-filled block is NOT silently ignored: it names the field, because "the agent used the
other database" is the kind of failure that produces a wrong ontology rather than an error.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

#: Prefix a Fernet token starts with (services/encryption.py). Used to tell "already encrypted" from
#: "plaintext that happens to be in the row" so a save does not double-encrypt.
_FERNET_PREFIX = "gAAAA"

_SECRET_FIELDS = ("password",)


class DatabaseConfigError(ValueError):
    """The agent's database block cannot be used — the message names what is missing."""


def _block(config: Any) -> Optional[Dict[str, Any]]:
    """The agent config's `database` block as a plain dict (a pydantic model also accepted)."""
    if config is None:
        return None
    raw = config.get("database") if isinstance(config, dict) else getattr(config, "database", None)
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        return raw.model_dump()
    return dict(raw) if isinstance(raw, dict) else None


# ── secrets at rest ─────────────────────────────────────────────────────────

def _already_encrypted(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(_FERNET_PREFIX)


def encrypt_config_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt `database.password` before the row is written. Mutates and returns `config`."""
    block = _block(config)
    if not block:
        return config
    # `password_set` is a RESPONSE marker (the editor renders a write-only field from it). It must not
    # be persisted: a stored flag would outlive the password it describes.
    block.pop("password_set", None)
    password = block.get("password")
    if password and not _already_encrypted(password):
        from services.encryption import encryption_service

        block["password"] = encryption_service.encrypt(password)
    config["database"] = block
    return config


def decrypt_config_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt `database.password` for USE (never for a response). Mutates and returns `config`."""
    block = _block(config)
    if not block:
        return config
    password = block.get("password")
    if _already_encrypted(password):
        from services.encryption import encryption_service

        block["password"] = encryption_service.decrypt(password)
        config["database"] = block
    return config


def redact_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """The shape an API may return: the password is never in it.

    A boolean `password_set` travels instead, which is what an editor needs to render a write-only
    field — the same contract `core/settings/secrets.redact` uses for the catalogue.
    """
    if not isinstance(config, dict):
        return config
    block = _block(config)
    if not block:
        return config
    block = dict(block)
    password = block.pop("password", None)
    # Idempotent: redacting an already-redacted block must not flip the marker to False, or a caller
    # that redacts twice (the normaliser is used by list AND detail) claims "no password" for an agent
    # that has one.
    block["password_set"] = bool(password) or bool(block.get("password_set"))
    out = dict(config)
    out["database"] = block
    return out


# ── resolution ─────────────────────────────────────────────────────────────

def _from_block(block: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(env, dsn-without-password) for a custom block, after decrypting its password."""
    host = str(block.get("host") or "").strip()
    dbname = str(block.get("dbname") or "").strip()
    if not host or not dbname:
        raise DatabaseConfigError(
            "config.database (mode='custom') needs host and dbname"
            + ("" if host else "; host is empty")
            + ("" if dbname else "; dbname is empty"))
    env = {"PGHOST": host, "PGDATABASE": dbname}
    port = block.get("port") or 5432
    env["PGPORT"] = str(port)
    user = str(block.get("user") or "").strip()
    if user:
        env["PGUSER"] = user
    password = block.get("password")
    if _already_encrypted(password):
        from services.encryption import encryption_service

        password = encryption_service.decrypt(password)
    if password:
        env["PGPASSWORD"] = str(password)
    if block.get("sslmode"):
        env["PGSSLMODE"] = str(block["sslmode"])
    dsn = {k[2:].lower(): v for k, v in env.items() if k.startswith("PG")}
    dsn.pop("password", None)
    return env, dsn


def resolve(config: Any) -> Tuple[Dict[str, str], Dict[str, str]]:
    """(env, dsn-without-password) for this agent — see the module docstring for the order.

    Raises DatabaseConfigError when the agent says it has a database and the answer is unusable: an
    agent that silently falls back to another database is one whose ontology is built against the
    wrong rows.
    """
    block = _block(config)
    if block:
        mode = str(block.get("mode") or "catalog")
        if mode == "custom":
            return _from_block(block)
        name = str(block.get("name") or "").strip()
        if not name:
            raise DatabaseConfigError("config.database (mode='catalog') needs a `name`")
        from services.deepagent_factory.assembly import _datasource_env

        return _datasource_env(name)

    legacy = (config.get("datasource") if isinstance(config, dict)
              else getattr(config, "datasource", None))
    if legacy:
        from services.deepagent_factory.assembly import _datasource_env

        return _datasource_env(str(legacy))

    return {}, {}


def ontology_env(env: Dict[str, str]) -> Dict[str, str]:
    """The `ONTOLOGY_DB_*` view of a resolved connection.

    An ontology profile declares `"port": "${ONTOLOGY_DB_PORT:-5432}"` and
    `"password": "${ONTOLOGY_DB_PASSWORD}"` — it may not carry either (gate X2). Seeding those names
    from the agent's own connection is what lets a custom agent run the gates against ITS database
    without the profile learning a secret or a machine.
    """
    out: Dict[str, str] = {}
    if env.get("PGHOST"):
        out["ONTOLOGY_DB_HOST"] = env["PGHOST"]
    if env.get("PGPORT"):
        out["ONTOLOGY_DB_PORT"] = env["PGPORT"]
    if env.get("PGUSER"):
        out["ONTOLOGY_DB_USER"] = env["PGUSER"]
    if env.get("PGPASSWORD"):
        out["ONTOLOGY_DB_PASSWORD"] = env["PGPASSWORD"]
    return out


def describe(config: Any) -> str:
    """One line for the prompt: WHERE, never the credential."""
    block = _block(config)
    try:
        env, _dsn = resolve(config)
    except DatabaseConfigError as exc:
        return f"datasource configured but unusable — {exc}"
    if not env:
        return "no database configured for this agent"
    if block and str(block.get("mode")) == "custom":
        who = "this agent's own database config"
    else:
        name = (block or {}).get("name") if block else (config.get("datasource")
                                                       if isinstance(config, dict)
                                                       else getattr(config, "datasource", None))
        who = f"the catalogue entry `{name}`"
    return (f"{who}: host={env.get('PGHOST')} port={env.get('PGPORT')} "
            f"dbname={env.get('PGDATABASE')} user={env.get('PGUSER') or '(default)'} "
            f"credential={'set' if env.get('PGPASSWORD') else 'none'}")


# ── the test a user clicks ────────────────────────────────────────────────

def test_connection(config: Any, *, timeout: int = 5) -> Dict[str, Any]:
    """Open a real connection from this agent's configuration and report what it found.

    A failed test is a RESULT, not a server error: the server's own words ("no password supplied",
    "database does not exist") are what tells a person which field is wrong.
    """
    try:
        env, dsn = resolve(config)
    except DatabaseConfigError as exc:
        return {"ok": False, "detail": str(exc), "target": "unresolved"}
    if not env:
        return {"ok": False, "detail": "no database configured for this agent", "target": "none"}

    import psycopg2

    params = {"host": env.get("PGHOST"), "port": int(env.get("PGPORT") or 5432),
              "dbname": env.get("PGDATABASE")}
    if env.get("PGUSER"):
        params["user"] = env["PGUSER"]
    if env.get("PGPASSWORD"):
        params["password"] = env["PGPASSWORD"]
    if env.get("PGSSLMODE"):
        params["sslmode"] = env["PGSSLMODE"]

    started = time.time()
    try:
        conn = psycopg2.connect(connect_timeout=timeout, **params)
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "detail": str(exc).strip() or type(exc).__name__,
                "target": params["dbname"], "elapsed_ms": int((time.time() - started) * 1000)}
    try:
        with conn.cursor() as cur:
            cur.execute("select current_database(), current_user, version()")
            dbname, role, version = cur.fetchone()
            cur.execute("""select count(*) from information_schema.tables
                           where table_schema = 'public'""")
            tables = cur.fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "database": dbname, "user": role, "tables": tables,
            "server_version": (version or "").split(" on ")[0],
            "host": params["host"], "port": params["port"],
            "elapsed_ms": int((time.time() - started) * 1000),
            "target": params["dbname"]}

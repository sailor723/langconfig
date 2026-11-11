"""Resolve a profile's DSN, with environment substitution.

A profile declares WHICH database an ontology reads (`dsn.host`, `.port`, `.dbname`). In a container
those values are the deployment's, not the author's: `127.0.0.1` inside a container is the container
itself, so the same declaration has to say `$ABC_DB_HOST` on a box where the database is a sibling
service. This module is the ONE place that turns a declared DSN into a connection, so the substitution
rule cannot differ between the app, the gates and the workbench.

Syntax inside any string value:
    `${VAR}`            the variable, or an ERROR when it is unset
    `${VAR:-default}`   the variable, or the stated default when it is unset
    `$VAR`              the variable, or an ERROR
An unset variable with no default is an ERROR, not an empty string — a blank host silently connects to
localhost, which is the failure that looks like "no data". A default is how one declaration works both
on a laptop (`${ONTOLOGY_DB_HOST:-127.0.0.1}`) and on a box where the database is a service.
"""
from __future__ import annotations

import os
import pathlib
import re

_VAR = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|([A-Za-z_][A-Za-z0-9_]*))")


#: The repo's single `.env`, filled into `os.environ` once. The APP gets it from config.py and the
#: gate runner loads it explicitly, but a gate script run by hand (or by a test) did not — so a
#: declaration that legitimately names `${ONTOLOGY_DB_PASSWORD}` failed for "deployment does not set
#: it" while the deployment clearly did. One loader, in the module whose job is to turn a declaration
#: into a connection.
_ENV_LOADED = False


def _load_deployment_env() -> None:
    """Fill os.environ from <repo>/.env, without overriding anything already set."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env = pathlib.Path(__file__).resolve().parents[4] / ".env"
    if not env.is_file():
        return
    try:
        for raw in env.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")
    except Exception:                                          # noqa: BLE001
        pass


class DsnError(Exception):
    """A declared DSN names a variable this deployment does not define."""


def _expand(value):
    if not isinstance(value, str):
        return value

    def sub(match):
        name = match.group(1) or match.group(3)
        default = match.group(2)
        if name in os.environ:
            return os.environ[name]
        if default is not None:
            # `${VAR:-127.0.0.1}`: the profile states a default that works on a laptop, and a
            # deployment overrides it. A declaration that only works in one environment is how
            # "the host is wrong" becomes a mystery.
            return default
        raise DsnError(f"the profile's DSN names ${name}, which this deployment does not set "
                       f"(set it, or give the profile a default: ${{{name}:-…}})")

    return _VAR.sub(sub, value)


def resolved(settings: dict) -> dict:
    """The connection arguments for `psycopg2.connect(**…)`: expanded, with a password key."""
    _load_deployment_env()
    raw = dict((settings or {}).get("dsn") or {})
    out = {k: _expand(v) for k, v in raw.items()}
    out.setdefault("password", "")
    return out

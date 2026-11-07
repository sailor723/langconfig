"""Where the pieces of this feature live — one place, so no script re-derives a path.

The ontology feature is four things:

    compiler/   the compiler: sqlgen (the truth), guard (the rails), actions/capability/nl
                (the verbs and the question pipeline), graph_view (the graph page)
    workbench/  the standalone server that serves a profile on its own (serve_ui.py) plus the
                static pages it serves
    gates/      the checks that hold every declaration honest
    profiles/   the DECLARATIONS: one directory per ontology (TTL, overlay, dashboard.json,
                samples.json, tutorial.json, the workbench profile)

Everything is addressed RELATIVE to this file. A path that depends on where the repository
happens to live (`/Users/weiping/...`) is a bug that only shows up on another machine — which is
exactly what an ECS deployment is.
"""
from __future__ import annotations

import os
import pathlib
import sys

FEATURE = pathlib.Path(__file__).resolve().parent
COMPILER = FEATURE / "compiler"
WORKBENCH = FEATURE / "workbench"
GATES = FEATURE / "gates"
PROFILES = FEATURE / "profiles"


def profile_dir(key: str) -> pathlib.Path:
    """The directory holding one ontology's declarations (and its workbench profile)."""
    return PROFILES / key


def bootstrap_code() -> pathlib.Path:
    """Put the COMPILER on sys.path — its modules import each other by bare name (import sqlgen)."""
    if str(COMPILER) not in sys.path:
        sys.path.insert(0, str(COMPILER))
    return COMPILER


def python() -> str:
    """The interpreter that runs the compiler.

    In production that is THIS process's interpreter (the feature lives inside the app, so it has
    rdflib and psycopg2 already). A separate venv is still supported for the standalone workbench
    and for the gates, via ONTOLOGY_PYTHON — but the default is no longer a path to somebody
    else's machine.
    """
    return os.environ.get("ONTOLOGY_PYTHON") or sys.executable

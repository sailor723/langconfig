"""L2: the shell may not open a database connection; python may still be python.

Why: 2026-11-25, agent 393 used `execute` 264 times in one run — four of them `psql` (list databases, check
`information_schema`, look for `orders_demo_xlsx`). The prompt said "don't query the database from the shell",
the db tools were bound, and it still happened: the shell was a second, unguarded door. Removing `execute`
is not an option (the ontology experts run the repo's compile/gate scripts with it), so the door stays and
only its database half is bolted: `core/tools/db_guard.py` + `WorkspaceShellBackend.execute`.

What is pinned:
  * `psql`, `pg_dump`, `psycopg2`, `sqlalchemy`, `connect(...dbname)`, `COPY … FROM stdin`, `PGPASSWORD=`,
    and a DSN with credentials are refused, as a normal `ExecuteResponse` with a non-zero exit;
  * `python -m features.ontology…` (compile/gates), plain `python -c "print(1+1)"`, `ls`, `echo` still run;
  * the refusal text names the three db tools, so the model can switch in the same turn.
"""
from __future__ import annotations

import pathlib

import pytest

from core.tools.db_guard import find_db_connection, refusal


@pytest.mark.parametrize("command", [
    "psql -lqt",
    'psql -X -A -t -c "select count(*) from orders"',
    "pg_dump -Fc -f /tmp/x.dump db",
    'python -c "import psycopg2; psycopg2.connect(host=\'h\', dbname=\'d\')"',
    'python -c "import sqlalchemy; sqlalchemy.create_engine(\'postgresql://u:p@h/d\')"',
    'PGPASSWORD=secret psql -d postgres -c "select 1"',
    "psql postgresql://user:pw@localhost:5433/db -c 'select 1'",
])
def test_db_connection_commands_are_refused(command):
    assert find_db_connection(command), command
    text = refusal(command)
    assert text and "db_query_agent" in text and "db_query_langgraph" in text and "db_execute" in text


@pytest.mark.parametrize("command", [
    "python -m features.ontology.gates.check_structure --profile p.json",
    "python -m scripts.ontology_gates --key store_monthly --quick",
    'python -c "print(6*7)"',
    "ls -la upload/",
    "echo hello",
    "python3 - <<'EOF'\nx = 1\nprint(x)\nEOF",
])
def test_everything_else_still_runs(command):
    assert find_db_connection(command) is None, command
    assert refusal(command) is None


def test_the_platform_shell_backend_refuses_only_the_database_half(tmp_path):
    from services.workspace_filesystem_backend import WorkspaceShellBackend

    backend = WorkspaceShellBackend(root_dir=str(tmp_path))
    blocked = backend.execute("psql -lqt")
    assert blocked.exit_code != 0
    assert "拒绝执行" in blocked.output and "db_query_agent" in blocked.output

    ok = backend.execute("echo hello-from-shell")
    assert ok.exit_code == 0 and "hello-from-shell" in ok.output

    # `python` may not be on the sandbox PATH in every environment (here it is `python3`); what matters is
    # that a *harmless* python one-liner is NOT refused by the guard.
    import sys
    py = backend.execute(f'{sys.executable} -c "print(6*7)"')
    assert py.exit_code == 0 and "42" in py.output


def test_python_execute_and_bash_refuse_db_connections_but_stay_usable():
    """The two platform execution tools are the OTHER door: python runs in-process, bash runs a shell.

    Measured 2026-11-25: `python_execute` happily ran `import psycopg2; psycopg2.connect(...)` and a
    `subprocess.run(["psql", …])` one-liner, and `bash` ran `psql -lqt` — both while the prompts said not to.
    They now call the same guard the sandbox backend uses; everything that does not connect still works.
    """
    import tools.native_impl as NI

    py = getattr(NI.python_execute, "func", NI.python_execute)
    sh = getattr(NI.bash, "func", NI.bash)

    assert "42" in str(py("print(6*7)"))
    for code in ("import psycopg2; psycopg2.connect(dbname='x')",
                 "import subprocess; subprocess.run(['psql','-lqt'])",
                 "import sqlalchemy; sqlalchemy.create_engine('postgresql://u:p@h/d')"):
        out = str(py(code))
        assert "拒绝执行" in out, out[:120]
        assert "db_query_agent" in out

    assert "hi" in str(sh("echo hi"))
    blocked = str(sh("psql -lqt"))
    assert "拒绝执行" in blocked and "db_query_langgraph" in blocked

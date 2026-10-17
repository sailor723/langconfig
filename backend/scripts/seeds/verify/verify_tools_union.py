"""Prove the tool seed is a UNION, using the exact scenario from the team plan.

    teammate: 5 tools   (t1 t2 t3 shared with me, t4 t5 theirs alone)
    me:       6 tools   (t1 t2 t3 shared, m4 m5 m6 new)
    expect after migration: 5 + 3 = 8, and the 3 shared rows keep THEIR content.

The "me" set is a hand-built merge file so the arithmetic is visible; the real
generated file (67 tools) is applied afterwards to confirm it is well-formed and
idempotent.
"""
import subprocess
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, TOOLS_MERGE  # noqa: E402


from sqlalchemy import text                      # noqa: E402
from db.database import engine, SessionLocal, init_db  # noqa: E402

URL = engine.url.render_as_string(hide_password=False)
assert "langconfig_seedtest" in URL, f"refusing to run outside the scratch DB: {URL}"
REAL_MERGE = TOOLS_MERGE


def psql(sql: str) -> str:
    p = subprocess.run(["psql", URL, "-tA", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"psql failed: {p.stderr.strip()}")
    return p.stdout.strip()


def make_tool(db, tool_id, name, description):
    db.execute(text("""
        INSERT INTO custom_tools (tool_id, name, description, tool_type, implementation_config,
                                  input_schema, is_template_based, is_advanced_mode, is_public,
                                  usage_count, error_count, version, is_builtin, tags, created_at, updated_at)
        VALUES (:t, :n, :d, 'python_function', '{}'::json, '{}'::json, false, false, true,
                0, 0, '1.0.0', false, '[]'::json, now(), now())
    """), {"t": tool_id, "n": name, "d": description})


print("1. schema …")
init_db()
# the arithmetic below ("5 + 3 = 8") assumes this script's own starting state, so
# clear whatever a previous verification left in the scratch DB
psql("TRUNCATE custom_tools RESTART IDENTITY CASCADE")

print("2. teammate's 5 tools …")
db = SessionLocal()
try:
    for t in ("t1", "t2", "t3"):
        make_tool(db, t, f"{t} (theirs)", "TEAMMATE VERSION")
    for t in ("t4", "t5"):
        make_tool(db, t, f"{t} (theirs)", "team only")
    db.commit()
finally:
    db.close()
print("   total:", psql("SELECT count(*) FROM custom_tools"))

print("3. applying a 6-tool merge that represents MY set (3 shared, 3 new) …")
mine = BACKEND / "scenario_tools_merge.sql"
mine.write_text("\n".join(
    ["BEGIN;"] +
    [f"""INSERT INTO custom_tools (tool_id, name, description, tool_type, implementation_config,
            input_schema, is_template_based, is_advanced_mode, is_public, usage_count, error_count,
            version, is_builtin, tags, created_at, updated_at)
SELECT {lit_id}, {lit_name}, 'MY VERSION', 'python_function', '{{}}'::json, '{{}}'::json,
       false, false, true, 0, 0, '1.0.0', false, '[]'::json, now(), now()
WHERE NOT EXISTS (SELECT 1 FROM custom_tools WHERE tool_id = {lit_id});"""
     for lit_id, lit_name in [(f"'{t}'", f"'{t} (mine)'") for t in ("t1", "t2", "t3", "m4", "m5", "m6")]]
    + ["COMMIT;", ""]))
subprocess.run(["psql", URL, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(mine)], check=True)

total = int(psql("SELECT count(*) FROM custom_tools"))
shared = psql("SELECT string_agg(DISTINCT description, ',') FROM custom_tools WHERE tool_id IN ('t1','t2','t3')")
ids = psql("SELECT string_agg(tool_id, ',' ORDER BY tool_id) FROM custom_tools")

print(f"   total now: {total}   ids: {ids}")
print(f"   shared rows' description: {shared}")

print("4. re-applying the same merge (idempotency) …")
subprocess.run(["psql", URL, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(mine)], check=True)
total2 = int(psql("SELECT count(*) FROM custom_tools"))
print(f"   total after a second run: {total2}")

print("5. the real generated seed into a second schema …")
psql("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
init_db()
subprocess.run(["psql", URL, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(REAL_MERGE)], check=True)
real1 = int(psql("SELECT count(*) FROM custom_tools"))
subprocess.run(["psql", URL, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(REAL_MERGE)], check=True)
real2 = int(psql("SELECT count(*) FROM custom_tools"))
print(f"   real seed: {real1} tool(s), {real2} after re-run")

mine.unlink()

print("\n=== verdict ===")
checks = [
    ("teammate's 5 + my 3 new = 8", total == 8),
    ("the 3 shared rows kept THEIR version", shared == "TEAMMATE VERSION"),
    ("my 3 new tools arrived", set(ids.split(",")) == {"t1","t2","t3","t4","t5","m4","m5","m6"}),
    ("no duplicates on re-run", total2 == 8),
    ("real seed applied cleanly and is idempotent", real1 == real2 and real1 > 60),
]
for label, ok in checks:
    print(f"   [{'PASS' if ok else 'FAIL'}] {label}")
print("\n" + ("ALL CHECKS PASSED" if all(o for _, o in checks) else "SOME CHECKS FAILED"))

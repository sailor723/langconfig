"""The verifier must compare column NAMES, and a rerun must not dead-end on "already exists".

Two bugs found by reading a real session of the table-building agent (2026-11-11):

1. `db_verify_against_file` compared *column counts*. A database whose `orders.sold_at` had
   been renamed to `store_id` was still reported PASS — "5 columns vs 5 columns", and the four
   row values happened to line up. That is the one check meant to prove the load, so a false
   PASS is worse than no check: the agent quoted it to the user as 「对账 PASS」.
2. `db_build_from_file` answered "database already exists" with a dead end: the agent could not
   tell its own earlier build (nothing to do) from a stale one (rebuild), and the recreate rule
   only allowed names ending in `_xlsx/_csv/_test` — so `retail_db_export` could never be rebuilt.

The name checks below are source-level (they hold with no server). The live ones run only when
the platform's own server answers; they create and drop a scratch database.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NATIVE = REPO / "backend" / "tools" / "native_impl.py"
SKILL = REPO / "backend" / "skills" / "builtin" / "excel-csv-to-postgres" / "SKILL.md"


@pytest.fixture(scope="module")
def native():
    spec = importlib.util.spec_from_file_location("native_impl_verify_columns", NATIVE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _body(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end)]


# ── the verifier compares names, not positions ──────────────────────────────

def test_verify_has_a_renames_argument(native):
    """A rename made on purpose must be declarable, or the honest verdict is a permanent FAIL."""
    assert "renames" in native.db_verify_against_file.args


def test_verify_matches_columns_by_name():
    text = NATIVE.read_text(encoding="utf-8")
    body = _body(text, "def db_verify_against_file", "def sqlite_load_csv")
    assert "missing_cols" in body and "extra_cols" in body, \
        "the verifier does not compare column names at all"
    assert "len(db_cols) == len(headers)" not in body, \
        "column COUNT comparison is back — a rename passes as PASS again"
    assert "列名不一致" in body, "a name mismatch must be named in the verdict"


def test_verify_reorders_rows_when_names_match_in_another_order():
    """Same columns in another order is not a data difference; the comparison must realign."""
    text = NATIVE.read_text(encoding="utf-8")
    body = _body(text, "def db_verify_against_file", "def sqlite_load_csv")
    assert "reordered" in body and "order = [have.index(w) for w in want]" in body


def test_verify_still_refuses_to_claim_pass_on_name_problems():
    text = NATIVE.read_text(encoding="utf-8")
    body = _body(text, "def db_verify_against_file", "def sqlite_load_csv")
    # missing/extra columns are counted as failures, not as a note under a PASS
    assert 'problems.append("列名不一致' in body
    assert 'verdict = "FAIL" if (not col_ok' in body


def test_verify_normalises_headers_the_way_the_build_did():
    """The load normalises headers (`_column_names`); the check must use the SAME function.

    Measured on client/team-1's meeting export: the client's header is `时长_(分钟)`, the build
    stored `时长_分钟`, and the verifier compared the raw header verbatim — `0/3562 一致的整行`
    on a load that was byte-for-byte correct. The agent then papered over it with
    `renames="...时长_(分钟)=时长_分钟"`, i.e. an honest tool forced an untruthful argument.
    """
    text = NATIVE.read_text(encoding="utf-8")
    assert "def _column_names(" in text, "the one naming rule is gone again"
    body = _body(text, "def db_verify_against_file", "def sqlite_load_csv")
    assert "_column_names(headers" in body, \
        "the verifier has its own idea of the column names again"
    planner = _body(text, "def _plan_from_file", "def _format_plan")
    assert "_column_names(headers" in planner, "the planner has its own idea again"


def test_a_header_the_build_rewrites_still_verifies(native, tmp_path):
    kwargs, _, _ = _live_connection()
    if kwargs is None:
        pytest.skip("no PostgreSQL server configured for this checkout")
    import psycopg2

    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "meeting_hub-clean.csv"
    # the client's real shape: a title pair of lines, then a header with `(`/`)` in a column name
    path.write_text(
        "会议汇总导出,,\n导出时间,2026-11-01,\n"
        "厂区,时长_(分钟),责任人\n"
        "001,45,张三\n"
        "001,30,\n",
        encoding="utf-8",
    )
    target = "zz_verify_header_probe_csv"

    def drop():
        admin = psycopg2.connect(**kwargs)
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "' + target + '" with (force)')
        admin.close()

    drop()
    try:
        built = native.db_build_from_file.func(file=str(path), db_name=target, confirm=True)
        assert "Row counts match the workbook" in built, built[:300]
        verdict = native.db_verify_against_file.func(file=str(path), db_name=target)
        assert "PASS" in verdict, f"a header the build only normalised failed the check:\n{verdict}"
        assert "列名不一致" not in verdict, verdict[:400]
    finally:
        drop()
        path.unlink(missing_ok=True)


# ── a rerun is idempotent, and recreate stays narrow ────────────────────────

def test_build_asks_the_database_whether_it_is_already_in_sync():
    text = NATIVE.read_text(encoding="utf-8")
    assert "_existing_db_matches_file" in text
    body = _body(text, "def db_build_from_file", "def db_review")
    assert "_existing_db_matches_file(" in body, \
        "an existing database is reported without checking whether it is already the file"
    assert "已存在，且与文件完全一致" in body, \
        "the in-sync case must say so plainly instead of erroring"


def test_a_built_database_is_stamped_so_it_can_be_rebuilt():
    text = NATIVE.read_text(encoding="utf-8")
    assert '_BUILD_MARKER_PREFIX = "langconfig:built-from="' in text
    body = _body(text, "def db_build_from_file", "def db_review")
    assert "COMMENT ON DATABASE" in body, "a build leaves no provenance, so recreate can never widen"
    assert "_db_build_marker(" in body, "recreate does not consult the build stamp"


def test_recreate_is_still_refused_for_someone_elses_database():
    text = NATIVE.read_text(encoding="utf-8")
    body = _body(text, "def db_build_from_file", "def db_review")
    assert "refusing recreate" in body
    # the only two ways in: a build stamp, or the documented name suffix
    assert "(xlsx|csv|test)$" in body


def test_the_build_marker_is_read_from_the_catalogue(native):
    """`shobj_description` on pg_database is what makes the stamp survive a restart."""
    text = NATIVE.read_text(encoding="utf-8")
    helper = _body(text, "def _db_build_marker", "def _existing_db_matches_file")
    assert "shobj_description" in helper and "pg_database" in helper


# ── the skill states both rules ────────────────────────────────────────────

def test_the_skill_requires_declaring_a_rename():
    text = SKILL.read_text(encoding="utf-8")
    assert 'renames="orders.sold_at=store_id"' in text
    assert "假的 PASS" in text or "假 PASS" in text, "the skill must name the false-PASS trap"


def test_the_skill_explains_the_already_exists_branches():
    text = SKILL.read_text(encoding="utf-8")
    assert "已存在且表名/列名/行数都和文件一致" in text
    assert "recreate=true" in text
    assert "你这次没建" in text, "the skill must forbid claiming a build it did not do"


def test_the_skill_names_the_dashboard_filename_rule():
    """Auto-open globs `*dashboard*.html`; an agent that believes otherwise misinforms the user."""
    text = SKILL.read_text(encoding="utf-8")
    assert "文件名必须包含 `dashboard`" in text
    assert "*dashboard*.html" in text


# ── live: a renamed column is not a PASS ──────────────────────────────────

def _live_connection():
    """The platform's own server, or None (env from the repo's single .env)."""
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except Exception:                                         # noqa: BLE001
        pass
    import psycopg2
    from importlib import util as _util

    spec = _util.spec_from_file_location("native_impl_live", NATIVE)
    module = _util.module_from_spec(spec)
    spec.loader.exec_module(module)
    kwargs = module._pg_conn_kwargs()
    try:
        psycopg2.connect(**kwargs).close()
    except Exception:                                         # noqa: BLE001
        return None, module, kwargs
    return kwargs, module, kwargs


@pytest.fixture()
def scratch_db(native, tmp_path):
    kwargs, _, _ = _live_connection()
    if kwargs is None:
        pytest.skip("no PostgreSQL server configured for this checkout")
    from openpyxl import Workbook

    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "orders"
    ws.append(["id", "amount", "sold_at"])
    ws.append([1, 500, 1])
    ws.append([2, 250, 2])
    path = root / "verify_columns_probe.xlsx"
    wb.save(path)

    target = "zz_verify_columns_probe_xlsx"
    import psycopg2

    def drop():
        conn = psycopg2.connect(**kwargs)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "' + target + '" with (force)')
        conn.close()

    drop()
    try:
        yield target, path
    finally:
        drop()
        path.unlink(missing_ok=True)


def test_a_renamed_column_fails_the_verification(native, scratch_db):
    target, path = scratch_db
    built = native.db_build_from_file.func(file=str(path), db_name=target, confirm=True)
    assert "Row counts match the workbook" in built, built[:200]

    renamed = native.db_rename_column.func(db_name=target, table="orders",
                                           column="sold_at", new_name="store_id", confirm=True)
    assert "error" not in renamed.lower(), renamed[:200]

    without = native.db_verify_against_file.func(file=str(path), db_name=target)
    assert "API" not in without
    assert "FAIL" in without, f"a renamed column still verified as PASS:\n{without}"
    assert "列名不一致" in without
    assert "sold_at" in without and "store_id" in without

    declared = native.db_verify_against_file.func(
        file=str(path), db_name=target, renames="orders.sold_at=store_id")
    assert "PASS" in declared, f"a declared rename must verify:\n{declared}"


def test_building_twice_is_a_no_op_not_an_error(native, scratch_db):
    target, path = scratch_db
    first = native.db_build_from_file.func(file=str(path), db_name=target, confirm=True)
    assert "Row counts match the workbook" in first

    second = native.db_build_from_file.func(file=str(path), db_name=target, confirm=True)
    assert "已存在，且与文件完全一致" in second, second[:300]
    assert "没有建库" in second or "没有写入" in second

    # and it can still be rebuilt on request, because the first build stamped it
    third = native.db_build_from_file.func(file=str(path), db_name=target, confirm=True,
                                           recreate=True)
    assert "Row counts match the workbook" in third, third[:300]


def test_an_existing_database_that_differs_names_the_difference(native):
    """A hand-made database on a protected name is refused, and the refusal says why."""
    kwargs, module, _ = _live_connection()
    if kwargs is None:
        pytest.skip("no PostgreSQL server configured for this checkout")
    from openpyxl import Workbook

    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "orders"
    ws.append(["id", "amount"])
    ws.append([1, 500])
    path = root / "not_ours_probe.xlsx"
    wb.save(path)

    target = "zz_not_ours_probe"
    import psycopg2

    def drop():
        admin = psycopg2.connect(**kwargs)
        admin.autocommit = True
        with admin.cursor() as cur:
            cur.execute('DROP DATABASE IF EXISTS "' + target + '" with (force)')
        admin.close()

    drop()
    admin = psycopg2.connect(**kwargs)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute('CREATE DATABASE "' + target + '"')
    admin.close()
    try:
        # exists, unstamped, columns differ → says what differs and why it will not rebuild
        result = module.db_build_from_file.func(file=str(path), db_name=target, confirm=True)
        assert result.startswith("Error:"), result[:300]
        assert "和文件对不上" in result
        assert "不能重建" in result

        # and the explicit recreate is refused by the stamp rule, not by the name
        forced = module.db_build_from_file.func(file=str(path), db_name=target, confirm=True,
                                                recreate=True)
        assert forced.startswith("Error:") and "refusing recreate" in forced, forced[:300]
    finally:
        drop()
        path.unlink(missing_ok=True)

"""The Excel/CSV → PostgreSQL tools must refuse to build before a human agrees.

The tools are registered in the platform catalogue, so their *decision* logic is what
gets tested here: the plan phase creates nothing, the plan names the questions only a
user can settle, and the query tool refuses anything that is not a single SELECT.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NATIVE = REPO / "backend" / "tools" / "native_impl.py"
SEED = REPO / "backend" / "scripts" / "seeds" / "in" / "seed_builtin_tools.py"
SKILL = REPO / "backend" / "skills" / "builtin" / "excel-csv-to-postgres" / "SKILL.md"

NEW_TOOLS = ("db_plan_from_file", "db_build_from_file", "db_review", "db_query",
             "db_verify_against_file")


@pytest.fixture(scope="module")
def native():
    if not NATIVE.is_file():
        pytest.skip("native_impl.py not present")
    spec = importlib.util.spec_from_file_location("native_impl_under_test", NATIVE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ── registration ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", NEW_TOOLS)
def test_the_tool_is_both_defined_and_seedable(name, native):
    """Defined in native_impl but absent from the seed table = a tool no agent can select."""
    assert hasattr(native, name), f"{name} is not defined in tools/native_impl.py"
    seed = SEED.read_text(encoding="utf-8")
    assert f'"{name}":' in seed, f"{name} is not in SEEDABLE_TOOL_META, so it never reaches the catalogue"


def test_plan_is_a_separate_read_only_tool(native):
    """The plan and the build are different actions: a guardrail on the build must not fire
    on a review, so the read-only proposal is its own tool with no write path."""
    assert hasattr(native, "db_plan_from_file")
    text = NATIVE.read_text(encoding="utf-8")
    plan = text[text.index("def db_plan_from_file"):text.index("def db_build_from_file")]
    for forbidden in ("CREATE DATABASE", "psycopg2.connect", "INSERT INTO", "DROP DATABASE"):
        assert forbidden not in plan, f"the plan tool must not contain {forbidden!r}"


def test_build_refuses_without_confirm_and_points_at_the_plan(native, tmp_path):
    """`confirm=false` is an error, not a plan dump: the two phases have two entry points."""
    from openpyxl import Workbook

    wb = Workbook(); ws = wb.active; ws.title = "t"
    ws.append(["a", "b"]); ws.append([1, 2])
    path = tmp_path / "x.xlsx"; wb.save(path)
    result = native.db_build_from_file.func(file=str(path), db_name="should_not_exist_xlsx")
    assert result.startswith("Error:") and "confirm=false" in result
    assert "db_plan_from_file" in result, "the refusal must say which tool to call first"


def test_build_takes_a_confirm_flag_and_defaults_to_off(native):
    """The two-phase contract: without `confirm` the tool reports a plan and creates nothing."""
    args = native.db_build_from_file.args
    assert "confirm" in args, "db_build_from_file lost its confirmation flag"
    assert args["confirm"].get("default") is False or args["confirm"].get("default") is None, \
        "the build must not be the default action"


# ── the plan is a plan ──────────────────────────────────────────────────────

def test_the_plan_names_what_only_a_human_can_settle(tmp_path):
    """A missing header, a duplicate header and a half-empty column are the questions that
    produce a wrong schema, so they must be surfaced before anything is created."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "sales"
    ws.append(["region", "region", ""])          # duplicate + missing header
    ws.append(["North", 100, None])
    ws.append(["South", 200, None])
    path = tmp_path / "messy.xlsx"
    wb.save(path)

    plan = _plan_or_skip(path)
    assert "重复" in plan, "a duplicate header was not reported"
    assert "没有表头" in plan, "a missing header was not reported"
    assert "confirm=true" in plan, "the plan must say how to proceed"


def test_the_plan_does_not_create_a_database():
    """The first call is read-only by construction — it returns text, not DDL."""
    text = NATIVE.read_text(encoding="utf-8")
    start = text.index("def db_build_from_file")
    end = text.index("def db_review")
    body = text[start:end]
    guard = body.index("if not confirm:")
    create = body.index('CREATE DATABASE')
    assert guard < create, "the confirm check must come before any CREATE DATABASE"


# ── the query tool is read-only ─────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "DELETE FROM customers",
    "UPDATE customers SET tier = 'X'",
    "DROP TABLE customers",
    "select 1; drop table customers",
])
def test_the_query_tool_refuses_anything_but_one_select(sql, native):
    result = native.db_query.func(db_name="whatever", sql=sql)
    assert result.startswith("Error:"), f"{sql!r} was not refused: {result[:80]}"


# ── the skill states the gate ───────────────────────────────────────────────

def test_the_skill_requires_confirmation_before_building():
    text = SKILL.read_text(encoding="utf-8")
    assert "confirm=true" in text, "the skill must tell the agent how to proceed after confirmation"
    assert "不许自动过" in text or "用户确认" in text
    assert "先建了不好再删" in text, "the skill must name the shortcut it forbids"
    for tool in NEW_TOOLS:
        assert tool in text, f"the skill does not mention {tool}"


def _plan_or_skip(path):
    """Run only the planning half of the tool (no database is contacted)."""
    spec = importlib.util.spec_from_file_location("native_impl_plan", NATIVE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    sheets = {}
    for name in wb.sheetnames:
        data = list(wb[name].iter_rows(values_only=True))
        headers = ["" if c is None else str(c) for c in data[0]]
        body = [list(r) for r in data[1:] if any(c is not None and str(c).strip() != "" for c in r)]
        sheets[name] = (headers, body)
    wb.close()
    tables, warnings = module._plan_from_file(path, sheets)
    return module._format_plan(path, "messy_xlsx", tables, warnings)


# ── the verifier compares values, not formatting ────────────────────────────

def test_canonical_form_ignores_how_a_number_was_written():
    """The sheet says 120, Postgres says Decimal('120.000') — that is not a difference."""
    from decimal import Decimal

    canon = _native()._canon
    assert canon(120) == canon(Decimal("120.000")) == "120"
    assert canon(Decimal("99.5")) == "99.5"
    assert canon(True) == "t" and canon(False) == "f"
    assert canon(None) == "∅"
    assert canon({"b": 1, "a": 2}) == canon({"a": 2, "b": 1}), "jsonb key order must not matter"


def test_120_and_180_are_still_different():
    canon = _native()._canon
    assert canon(120) != canon(180)


def test_verifier_and_builder_share_one_file_reader():
    """A verifier with its own parser would confirm its own parsing bug."""
    text = NATIVE.read_text(encoding="utf-8")
    builder = text[text.index("def db_build_from_file"):text.index("def db_review")]
    verifier = text[text.index("def db_verify_against_file"):]
    assert "_read_source_sheets(path)" in builder
    assert "_read_source_sheets(path)" in verifier


def test_the_skill_forbids_reporting_numbers_before_a_pass():
    text = SKILL.read_text(encoding="utf-8")
    assert "db_verify_against_file" in text
    assert "PASS" in text and "PARTIAL" in text and "FAIL" in text
    assert "不是 PASS 的情况下报数" in text


def _native():
    spec = importlib.util.spec_from_file_location("native_impl_for_canon", NATIVE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

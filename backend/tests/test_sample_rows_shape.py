"""The sample gate must understand every row shape the compiler produces.

`compiler/nl.py::_exec_metric` has three: a scalar `value`, a one-key `{"key", "value"}`, and — as
soon as the GROUP BY has more than one key — `{"keys": [...], "value": …}`. The gate knew the first
two.

Measured on `eff_ops_v1` (2026-11-14): 17 department names produce 18 groups because 「加色部」 exists
in both DG and HY, so its metrics group by (factory, dept) and every answer arrived in the `keys`
shape. `check_samples` then found no key at all and printed "rows comparison: got {}" for 15
declarations that were correct (the same 15 pass with this reader fixed: 34 PASS / 0 FAIL).

A gate that does not understand an answer reports it as a wrong answer — which is the one thing a
gate must never do.
"""
import importlib.util
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "features" / "ontology" / "gates" / "check_samples.py"


def _rows_of():
    spec = importlib.util.spec_from_file_location("check_samples_rows", GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["check_samples_rows"] = module
    spec.loader.exec_module(module)
    return module._rows_of


def test_a_multi_key_answer_is_read():
    rows_of = _rows_of()
    out = rows_of({"rows": [{"keys": ["DG", "金架九部"], "value": 5771679.0},
                            {"keys": ["HY", "加色部"], "value": 202.8}]})
    assert out == {"DG / 金架九部": "5771679.0", "HY / 加色部": "202.8"}, out


def test_the_one_key_shape_still_works():
    rows_of = _rows_of()
    assert rows_of({"rows": [{"key": "core", "value": 5496}]}) == {"core": "5496"}


def test_the_two_key_dict_shape_still_works():
    rows_of = _rows_of()
    assert rows_of({"rows": [{"key": "DG", "key2": "配件部", "value": 1.5}]}) == {"DG / 配件部": "1.5"}


def test_a_plain_list_row_still_works():
    rows_of = _rows_of()
    assert rows_of({"rows": [["DG", "配件部", 12]]}) == {"DG / 配件部": "12"}


def test_nulls_stay_empty_rather_than_becoming_the_string_none():
    rows_of = _rows_of()
    assert rows_of({"rows": [{"keys": ["DG", None], "value": None}]}) == {"DG / ": ""}

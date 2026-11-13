"""A join can carry a declared condition — not only column equality.

Measured on `eff_ops_v1` (team-3's 產出標工計算): the standard-hours row is keyed `(part_no, side)`,
and which side a production row needs is decided by its work-centre description:

    side = CASE WHEN work_center_desc = 'SH分公司前工序' THEN 'front' ELSE 'back' END

Declared as a plain equality the compiler could not express it at all: joining on
`part_no AND work_center_desc` misses every packaging row whose standard hours sit under the other
packaging centre (−29.4% of total i, 5,771.679 → 4,008.120), and joining on `part_no` alone adds both
sides together (×2.006). The agent's report on that build therefore had to refuse `i` entirely
("缺「带条件的连接」声明") — an honest refusal caused by a compiler gap, not by the data.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
from rdflib import Graph, Literal
from rdflib.namespace import OWL, RDF, RDFS

REPO = Path(__file__).resolve().parents[2]
SQLGEN = REPO / "backend" / "features" / "ontology" / "compiler" / "sqlgen.py"
NS = "https://cube.local/ontology/join_extra#"


def P(local):
    from rdflib import URIRef
    return URIRef(NS + local)


def _sqlgen():
    spec = importlib.util.spec_from_file_location("sqlgen_join_extra", SQLGEN)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["sqlgen_join_extra"] = module
    spec.loader.exec_module(module)
    return module


def _graph(extra: str | None) -> Graph:
    g = Graph()
    g.bind("", NS)
    row = P("ProductionRow")
    std = P("StdTime")
    for cls, table, pk, tcol in ((row, "production_row", "id", "src_row"),
                                 (std, "std_time", "id", "month")):
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, P("physicalTable"), Literal(table)))
        g.add((cls, P("primaryKey"), Literal(pk)))
        g.add((cls, P("timeColumn"), Literal(tcol)))
    for cls, prop, col in ((row, "rowQty", "qty_report"), (row, "rowWorkCenter", "work_center_desc"),
                           (row, "rowPartNo", "part_no"), (std, "stdSeconds", "seconds"),
                           (std, "stdPartNo", "part_no"), (std, "stdSide", "side")):
        node = P(prop)
        g.add((node, RDF.type, OWL.DatatypeProperty))
        g.add((node, RDFS.domain, cls))
        g.add((node, P("physicalColumn"), Literal(col)))
    link = P("rowStdTime")
    g.add((link, RDF.type, OWL.ObjectProperty))
    g.add((link, RDFS.domain, row))
    g.add((link, RDFS.range, std))
    g.add((link, P("physicalColumn"), Literal("part_no")))
    g.add((link, P("references"), std))       # _closure 要求存在 :references（否则整条边被跳过）
    g.add((link, P("referencesKey"), Literal("part_no")))
    if extra is not None:
        g.add((link, P("joinExtra"), Literal(extra)))
    metric = P("stdHours")
    g.add((metric, RDF.type, OWL.DatatypeProperty))
    g.add((metric, P("aggregate"), Literal("sum")))
    g.add((metric, P("grain"), row))
    g.add((metric, P("universe"), row))          # 分母必须声明（编译器会拒绝缺 universe 的指标）
    g.add((metric, P("formula"), Literal("seconds * qty_report / 3600.0")))
    return g


CASE_EXTRA = ("{r}.side = CASE WHEN {d}.work_center_desc = 'SH分公司前工序' "
              "THEN 'front' ELSE 'back' END")


def _compile(g, module, name="stdHours") -> str:
    module.reconfigure(ns=NS)
    return module.compile_metric(g, name).sql
    assert "JOIN std_time ON" in sql
    assert "std_time.side = CASE WHEN production_row.work_center_desc" in sql, sql
    assert "production_row.part_no = std_time.part_no" in sql, sql


def test_without_join_extra_the_join_is_still_a_plain_equality():
    """The default must not change: every existing ontology declares equality joins only."""
    module = _sqlgen()
    sql = _compile(_graph(None), module)
    assert "production_row.part_no = std_time.part_no" in sql
    assert "CASE" not in sql.upper()


def test_a_join_extra_naming_an_unknown_column_is_refused_by_name():
    module = _sqlgen()
    g = _graph("{r}.wrong_side = 'front'")
    with pytest.raises(Exception) as exc:
        _compile(g, module)
    assert "wrong_side" in str(exc.value), exc.value


def test_an_unknown_placeholder_is_refused():
    module = _sqlgen()
    g = _graph("{x}.side = 'front'")
    with pytest.raises(Exception) as exc:
        _compile(g, module)
    assert "{x}" in str(exc.value) or "placeholder" in str(exc.value)

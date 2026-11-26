"""A Chinese question that names nothing declared must not be answered by the nearest metric.

Measured on tpch_sales_v1 (2026-11-26): 问「毛利率是多少」 resolved to :grossRevenue and answered
21,615,929,280.24 — on the rules path AND on the model path — while the ontology had written 毛利率
into its refusal list. The reason was structural: `_rule_intent`'s noun-coverage test drops every
CJK token on purpose (Chinese has no word boundaries), so a Chinese question had no coverage test
at all, and `:askedAs` — the declared menu aliases, which C5a forces every metric to carry — never
reached the matcher.

These tests pin the fix:

* the menu carries each metric's `:askedAs`, so both the rule matcher and the model prompt see the
  declared aliases;
* a Chinese question whose answer was NOT declared is `None` (unsure → the model gets one chance,
  and without one it becomes the refusal-by-name path), not the nearest metric;
* a Chinese question that DOES name a declared alias still resolves.

No database is needed: the graph is a throwaway TTL.
"""
from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
COMPILER = BACKEND / "features" / "ontology" / "compiler"
sys.path.insert(0, str(COMPILER))

import rdflib  # noqa: E402
import nl  # noqa: E402
import sqlgen  # noqa: E402

TTL = """@prefix : <http://probe.local/onto#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:OrderRow a owl:Class ;
    :physicalTable "orders" ;
    :primaryKey "id" .

:netRevenue a owl:DatatypeProperty ;
    rdfs:label "净收入" ;
    :aggregate "sum" ;
    :grain :OrderRow ;
    :universe :OrderRow ;
    :formula "amount * (1 - discount)" ;
    :unit "money" ;
    :askedAs "净收入是多少" ;
    :askedAs "净收入" .

:grossRevenue a owl:DatatypeProperty ;
    rdfs:label "毛收入" ;
    :aggregate "sum" ;
    :grain :OrderRow ;
    :universe :OrderRow ;
    :formula "amount" ;
    :unit "money" ;
    :askedAs "毛收入（未折扣未税）是多少" .
"""


def _menu():
    # sqlgen.metrics() only speaks about the CONFIGURED namespace, so the fixture's prefix has to
    # be the one the generator was told about (otherwise the menu is empty and every assertion
    # passes vacuously).
    sqlgen.reconfigure(ns="http://probe.local/onto#")
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return nl.menu(g)


def test_menu_carries_the_declared_aliases():
    menu = _menu()
    gross = next(m for m in menu["metrics"] if m["name"] == "grossRevenue")
    assert gross["asked_as"] == ["毛收入（未折扣未税）是多少"]


def test_undeclared_chinese_question_is_unsure_not_nearest_metric():
    # 毛利率 is not a declared surface of either metric: answering grossRevenue would be a wrong
    # number presented confidently, which is the failure this test exists for.
    assert nl._rule_intent("毛利率是多少", _menu()) is None


def test_declared_chinese_question_still_resolves():
    got = nl._rule_intent("净收入是多少", _menu())
    assert got == {"kind": "metric", "name": "netRevenue"}


def test_rule_matcher_reads_asked_as():
    # The matcher used to compare only the internal name and the label; an alias that the model
    # prompt would have seen must also resolve on the rules path.
    got = nl._fallback_intent("毛收入（未折扣未税）是多少", _menu())
    assert got == {"kind": "metric", "name": "grossRevenue"}

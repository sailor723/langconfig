"""Gates for tutorial samples: click-through, verified numbers, and a reset that only removes."""
import pathlib
import pytest
from services import ontology_samples as s


def test_the_three_samples_are_business_answers_a_person_could_have_typed():
    assert len(s.SAMPLES) >= 3
    for sp in s.SAMPLES:
        assert sp["answers"]["name"] and sp["answers"]["question"] and sp["answers"]["arithmetic"]
        # a sample must be MORE than a one-table count: it says what it joins
        assert sp["why_it_is_not_one_table"]
        # and it must be checkable: a number or row count that proves the demo worked
        assert sp["expect"].get("values")
        assert sp["metric"]


def test_an_unknown_sample_is_refused_with_the_alternatives_named():
    with pytest.raises(s.SampleError) as exc:
        s.sample_by_id("nope")
    assert "damaged-by-route-version" in str(exc.value)


def test_a_sample_only_applies_to_its_ontology():
    with pytest.raises(s.SampleError):
        s.reset("clinic", "damaged-by-route-version", apply_now=False)


def test_the_strip_removes_exactly_one_block_and_nothing_else():
    text = """@prefix : <http://x#> .

:keepMe a owl:DatatypeProperty ;
    rdfs:label "保留" ;
    :aggregate "count" .

:dropMe a owl:DatatypeProperty ;
    rdfs:label "删我" ;
    :aggregate "sum" ;
    :businessDescription "多行也要整块删掉" .

:alsoKeep a owl:DatatypeProperty ;
    rdfs:label "也保留" .
"""
    out, removed = s._strip_block(text, "dropMe")
    assert removed is True
    assert ":dropMe" not in out
    assert ":keepMe" in out and ":alsoKeep" in out
    # the rest of the file must be byte-identical
    assert out == text.replace("""
:dropMe a owl:DatatypeProperty ;
    rdfs:label "删我" ;
    :aggregate "sum" ;
    :businessDescription "多行也要整块删掉" .
""", "")


def test_a_block_with_no_terminator_is_not_cut():
    with pytest.raises(s.SampleError):
        s._strip_block(":x a owl:Class ;\n    rdfs:label \"no terminator\"\n", "x")


def test_reset_reports_when_the_metric_is_already_absent(monkeypatch, tmp_path):
    live = tmp_path / "ontologies" / "logistics"
    live.mkdir(parents=True)
    (live / "metrics_ext.ttl").write_text('@prefix : <http://x#> .\n', encoding="utf-8")
    from services import ontology_publish
    monkeypatch.setattr(ontology_publish, "ONTOLOGIES", tmp_path / "ontologies")
    out = s.reset("logistics", "baskets-per-1k-km", apply_now=False)
    assert out["ok"] is False and out["already_absent"] is True
    assert "nothing to reset" in out["reason"]

"""The build panel must read the questions where the agent actually wrote them.

Measured twice on 2026-11-13 while building meeting_v1: one run wrote `generated/questions.json`, another
wrote a markdown decision list. The reader in `services/ontology_build.py` knew only the documented
`work/<key>/questions.json`, so the panel listed nothing — the agent asked in prose, the interface asked
nobody, and both sides waited. The skill's rule is unchanged; the READER had to accept the runtime's
output, because "nobody answered" and "nobody was asked" are the same screenshot.
"""
import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
BUILD = REPO / "backend" / "services" / "ontology_build.py"


def _source() -> str:
    return BUILD.read_text(encoding="utf-8")


def test_the_reader_accepts_the_documented_path_and_the_two_it_met():
    text = _source()
    for fragment in ('base / "questions.json"',
                     '/ "generated" / "questions.json"',
                     '/ "questions.json"'):
        assert fragment in text, f"the questions reader no longer looks in {fragment}"


def test_the_reader_stops_at_the_first_parseable_copy():
    """A stale copy in a second location must not win over the one the agent just wrote."""
    text = _source()
    start = text.index("qdoc, qpath = None, None")
    body = text[start:start + 900]
    assert body.index('base / "questions.json"') < body.index('/ "generated" / "questions.json"'), \
        "generated/ is searched before work/<key>/ — a stale copy would win"
    assert "break" in body, "the reader does not stop after the first parseable file"

"""A generated graph page must prove it matches the declarations it describes.

Measured on talent_v1 (2026-11-14): the profile served a page with 12 structure nodes and 9 live metrics
while it declared 11 metrics and the generator emitted 13 — the browser drew a graph of a previous
ontology and nothing in the page said so. The first fix compared mtimes, which does not survive a
checkout: `git pull` stamps the page and its TTLs identically.

So the page carries a sha256 fingerprint of the TTL files it read, and the app regenerates on mismatch (or
when a page predates the check and carries none). A page that cannot be shown current is a guess.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[2]
GRAPH_VIEW = REPO / "backend" / "features" / "ontology" / "compiler" / "graph_view.py"
PAGES = REPO / "backend" / "services" / "ontology_pages.py"
PROFILE = REPO / "backend" / "features" / "ontology" / "profiles" / "talent_v1"


def test_the_generator_embeds_a_fingerprint_of_its_inputs():
    text = GRAPH_VIEW.read_text(encoding="utf-8")
    assert "fingerprint=digest.hexdigest()[:16]" in text, "the page no longer records what it was built from"
    assert "digest.update(path.read_bytes())" in text, "the fingerprint does not cover the file contents"


def test_the_app_regenerates_on_a_fingerprint_mismatch():
    text = PAGES.read_text(encoding="utf-8")
    assert "_graph_page_is_stale" in text
    assert '"fingerprint"' in text, "the page's fingerprint is not read back"
    assert "return True                     # a page with no fingerprint predates this check" in text, (
        "a page without a fingerprint must be treated as stale, not trusted")


def test_the_shipped_page_is_current():
    """The committed page must match the committed declarations — otherwise the repo ships a lie."""
    page = PROFILE / "ontology.html"
    if not page.is_file():
        return
    html = page.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'"fingerprint":\s*"([0-9a-f]+)"', html)
    assert m, "the shipped page has no fingerprint"
    import hashlib

    settings_text = (PROFILE / "talent_v1_settings.json").read_text(encoding="utf-8")
    import json

    settings = json.loads(settings_text)
    candidates = []
    overlay = settings.get("overlay")
    if overlay and (PROFILE / overlay).is_file():
        candidates.append(PROFILE / overlay)
    onto = PROFILE / (settings.get("ontology_dir") or "ontology")
    candidates += sorted(onto.glob("*.ttl"))
    digest = hashlib.sha256()
    for path in candidates:
        digest.update(str(path.name).encode())
        digest.update(str(path.stat().st_size).encode())
        digest.update(path.read_bytes())
    assert digest.hexdigest()[:16] == m.group(1), (
        "profiles/talent_v1/ontology.html was built from different declarations; regenerate it")

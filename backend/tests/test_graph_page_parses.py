"""A generated graph page must PARSE — the browser is the last place to find that out.

Measured on talent_v1 (2026-11-14): the page rendered blank. The data was all there (25 nodes, 11 live
metrics); the inline script had `SyntaxError: missing ) after argument list`, because two template
literals in `graph_view.py` were closed after a newline instead of on their own line:

    html += section(`域 :${esc(n.name)} — ${n.inDomain.length} 个属性,
                    propTable(n.inDomain));

Any page generated from that source is dead on arrival, and every earlier signal was green: the generator's
own self-check passed (25/25 positioned), the profile shipped the file, the HTTP status was 200 and the
bytes were there. A headless browser reported it in one line.

This test generates a page for a committed profile and runs `node --check` on its script, so a broken
template is caught at build time instead of in a reader's blank window.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
GRAPH_VIEW = BACKEND / "features" / "ontology" / "compiler" / "graph_view.py"
PROFILE = BACKEND / "features" / "ontology" / "profiles" / "talent_v1"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def test_the_generated_page_script_parses(tmp_path):
    out = tmp_path / "graph.html"
    proc = subprocess.run([
        sys.executable, str(GRAPH_VIEW),
        "--ontology-dir", str(PROFILE / "ontology"),
        "--overlay", str(PROFILE / "metrics_ext.ttl"),
        "--ns", "https://cube.local/ontology/talent_v1#",
        "--title", "talent_v1 parse check",
        "--out", str(out),
    ], capture_output=True, text=True, cwd=str(BACKEND), timeout=600)
    assert out.is_file(), proc.stderr[-800:]
    html = out.read_text(encoding="utf-8", errors="replace")
    body = re.search(r"<script>(.*)</script>", html, re.S)
    assert body, "the page has no inline script"
    js = tmp_path / "graph.js"
    js.write_text(body.group(1), encoding="utf-8")
    check = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    first = [line for line in check.stderr.splitlines() if "SyntaxError" in line]
    assert check.returncode == 0, f"the graph page script does not parse: {first[:1]}"


def test_no_template_literal_spans_a_newline_in_the_generator():
    """The specific shape that broke it: a backtick opened on one line and closed on the next."""
    text = GRAPH_VIEW.read_text(encoding="utf-8")
    offenders = [
        line for line in text.splitlines()
        if re.search(r"section\(`[^`]*$", line)
    ]
    assert not offenders, f"unterminated template literal(s): {offenders[:2]}"

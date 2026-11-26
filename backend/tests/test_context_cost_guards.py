"""Two context-cost guards: a capped shell result, and a gate-doc tool that replaces `sed`.

Measured on one ontology build (2026-11-26): 151 `execute` results carried 325,712 characters —
88% of every tool result in the turn — and the five biggest were `cat gate.py` (18,545),
`sed 02-meaning.ttl` (12,863), `ls -la` (10,448), `sed gate.py` (10,040), `grep` (9,509).
Each one is re-sent on every later model call, so the context — not the work — drove the cost.

* `_cap_output` keeps a shell result's head and tail, says exactly how much it cut, and names the
  door for the rest (`read_file` with offset/limit) so the model does not re-run it verbatim.
* `ontology_gate_doc` answers "what does this gate check?" from the gate's own source instead of
  800 lines of `sed` output.
"""
from __future__ import annotations

import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from services.workspace_filesystem_backend import (  # noqa: E402
    _EXECUTE_OUTPUT_CAP,
    _EXECUTE_OUTPUT_HEAD,
    _cap_output,
)


class _Resp:
    def __init__(self, output, exit_code=0, truncated=False):
        self.output = output
        self.exit_code = exit_code
        self.truncated = truncated


def test_a_short_result_is_untouched():
    r = _Resp("ok")
    assert _cap_output(r, _Resp) is r


def test_an_oversized_result_keeps_head_and_tail_and_says_so():
    text = "HEAD" + ("x" * 50_000) + "TAIL-ERROR"
    out = _cap_output(_Resp(text, exit_code=1), _Resp)
    assert out.truncated is True
    assert out.exit_code == 1, "the exit code is evidence and must survive the cap"
    assert out.output.startswith("HEAD")
    assert out.output.endswith("to see the rest]")
    assert "TAIL-ERROR" in out.output, "the tail is where errors print — it must survive"
    assert len(out.output) < len(text)
    assert "characters cut from the middle" in out.output
    assert "read_file" in out.output, "the cap must name the door for the rest, not just complain"
    # head budget respected before the marker
    assert out.output[: _EXECUTE_OUTPUT_HEAD] == text[: _EXECUTE_OUTPUT_HEAD]


def test_the_cap_is_smaller_than_the_results_that_measured_it():
    # the five biggest results measured were 9.5k–18.5k characters
    assert _EXECUTE_OUTPUT_CAP <= 10_000


def test_gate_doc_lists_checks_from_source():
    from tools.native_impl import ontology_gate_doc

    text = ontology_gate_doc("check_dashboard")
    assert "gate: check_dashboard.py" in text
    assert "checks printed" in text
    # the dashboard gate prints D-numbered checks; the extractor must find them
    assert "D0" in text or "D1" in text
    assert "Read the checks:".lower() not in text.lower()


def test_gate_doc_without_a_name_lists_the_families():
    from tools.native_impl import ontology_gate_doc

    text = ontology_gate_doc()
    assert "gates (id → first line of its docstring)" in text
    assert "check_structure" in text and "check_dashboard" in text


# ─────────────────────────── the two "read it once" documents must stay true ────────────

DOCS = BACKEND.parent / "docs" / "system-architecture"


def test_the_dsl_doc_teaches_shapes_that_are_valid_turtle():
    """Every turtle block in ontology-dsl.md must PARSE — an example that does not parse would be
    the most expensive kind of doc: it teaches a syntax the gates reject."""
    import re

    import rdflib

    # the shapes now live in the merged document (6.1); the old file is a pointer stub
    text = (DOCS / "data-agent.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```turtle\n(.*?)```", text, re.S)
    assert len(blocks) >= 4, f"expected the four minimal shapes, found {len(blocks)}"
    for i, block in enumerate(blocks, 1):
        g = rdflib.Graph()
        g.parse(data=block, format="turtle")       # raises on invalid turtle
        assert len(g) >= 1, f"block {i} declared nothing"


def test_platform_facts_points_at_files_that_exist():
    """Each fact names its proof; a pointer to a file that was renamed away is a lie."""
    import re

    merged = (DOCS / "data-agent.md").read_text(encoding="utf-8")
    start = merged.find("## 6.3 平台事实")
    assert start > 0, "§6.3 平台事实 is gone from the merged document"
    end = merged.find("\n---\n", start)
    text = merged[start:end if end > 0 else len(merged)]
    paths = set(re.findall(r"`((?:backend/|docs/)[\w./\-]+?)`", text))
    paths |= {p.split("::")[0] for p in re.findall(r"`([a-z][\w./\-]+\.py)::", text)}
    assert paths, "no file pointers found"
    missing = []
    for p in sorted(paths):
        if p.endswith("/"):
            continue
        if not (BACKEND.parent / p).exists():
            missing.append(p)
    assert not missing, f"platform-facts.md points at files that do not exist: {missing}"


def test_stage_gate_mapping_matches_the_stage_code():
    """`ontology_gate_doc(stage=…)` claims which gates a stage runs. If stage_checks changes and
    the tool does not, the answer becomes fiction — so compare them mechanically."""
    import re

    from tools.native_impl import STAGE_GATES

    src = (BACKEND / "features" / "ontology" / "stage_checks.py").read_text(encoding="utf-8")
    for stage, claimed in STAGE_GATES.items():
        fn = re.search(rf"def check_{stage}\(.*?(?=\ndef |\Z)", src, re.S)
        if fn is None:
            continue
        actual = re.findall(r'_run_gate\("([a-z_]+)"', fn.group(0))
        assert sorted(set(actual)) == sorted(set(claimed)), (
            f"{stage}: stage_checks runs {sorted(set(actual))}, the tool claims {sorted(set(claimed))}")


def test_gate_doc_by_stage_is_compact():
    """The point of the tool is that it replaces `sed`-ing a 800-line gate: keep it small."""
    from tools.native_impl import ontology_gate_doc

    text = ontology_gate_doc(stage="structure")
    assert text.startswith("stage: structure")
    assert "check_structure" in text
    assert len(text) < 4000, f"stage answer is {len(text)} chars — too big to replace a read"


# ─────────────────────────── how a file path is resolved (the base that bit us) ──────────────
def _backend(tmp_path):
    from services.workspace_filesystem_backend import WorkspaceShellBackend

    (tmp_path / "work" / "demo_v1").mkdir(parents=True)
    (tmp_path / "work" / "demo_v1" / "SPEC.md").write_text("spec", encoding="utf-8")
    return WorkspaceShellBackend(root_dir=str(tmp_path))


def test_absolute_and_relative_paths_mean_the_same_workspace_file(tmp_path):
    """`/work/…` and `work/…` are the SAME file — the file-tool base is the workspace root.

    Measured 2026-11-26: a build asked `read_file("/work/<key>/SPEC.md")` and got "not found";
    it then spent calls re-exploring directories. The path convention, not the file, was wrong —
    so it belongs in the docs (`platform-facts.md`) and it is asserted here.
    """
    b = _backend(tmp_path)
    assert b._resolve_path("/work/demo_v1/SPEC.md") == b._resolve_path("work/demo_v1/SPEC.md")
    assert b._resolve_path("work/demo_v1/SPEC.md").read_text(encoding="utf-8") == "spec"


# ─────────────────────────── one ontology, one server: `ontology_key` on the db tools ────────
def test_profile_dsn_supplies_the_tools_connection():
    """`tpch` lives on :5432/role weiping while the platform's database is :5433/langconfig.

    Before this, every db tool took host/port/user separately and the build rediscovered them per
    call (twice falling back to psycopg2 in a shell, which the guard refuses). The profile already
    declares the server — these assertions are what makes `ontology_key=` a real door.
    """
    from tools.native_impl import _pg_conn_kwargs, _profile_dsn

    declared = _profile_dsn("tpch_sales_v3") if _has_key("tpch_sales_v3") else None
    if declared is None:
        import pytest

        pytest.skip("tpch_sales_v3 profile not present on this machine")
    assert str(declared.get("port")) == "5432", declared
    assert declared.get("user") == "weiping", declared
    kw = _pg_conn_kwargs(ontology_key="tpch_sales_v3")
    assert kw["port"] == 5432 and kw["user"] == "weiping" and kw["dbname"] == "tpch"


def test_an_explicit_argument_beats_the_profile():
    from tools.native_impl import _pg_conn_kwargs

    if not _has_key("tpch_sales_v3"):
        import pytest

        pytest.skip("tpch_sales_v3 profile not present on this machine")
    kw = _pg_conn_kwargs(port=6543, user="someone", ontology_key="tpch_sales_v3")
    assert kw["port"] == 6543 and kw["user"] == "someone"


def test_an_unknown_ontology_key_refuses_by_name():
    from tools.native_impl import _profile_dsn

    import pytest

    with pytest.raises(ValueError) as exc:
        _profile_dsn("no_such_ontology")
    assert "no profile" in str(exc.value)


def _has_key(key: str) -> bool:
    return (BACKEND / "features" / "ontology" / "profiles" / key).is_dir()


# ─────────────────────────── nothing case-specific gets baked into the shared surfaces ──────
CASE_TOKENS = ("tpch", "tpc-h", "600,572", "20,535", "5432", "weiping", "orders_demo",
               "sunhing", "retail_db", "asia", "europe")


def test_the_agent_prompt_is_case_free():
    """The prompt must describe the RULE, not one case: the next build may be a new Excel or a
    new database, and a prompt that names a server or a table teaches the wrong facts."""
    import os

    body = (BACKEND / "tools" / "_prompt_probe.md")
    # read the live prompt body through the same script a human uses
    import subprocess
    import sys as _sys

    out = subprocess.run([_sys.executable, str(BACKEND / "scripts" / "set_agent_prompt.py"), "393", "--show"],
                         capture_output=True, text=True, cwd=str(BACKEND),
                         env={**os.environ})
    raw = out.stdout or ""
    assert "你是" in raw, "could not read the prompt back"
    # the machine tail (identity + AGENTS.md) carries the machine's path — that is not a case fact,
    # so the check is on the AUTHORED body only.
    body = raw.split("## Identity")[0].split("AGENTS.md")[0]
    text = body.lower()
    found = [t for t in CASE_TOKENS if t in text]
    assert not found, f"the prompt carries case-specific facts: {found}"


def test_shared_docs_mark_their_examples():
    """`ontology-dsl.md` / `platform-facts.md` / `ontology-metrics-shapes.md` may SHOW a case, but
    every line that names one must be marked as an example (`示例` / `例子` / `example`)."""
    docs = BACKEND.parent / "docs" / "system-architecture"
    offenders = []
    for name in ("ontology-dsl.md", "platform-facts.md", "ontology-metrics-shapes.md"):
        p = docs / name
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if any(t in low for t in CASE_TOKENS) and not any(
                    k in low for k in ("示例", "例子", "example", "例：", "example:")):
                offenders.append(f"{name}:{i} {line.strip()[:70]}")
    assert not offenders, "case-specific facts must be marked as examples:\n" + "\n".join(offenders)


def test_start_pack_is_derived_not_baked():
    """The start pack may mention the key it was asked about, and nothing else case-specific."""
    from tools.native_impl import ontology_start_pack

    if not _has_key("tpch_sales_v3"):
        import pytest

        pytest.skip("tpch_sales_v3 profile not present on this machine")
    text = ontology_start_pack("tpch_sales_v3").lower()
    # the facts it reports must be the ones the profile declares
    import json

    prof = json.loads((BACKEND / "features/ontology/profiles/tpch_sales_v3"
                       / "tpch_sales_v3_settings.json").read_text(encoding="utf-8"))
    assert str(prof["dsn"]["dbname"]) in text
    assert "ontology-gate-doc" in text.replace("_", "-") or "ontology_gate_doc" in text
    # and it must NOT carry the numbers of some other build
    for token in ("600,572", "20,535", "148,301"):
        assert token not in text, f"start pack carries a case number: {token}"


def test_toc_matches_headings():
    """目录是本篇唯一的导航；插一章而忘了重算，读者就会点到空处。

    `scripts/build_toc.py --check` 是同一套判断，这条测试让它进入 pytest。
    """
    import subprocess
    import sys as _sys

    r = subprocess.run([_sys.executable, str(BACKEND.parent / "scripts" / "build_toc.py"), "--check"],
                       capture_output=True, text=True, cwd=str(BACKEND.parent))
    assert r.returncode == 0, (r.stdout + r.stderr)[:400]


def test_docx_toc_links_resolve():
    """docx 里的目录条目是指向书签的内部链接；书签没建好就是 55 个死链。"""
    docx = BACKEND.parent / "docs" / "system-architecture" / "data-agent.docx"
    if not docx.is_file():
        import pytest

        pytest.skip("docx not built on this machine")
    from docx import Document
    from docx.oxml.ns import qn

    d = Document(str(docx))
    links = [h.get(qn("w:anchor")) for h in d.element.body.findall(".//" + qn("w:hyperlink"))]
    names = {b.get(qn("w:name")) for b in d.element.body.findall(".//" + qn("w:bookmarkStart"))}
    dangling = [a for a in links if a and a not in names]
    assert links, "no clickable entries found in the docx"
    assert not dangling, f"{len(dangling)} TOC entries point at no bookmark: {dangling[:5]}"


def test_fenced_code_is_literal_in_the_docx_build():
    """围栏里的 `# xxx` 不许变成一级标题。

    2026-11-26 的 bug：`grill.md` 样例用 ```markdown 包着，里面第一行是 `# grill · <key>`；
    docx 的解析器不认围栏，于是文档里多出一个「grill · <key>」一级章节，目录也差点跟着漂。
    围栏内的 `| a | b |` 同样不是表格 —— 它们是**被展示的内容**，不是排版指令。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_data_agent_docs", BACKEND.parent / "scripts" / "build_data_agent_docs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    blocks = mod.parse((BACKEND.parent / "docs" / "system-architecture" / "data-agent.md")
                       .read_text(encoding="utf-8"))
    heads = [b["text"] for b in blocks if b["kind"] == "h"]
    assert not [h for h in heads if h.startswith("grill ·")], \
        "a fenced `# grill · <key>` example leaked into the heading list"
    assert not [h for h in heads if h.startswith("有意未定（")], \
        "a fenced `## 有意未定` example leaked into the heading list"
    code = [b for b in blocks if b["kind"] == "code"]
    assert code, "no fenced blocks parsed at all — the fence branch is dead"
    assert any(any(line.startswith("# grill ·") for line in b["lines"]) for b in code), \
        "the grill.md example should be one literal code block"


def test_html_anchors_all_resolve():
    """HTML 版的 55 条目录链接必须都能落地 —— 和 docx 的书签是同一条要求。

    `data-agent.html` 用两套锚点：`#sNNN` 给 PDF（WeasyPrint 的命名目标只吃 ASCII），
    标题 slug 留给 GitHub/md 预览。任何一套对不上都是死链，所以两套一起查。
    """
    import re

    page = BACKEND.parent / "docs" / "system-architecture" / "data-agent.html"
    if not page.is_file():
        import pytest

        pytest.skip("data-agent.html not built on this machine")
    html = page.read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    hrefs = re.findall(r'href="#([^"]+)"', html)
    assert hrefs, "no clickable TOC entries found"
    dangling = [h for h in hrefs if h not in ids]
    assert not dangling, f"{len(dangling)} 条链接点不到锚点: {dangling[:5]}"


def test_pdf_is_a_real_artifact():
    """PDF 不是"生成过"就算：页数、书签、内部链接都要存在，且没有文字冲出纸边。"""
    import pathlib as _p

    pdf = BACKEND.parent / "docs" / "system-architecture" / "data-agent.pdf"
    if not pdf.is_file():
        import pytest

        pytest.skip("data-agent.pdf not built on this machine")
    try:
        import fitz
    except ImportError:                      # pragma: no cover - optional dep
        import pytest

        pytest.skip("PyMuPDF not installed")
    doc = fitz.open(str(pdf))
    try:
        assert doc.page_count > 50, f"only {doc.page_count} pages"
        refs = [l.get("nameddest") for p in doc for l in p.get_links() if l.get("kind") == 4]
        names = doc.resolve_names()
        missing = [r for r in refs if r not in names]
        assert refs and not missing, f"{len(missing)} 条 PDF 内部链接解不开: {missing[:5]}"
        # 内容右界 = 纸宽 − 16mm 边距；超出说明表格/长标识符被裁掉了
        right = doc[0].rect.width - 45.4
        over = [i + 1 for i, p in enumerate(doc)
                if max([max((d["rect"].x1 for d in p.get_drawings()), default=0),
                        max((b[2] for b in p.get_text("blocks")), default=0)]) > right + 1]
        assert not over, f"文字越出右边距的页: {over[:8]}"
    finally:
        doc.close()


def test_version_stamp_agrees_across_artifacts():
    """同一个版本号只能有一个来源：md 顶部那行。

    docx 页脚、html 的 <meta name="doc-version">、PDF 每页页脚，都必须与它一致 ——
    否则读者拿到的三份文件各说一个版本（"docx 是 v1.0、PDF 还是旧的"）。
    """
    import importlib.util
    import re

    root = BACKEND.parent
    md = (root / "docs/system-architecture/data-agent.md").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "bdah", root / "scripts/build_data_agent_html.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mark = mod.stamp(md)                      # 缺版本/日期行会直接 SystemExit
    version = re.search(r"v[\d.]+", mark).group(0)
    date = re.search(r"\d{4}-\d{2}-\d{2}", mark).group(0)

    html = root / "docs/system-architecture/data-agent.html"
    if html.is_file():
        page = html.read_text(encoding="utf-8")
        meta = re.search(r'<meta name="doc-version" content="([^"]+)">', page)
        assert meta and meta.group(1) == mark, f"html 的版本戳不一致: {meta and meta.group(1)!r}"

    docx = root / "docs/system-architecture/data-agent.docx"
    if docx.is_file():
        from docx import Document

        d = Document(str(docx))
        foot = "".join(p.text for p in d.sections[0].footer.paragraphs)
        assert version in foot and date in foot, f"docx 页脚没有版本/日期: {foot!r}"

    pdf = root / "docs/system-architecture/data-agent.pdf"
    if pdf.is_file():
        try:
            import fitz
        except ImportError:                   # pragma: no cover
            import pytest

            pytest.skip("PyMuPDF not installed")
        doc = fitz.open(str(pdf))
        try:
            last = doc[-1]
            footers = [b[4] for b in last.get_text("blocks") if b[1] > last.rect.height - 60]
            joined = " ".join(footers)
            assert version in joined and date in joined, \
                f"PDF 末页页脚没有版本/日期: {joined!r}"
        finally:
            doc.close()

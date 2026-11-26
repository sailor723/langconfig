#!/usr/bin/env python3
"""把 `data-agent.md` 渲染成**一个自带的 HTML**（图片内联、目录可点），再交给 WeasyPrint 出 PDF。

    python scripts/build_data_agent_html.py            # → data-agent.html（+ data-agent.pdf 若装了 weasyprint）

为什么不用 pandoc 一把梭：本文的目录用的是 **GitHub 锚点**（`#第-1-步-先被-grill…`），
pandoc 会另生成一套 `auto_identifier`，两套 slug 对不上就是 55 个死链。这里直接复用
`build_toc.slug()` —— 同一个函数同时决定 md 目录、docx 书签和本文件的 `id`，三份产物不会各说各话。

产物：
  docs/system-architecture/data-agent.html   自包含（内联 SVG + 内联 CSS），双击可读、可打印
  docs/system-architecture/data-agent.pdf    A4，目录条目是**真的内部链接**（WeasyPrint 保留锚点）
"""
from __future__ import annotations

import html as _html
import importlib.util
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "system-architecture"
ASSETS = ROOT / "docs" / "assets"
SRC = DOCS / "data-agent.md"

_spec = importlib.util.spec_from_file_location("build_toc", ROOT / "scripts" / "build_toc.py")
_toc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_toc)

CSS = """
@page {
  /* 12mm 边距 + 让正文更密：一页能装更多，A4 上仍然留有可读的呼吸感。
     这个数值也决定 PDF 守卫的右边界（见 backend/tests/test_context_cost_guards.py）——两边必须一致。 */
  size: A4;
  margin: 12mm 12mm 13mm 12mm;
  @bottom-center {
    content: "__STAMP__ · 第 " counter(page) " / " counter(pages) " 页";
    font-size: 7.5pt; color: #8a96a3;
    font-family: -apple-system, "PingFang SC", system-ui, sans-serif;
  }
}
:root { --ink:#16202b; --muted:#5b6b7c; --line:#d8e0e8; --accent:#0b6bcb; --bg:#fbfcfd;
        --code-bg:#f2f5f8; --warn:#fff7e6; --warn-line:#f0b429; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font: 16px/1.78 -apple-system, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei",
             "Noto Sans CJK SC", system-ui, sans-serif; }
main { max-width: 940px; margin: 0 auto; padding: 48px 28px 96px; }
h1, h2, h3, h4 { line-height:1.3; letter-spacing:.2px; }
h1 { font-size: 27px; margin: 44px 0 16px; padding-bottom: 10px; border-bottom: 2px solid var(--line); }
h1:first-of-type { margin-top: 0; border-bottom: 0; font-size: 31px; }
h2 { font-size: 21px; margin: 34px 0 12px; }
h3 { font-size: 18px; margin: 26px 0 10px; color:#1d2b3a; }
h4 { font-size: 16px; margin: 20px 0 8px; color:var(--muted); }
p { margin: 10px 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
a.anchor { display:block; height:0; }
code { font-family: "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; font-size: 13.5px;
       background: var(--code-bg); padding: 1px 5px; border-radius: 4px; }
pre { background: #0f1720; color: #e6edf3; padding: 14px 16px; border-radius: 10px;
      overflow-x: auto; font-size: 12.8px; line-height: 1.62;
      white-space: pre-wrap; overflow-wrap: anywhere; }
pre code { background: none; color: inherit; padding: 0; font-size: inherit; }
blockquote { margin: 14px 0; padding: 10px 16px; border-left: 4px solid var(--accent);
             background: #f4f8fd; color: #24384f; border-radius: 0 8px 8px 0; }
blockquote p { margin: 4px 0; }
ul, ol { margin: 10px 0 10px 4px; padding-left: 22px; }
li { margin: 5px 0; }
table { border-collapse: collapse; width: 100%; margin: 14px 0; font-size: 14.5px; background:#fff; }
th, td { border: 1px solid var(--line); padding: 7px 10px; text-align: left; vertical-align: top;
         overflow-wrap: anywhere; }   /* 单元格里常有 ontology_verify_stage(...) 这种长 token：
                                          不许断行它就把整张表撑出纸面（WeasyPrint 会静默裁掉） */
th { background: #eef3f8; font-weight: 600; }
tbody tr:nth-child(even) { background: #fafcfe; }
figure { margin: 20px 0; }
/* 宽屏时让图比正文更宽：图里的字是矢量，放大看仍然清楚，但先得给它宽度 */
@media screen and (min-width: 1100px) {
  figure { width: min(1180px, 94vw); margin-left: calc((100% - min(1180px, 94vw)) / 2); }
}
figure svg { width: 100%; height: auto; display: block; border: 1px solid var(--line);
             border-radius: 10px; background: #0f1419; }
figcaption { color: var(--muted); font-size: 13px; margin-top: 6px; }
hr { border: 0; border-top: 1px solid var(--line); margin: 34px 0; }
.note { background: var(--warn); border-left: 4px solid var(--warn-line); padding: 10px 16px;
        border-radius: 0 8px 8px 0; }
@media print {
  /* 打印版比屏幕版密一档：字号小一点、行距紧一点、块间距小一点。
     屏幕版（上面的 :root/body）不动——那是给人读的，这是给纸和 PDF 的。 */
  body { background:#fff; font-size: 9.4pt; line-height: 1.48; }
  main { max-width: none; padding: 0; }
  a { color: #0b4f96; }
  h1 { break-before: page; font-size: 17pt; margin: 6pt 0 4pt; padding-bottom: 4pt; }
  h1:first-of-type { break-before: avoid; font-size: 20pt; }
  h2 { font-size: 13pt; margin: 10pt 0 3pt; }
  h3 { font-size: 11pt; margin: 8pt 0 2pt; }
  h4 { font-size: 9.8pt; margin: 6pt 0 2pt; }
  h2, h3, h4 { break-after: avoid; }
  p { margin: 3pt 0; }
  ul, ol { margin: 3pt 0 3pt 0; padding-left: 16pt; }
  li { margin: 1.5pt 0; }
  hr { margin: 10pt 0; }
  blockquote { margin: 5pt 0; padding: 4pt 8pt; }
  blockquote p { margin: 1pt 0; }
  figure { margin: 6pt 0; }
  figcaption { font-size: 8pt; margin-top: 2pt; }
  /* 图按纸宽等比缩：宽度给 82% 时高度同比降，图多的一篇能省下好几页 */
  figure svg { width: 82%; margin: 0 auto; }
  /* 表格允许跨页（thead 会在新页重复）；原来一律 avoid 会把大表整体推到下一页，留下半页空白 */
  pre, blockquote, figure { break-inside: avoid; }
  table { break-inside: auto; }
  /* 表格按纸宽重排：六列密表在 A4 上要么缩小字号，要么冲出纸边 */
  /* 固定布局：列宽均分、内容在格内换行。auto 布局会按 min-content 撑列，
     一个 `tests/....py::test_...` 就能把整张表推过纸边（WeasyPrint 静默裁掉）。 */
  table { width: 100%; table-layout: fixed; font-size: 8pt; }
  th, td { padding: 2.5pt 4pt; word-break: break-all; }
  td code, th code { font-size: 0.92em; }   /* 单元格里的 code 用 px 字号就不随表缩小，撑宽整张表 */
  /* 正文里 `tests/xxx.py::test_yyy` 这种长标识符也要能断，否则它一个人就越过纸边 */
  code { word-break: break-all; }
  /* break-all 是给 `test_xxx.py::test_yyy` 这种长标识符用的：WeasyPrint 的表格布局
     按 min-content 撑列，不认 overflow-wrap: anywhere，不 break-all 就冲出纸边。 */
  thead { display: table-header-group; }
  pre { background: #f4f6f8; color: #16202b; border: 1px solid var(--line);
        font-size: 7.8pt; line-height: 1.35; padding: 6pt 8pt; margin: 4pt 0;
        white-space: pre-wrap; overflow-wrap: anywhere; }
  figure svg { background: #0f1419; }
}
"""


# ─────────────────────────────────────────────────────────── 行内 markdown → HTML
_CODE_PLACEHOLDER = "\x00CODE{}\x00"


def inline(text: str) -> str:
    """粗体 / 行内代码 / 链接。顺序很重要：代码先摘出去，否则里面的 `*` `|` 会被当语法。"""
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(f"<code>{_html.escape(m.group(1))}</code>")
        return _CODE_PLACEHOLDER.format(len(spans) - 1)

    text = re.sub(r"`([^`]+)`", stash, text)
    text = _html.escape(text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                  lambda m: f'<img alt="{m.group(1)}" src="{m.group(2)}">', text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                  lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = text.replace("&quot;", '"')
    for i, span in enumerate(spans):
        text = text.replace(_CODE_PLACEHOLDER.format(i), span)
    return text


def svg_block(src: str) -> str | None:
    p = (DOCS / src).resolve()
    if p.suffix != ".svg" or not p.is_file():
        return None
    svg = p.read_text(encoding="utf-8")
    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    svg = svg.replace('width="', 'data-w="', 1) if False else svg
    return svg.strip()


# ────────────────────────────────────────────────────────────────── md → HTML 主体
def render(md: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = md.splitlines()
    out: list[str] = []
    heads: list[tuple[int, str, str]] = []
    seen: dict[str, int] = {}          # 同名标题 → `-1`、`-2`，与 build_toc.py 的规则一致
    i, n = 0, len(lines)
    in_list: str | None = None          # "ul" / "ol" / None

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append(f"</{in_list}>")
            in_list = None

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            close_list()
            i += 1
            continue

        if stripped.startswith("<!--"):      # TOC 标记之类的注释，丢掉
            close_list()
            i += 1
            continue

        if stripped.startswith("```"):       # 代码块：字面量，不做任何解释
            close_list()
            code: list[str] = []
            i += 1
            while i < n and not lines[i].lstrip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            body = _html.escape("\n".join(code))
            out.append(f'<pre><code>{body}</code></pre>')
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            close_list()
            level, text = len(m.group(1)), m.group(2).strip()
            base = _toc.slug(text)
            count = seen.get(base, 0)      # 注意：不要用 `n`，那是行数
            seen[base] = count + 1
            anchor = base if count == 0 else f"{base}-{count}"
            k = len(heads)
            heads.append((level, text, anchor))
            # 两个锚点：`sNNN` 给 PDF（命名目标必须 ASCII，CJK 名字会被 WeasyPrint 写成乱码字节），
            # 原标题 slug 留给 GitHub / md 预览。
            out.append(f'<a class="anchor" id="s{k:03d}"></a>'
                       f'<h{level} id="{_html.escape(anchor)}">{inline(text)}</h{level}>')
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):     # 分隔线
            close_list()
            out.append("<hr>")
            i += 1
            continue

        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", stripped)
        if m:                                                   # 独立成行的图：内联 SVG
            close_list()
            alt, src = m.group(1), m.group(2)
            svg = svg_block(src)
            if svg:
                out.append(f'<figure>{svg}<figcaption>{inline(alt)}</figcaption></figure>')
            else:
                out.append(f'<figure><img alt="{alt}" src="{src}">'
                           f'<figcaption>{inline(alt)}</figcaption></figure>')
            i += 1
            continue

        if stripped.startswith("|"):                            # 表格
            close_list()
            rows: list[list[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                width = max(len(r) for r in rows)
                head, body = rows[0], rows[1:]
                parts = ['<table><thead><tr>']
                parts += [f"<th>{inline(c)}</th>" for c in head]
                parts.append("</tr></thead><tbody>")
                for r in body:
                    parts.append("<tr>" + "".join(
                        f"<td>{inline(c)}</td>" for c in r + [""] * (width - len(r))) + "</tr>")
                parts.append("</tbody></table>")
                out.append("".join(parts))
            continue

        if stripped.startswith(">"):                            # 引用
            close_list()
            quote: list[str] = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip().lstrip(">").strip())
                i += 1
            while quote and not quote[-1]:
                quote.pop()
            joined, buf = [], []
            for q in quote:
                if not q:                        # 引用里的空行 = 段落分隔
                    joined.append("<p>" + inline(" ".join(buf)) + "</p>")
                    buf = []
                else:
                    buf.append(q)
            if buf:
                joined.append("<p>" + inline(" ".join(buf)) + "</p>")
            out.append("<blockquote>" + "".join(joined) + "</blockquote>")
            continue

        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if in_list != "ul":
                close_list()
                out.append("<ul>")
                in_list = "ul"
            out.append(f"<li>{inline(m.group(1).strip())}</li>")
            i += 1
            continue

        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            if in_list != "ol":
                close_list()
                out.append("<ol>")
                in_list = "ol"
            out.append(f"<li>{inline(m.group(1).strip())}</li>")
            i += 1
            continue

        close_list()
        out.append(f"<p>{inline(stripped)}</p>")
        i += 1

    close_list()
    return "\n".join(out), heads


VERSION_RE = re.compile(r"\*\*版本\*\*\s*(v[\d.]+)")
DATE_RE = re.compile(r"\*\*日期\*\*\s*(\d{4}-\d{2}-\d{2})")


def stamp(md: str) -> str:
    """版本与日期只写在 md 里一处；三份产物都从这行读，避免"docx 是 v1.0、pdf 是 v1.1"。"""
    v = VERSION_RE.search(md)
    d = DATE_RE.search(md)
    if not v or not d:
        raise SystemExit("data-agent.md 缺 `**版本** vX.Y` 或 `**日期** YYYY-MM-DD` 那行")
    return f"数据 Agent 总文档 {v.group(1)} · {d.group(1)}"


def build() -> pathlib.Path:
    md = SRC.read_text(encoding="utf-8")
    mark = stamp(md)
    body, heads = render(md)
    for k, (_, _, anchor) in enumerate(heads):
        body = body.replace(f'href="#{anchor}"', f'href="#s{k:03d}"')
    title = heads[0][1] if heads else "data-agent"
    doc = (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{_html.escape(title)}</title>\n"
        f'<meta name="doc-version" content="{_html.escape(mark)}">\n'
        f"<style>{CSS.replace('__STAMP__', mark)}</style>\n</head>\n<body>\n<main>\n"
        f"{body}\n</main>\n</body>\n</html>\n"
    )
    out = DOCS / "data-agent.html"
    out.write_text(doc, encoding="utf-8")
    return out


def to_pdf(src: pathlib.Path) -> pathlib.Path | None:
    exe = shutil.which("weasyprint")
    if not exe:
        print("weasyprint 不在 PATH，跳过 PDF", file=sys.stderr)
        return None
    pdf = DOCS / "data-agent.pdf"
    env = {"XDG_CACHE_HOME": "/tmp/weasy-cache", "HOME": str(pathlib.Path.home())}
    import os

    r = subprocess.run([exe, "--encoding", "utf-8", str(src), str(pdf)],
                       capture_output=True, text=True,
                       env={**os.environ, **env})
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:], file=sys.stderr)
        return None
    font_warn = [ln for ln in (r.stderr or "").splitlines() if "font" in ln.lower()]
    print("\n".join(font_warn[:5]))
    return pdf


def main() -> int:
    html = build()
    print(f"{html.name}: {html.stat().st_size // 1024} KB")
    pdf = to_pdf(html)
    if pdf:
        print(f"{pdf.name}: {pdf.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

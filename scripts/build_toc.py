#!/usr/bin/env python3
"""在文档开头生成可点击的目录（markdown 锚点 + docx 书签/超链接）。

    python scripts/build_toc.py            # 重写 data-agent.md 的目录块
    python scripts/build_toc.py --check    # 只检查目录与标题是否一致（CI/测试用）

为什么要有脚本：目录是"手写一定会漂"的典型——插一章、改个标题，手写目录就指错地方。
这里从标题现算锚点，并把表格夹在 `<!--TOC-->` 两个标记之间，重复运行是幂等的。

锚点规则与 GitHub 一致（这也是 md 预览器/Word 里点击的依据）：
小写 → 去掉除字母数字、CJK、空格、`-`、`_` 之外的字符 → 空格变 `-`；
同名标题第二次出现时加 `-1`（以此类推）。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "system-architecture" / "data-agent.md"
BEGIN, END = "<!--TOC-->", "<!--/TOC-->"


def slug(text: str) -> str:
    s = re.sub(r"`([^`]*)`", r"\1", text)            # 行内代码
    s = re.sub(r"\*\*([^*]*)\*\*", r"\1", s)          # 加粗
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)    # 链接
    out = []
    for ch in s.strip().lower():
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or ch in "-_":
            out.append(ch)
        elif ch in " \t·：:，,。.、（）()「」“”\"'/":
            if ch in " \t":
                out.append("-")
        else:
            continue
    s = "".join(out)
    return re.sub(r"-{2,}", "-", s).strip("-")


def headings(text: str) -> list[tuple[int, str, str]]:
    """(level, title, anchor) — level 1 与 2；跳过代码块里的 #。"""
    out, used = [], {}
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,2})\s+(.*)$", line)
        if not m:
            continue
        level, title = len(m.group(1)), m.group(2).strip()
        anchor = slug(title)
        n = used.get(anchor, 0)
        used[anchor] = n + 1
        out.append((level, title, anchor if n == 0 else f"{anchor}-{n}"))
    return out


def build_toc(levels: list[tuple[int, str, str]]) -> str:
    lines = [BEGIN, "", "## 目录", "",
             "> 点标题直接跳转（markdown 预览器、GitHub、Word 里都可点）。", ""]
    for level, title, anchor in levels:
        if level == 1:
            lines.append(f"- **[{title}](#{anchor})**")
        else:
            lines.append(f"    - [{title}](#{anchor})")
    lines += ["", END]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    text = DOC.read_text(encoding="utf-8")
    levels = [h for h in headings(text) if h[0] in (1, 2)]
    # 目录里不放"目录"自己、也不放文首标题
    levels = [h for h in levels if h[1] != "目录"]
    block = build_toc(levels)

    if "--check" in argv:
        if BEGIN not in text:
            print("no TOC block in the document", file=sys.stderr)
            return 1
        cur = text[text.find(BEGIN):text.find(END) + len(END)]
        if cur.strip() != block.strip():
            print("TOC is stale — run `python scripts/build_toc.py`", file=sys.stderr)
            return 1
        print(f"TOC ok · {len(levels)} entries")
        return 0

    if BEGIN in text and END in text:
        text = text[:text.find(BEGIN)] + block + text[text.find(END) + len(END):]
    else:
        anchor = text.find("\n---\n")
        at = text.find("\n---\n", anchor + 1) if anchor > 0 else len(text)
        text = text[:at + 1] + "\n" + block + "\n" + text[at + 1:]
    DOC.write_text(text, encoding="utf-8")
    print(f"TOC written · {len(levels)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

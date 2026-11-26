#!/usr/bin/env python3
"""量一遍手画 SVG：文字有没有越出它所在的框、有没有跑出画布。

    python scripts/check_svg_overflow.py                 # 默认检查 docs/assets/data-agent-*.svg
    python scripts/check_svg_overflow.py a.svg b.svg

为什么需要它：SVG 的溢出是**静默**的。`<text>` 写宽了不会报错，只会压到相邻框上；
`<rect>` 画到 `viewBox` 之外也不会报错，只会被裁掉一半 —— 2026-11-26 就是靠这个脚本发现
`data-agent-pipeline7.svg` 的 STOP-2 胶囊 cy=762 落在 720 高的画布外，图上只有半个框。

判据沿用 `build_data_agent_charts.py` 的同一套字宽规则（`text_width`），所以它和生成器
"以为"的宽度是同一个模型，不会各说各话。退出码非 0 表示有问题，可直接进 CI。
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("charts", HERE / "build_data_agent_charts.py")
charts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(charts)

TAG = re.compile(r"<(rect|text)\b([^>]*)>")
ATTR = re.compile(r'([\w-]+)="([^"]*)"')
CANVAS = re.compile(r'viewBox="0 0 ([\d.]+) ([\d.]+)"')


def check(path: pathlib.Path) -> int:
    svg = path.read_text(encoding="utf-8")
    m = CANVAS.search(svg)
    if not m:
        print(f"{path.name}: 没有 viewBox，跳过")
        return 0
    cw, ch = (float(v) for v in m.groups())
    rects: list[tuple[float, float, float, float]] = []
    texts: list[tuple[dict[str, str], str]] = []
    for tag in TAG.finditer(svg):
        kind, raw = tag.group(1), dict(ATTR.findall(tag.group(2)))
        if kind == "rect":
            x, y = float(raw["x"]), float(raw["y"])
            w, h = float(raw["width"]), float(raw["height"])
            if w >= cw - 1 and h >= ch - 1:      # 背景板不算框
                continue
            rects.append((x, y, w, h))
        else:
            texts.append((raw, svg[tag.end():svg.index("</text>", tag.end())]))

    bad_in: list[str] = []
    bad_out: list[str] = []
    for raw, body in texts:
        if not body.strip():
            continue
        x, y = float(raw["x"]), float(raw["y"])
        fs = float(raw.get("font-size", 15))
        anchor = raw.get("text-anchor", "start")
        w = charts.text_width(body, fs)
        x0 = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        x1 = x0 + w
        if x0 < 2 or x1 > cw - 2 or y > ch - 2:
            bad_out.append(f"出画布: {body!r} x={x0:.0f}..{x1:.0f} y={y:.0f}")
        # 文字锚点落在哪个框里（取面积最小的那个），再比宽度
        inside = [(rw * rh, (rx, ry, rw, rh)) for rx, ry, rw, rh in rects
                  if rx <= x <= rx + rw and ry <= y <= ry + rh]
        if not inside:
            continue
        _, (rx, ry, rw, rh) = min(inside)
        if x0 < rx - 1 or x1 > rx + rw + 1 or y > ry + rh:
            bad_in.append(f"越框: {body!r} x={x0:.0f}..{x1:.0f} 框={rx:.0f}..{rx + rw:.0f}")

    print(f"{path.name}: {len(rects)} 框 · {len(texts)} 文本 · 越框{len(bad_in)} · 出画布{len(bad_out)}")
    for line in bad_in + bad_out:
        print("  " + line)
    return 1 if (bad_in or bad_out) else 0


def main(argv: list[str]) -> int:
    paths = ([pathlib.Path(a) for a in argv[1:]] if len(argv) > 1
             else sorted((HERE.parent / "docs" / "assets").glob("data-agent-*.svg")))
    rc = 0
    for p in paths:
        rc |= check(p)
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

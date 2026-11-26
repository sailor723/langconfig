#!/usr/bin/env python3
"""Draw the two data-agent charts by hand (SVG), then rasterise them for the docx.

    python scripts/build_data_agent_charts.py

Why not graphviz: `dot` refuses to lay this out readably. Measured on the first attempt — a
23-node graph came out 910×748 (a hairball), and the "two rows" version collapsed to 1858×204
(9.1:1) because `rank=same` plus a chain cannot express "these five are row one, those five are
row two". Hand-placed coordinates remove that fight entirely: the boxes go where the reading order
is, the text is the size we choose, and the aspect ratio is 1.6:1 so the figure survives being
dropped into a 6.3-inch column.

Outputs (docs/assets/):
  data-agent-flow.svg/.png   图 1 — 数据 → 本体 → 看板，两处停点
  data-agent-lanes.svg/.png  图 2 — 泳道：你 / 系统，同一批阶段
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "assets"

BG = "#0F1419"
INK = "#E6EDF3"
MUTED = "#8B98A5"
USER_FILL, USER_LINE, USER_INK = "#1B2A1B", "#51CF66", "#B2F2BB"
SYS_FILL, SYS_LINE, SYS_INK = "#12202E", "#4DABF7", "#D0EBFF"
STOP_FILL, STOP_LINE, STOP_INK = "#3A2A07", "#F59F00", "#FFD8A8"
PROD_FILL, PROD_LINE, PROD_INK = "#11161C", "#3A4450", "#9AA7B4"

W, H = 1180, 760



# ─────────────────────────────────────── 文本"放进框里"：量宽 + 折行 + 必要时缩字号
def _char_w(ch: str, fs: float) -> float:
    o = ord(ch)
    if ch == " ":
        return fs * 0.30
    if 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF:   # CJK / 全角
        return fs * 1.00
    return fs * 0.60                                                              # Menlo 近似


def text_width(text: str, fs: float) -> float:
    return sum(_char_w(c, fs) for c in text)


def wrap(text: str, max_w: float, fs: float) -> list[str]:
    """按字符折行，优先在空格与常见分隔符处断开（中文没有空格，只能逐字）。"""
    if text_width(text, fs) <= max_w:
        return [text]
    breaks = set(" ·、，；：/｜|")
    out, cur = [], ""
    for ch in text:
        if text_width(cur + ch, fs) > max_w and cur:
            cut = max((i for i in range(len(cur)) if cur[i] in breaks), default=-1)
            if cut > 0 and cut > len(cur) - 6:
                out.append(cur[:cut].rstrip())
                cur = cur[cut + 1:] + ch
            else:
                out.append(cur)
                cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def fit(lines: list[str], max_w: float, max_h: float, fs: float, *, min_fs: float = 9.0,
        gap: float = 6.0):
    """在给定框内找到能放下的字号与折行；返回 (lines, fs)。放不下就缩到 min_fs 继续硬折。"""
    size = fs
    while size >= min_fs:
        line_h = size + gap
        wrapped: list[str] = []
        for ln in lines:
            wrapped.extend(wrap(ln, max_w, size))
        if len(wrapped) * line_h <= max_h:
            return wrapped, size
        size -= 0.5
    return [wrap(ln, max_w, min_fs) for ln in lines][0] if lines else [], min_fs


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))



def soft_curve(x1, y1, x2, y2, *, colour="#F59F00", opacity=0.75, width=1.6, lift=0.55,
               dash=None, head=True):
    """一条"软"的连线：三次贝塞尔 + 圆头 + 低不透明度，末端是一个小圆点而不是尖三角。

    用户的原话是「线硬、有尖角」。硬来自三件事：折线、宽描边、三角箭头。这里三件都换掉：
    曲线代替折线、1.6px + 圆头代替 2px 方头、圆点代替三角。
    """
    dy = (y2 - y1) * lift
    path = f"M {x1},{y1} C {x1},{y1 + dy} {x2},{y2 - dy} {x2},{y2}"
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    out = [f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="{width}" '
           f'stroke-opacity="{opacity}" stroke-linecap="round"{dash_attr}/>']
    if head:
        out.append(f'<circle cx="{x2}" cy="{y2}" r="3.4" fill="{colour}" '
                   f'fill-opacity="{min(1.0, opacity + 0.15)}"/>')
    return "\n".join(out)


def soft_line(x1, y1, x2, y2, *, colour="#4D6A8A", opacity=0.5, width=1.4):
    """lane 内的横向连接：细、半透明、圆头，不要箭头（同一泳道里是顺序，不是交接）。"""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" '
            f'stroke-width="{width}" stroke-opacity="{opacity}" stroke-linecap="round"/>')


def soft_arrow(x1, y1, x2, y2, *, colour="#4D6A8A", opacity=0.6, width=1.5):
    """带小圆头的直线箭头（用在同一行内的推进，保持"软"）。"""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2 - 5}" y2="{y2 - 5 if y1 != y2 else y2}" '
            f'stroke="{colour}" stroke-width="{width}" stroke-opacity="{opacity}" '
            f'stroke-linecap="round"/>'
            f'<circle cx="{x2}" cy="{y2}" r="3" fill="{colour}" fill-opacity="{min(1, opacity+0.2)}"/>')

def box(x, y, w, h, lines, *, fill, line, ink, rx=10, fs=15, weight="600", dash=None):
    """框内文字必须留在框内：先量宽折行，必要时缩字号；max_w 还留 12px 内边距。"""
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" ry="{rx}" '
           f'fill="{fill}" stroke="{line}" stroke-width="2"'
           + (f' stroke-dasharray="{dash}"' if dash else "") + "/>"]
    if not lines:
        return "\n".join(out)
    fitted, size = fit(lines, w - 12, h - 10, fs)
    line_h = size + 6
    top = y + h / 2 - (len(fitted) - 1) * line_h / 2 + size / 3
    for i, ln in enumerate(fitted):
        weight_i = weight if i == 0 else "400"
        size_i = size if i == 0 else size - 1.5
        colour = ink if i == 0 else MUTED
        out.append(f'<text x="{x + w/2}" y="{top + i*line_h}" fill="{colour}" '
                   f'font-family="Menlo, monospace" font-size="{size_i}" font-weight="{weight_i}" '
                   f'text-anchor="middle">{esc(ln)}</text>')
    return "\n".join(out)


def pill(cx, cy, w, h, lines, *, fill, line, ink, fs=15):
    """圆角胶囊：停点用。八边形是尖角，用户明确说不要尖角。"""
    x, y = cx - w / 2, cy - h / 2
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2}" ry="{h/2}" '
           f'fill="{fill}" fill-opacity="0.92" stroke="{line}" stroke-width="1.6" '
           f'stroke-opacity="0.85"/>']
    fitted, size = fit(lines, w - 20, h - 8, fs)
    line_h = size + 6
    top = cy - (len(fitted) - 1) * line_h / 2 + size / 3
    for i, ln in enumerate(fitted):
        out.append(f'<text x="{cx}" y="{top + i*line_h}" fill="{ink if i == 0 else MUTED}" '
                   f'font-family="Menlo, monospace" font-size="{size if i == 0 else size-1.5}" '
                   f'font-weight="{600 if i == 0 else 400}" text-anchor="middle">{esc(ln)}</text>')
    return "\n".join(out)


def octagon(cx, cy, w, h, lines, *, fill, line, ink, fs=15):
    dx, dy = w / 2, h / 2
    pts = [(cx - dx + 14, cy - dy), (cx + dx - 14, cy - dy), (cx + dx, cy - dy + 14),
           (cx + dx, cy + dy - 14), (cx + dx - 14, cy + dy), (cx - dx + 14, cy + dy),
           (cx - dx, cy + dy - 14), (cx - dx, cy - dy + 14)]
    poly = " ".join(f"{px},{py}" for px, py in pts)
    out = [f'<polygon points="{poly}" fill="{fill}" stroke="{line}" stroke-width="2"/>']
    n = len(lines)
    line_h = fs + 6
    top = cy - (n - 1) * line_h / 2 + fs / 3
    for i, ln in enumerate(lines):
        out.append(f'<text x="{cx}" y="{top + i*line_h}" fill="{ink if i == 0 else MUTED}" '
                   f'font-family="Menlo, monospace" font-size="{fs if i == 0 else fs-3}" '
                   f'font-weight="{600 if i == 0 else 400}" text-anchor="middle">{esc(ln)}</text>')
    return "\n".join(out)


def arrow(x1, y1, x2, y2, *, colour="#4D6A8A", label="", dashed=False, width=2):
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    head = 9
    p1 = (x2 - head * math.cos(ang - 0.42), y2 - head * math.sin(ang - 0.42))
    p2 = (x2 - head * math.cos(ang + 0.42), y2 - head * math.sin(ang + 0.42))
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour}" stroke-width="{width}"'
           f'{dash} marker-end="url(#a)"/>']
    out.append(f'<polygon points="{x2},{y2} {p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}" fill="{colour}"/>')
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 7
        out.append(f'<text x="{mx}" y="{my}" fill="{MUTED}" font-family="Menlo, monospace" '
                   f'font-size="11" text-anchor="middle">{esc(label)}</text>')
    return "\n".join(out)


def head(title: str, subtitle: str) -> str:
    return (f'<rect x="0" y="0" width="{W}" height="{H}" fill="{BG}"/>\n'
            f'<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            f'markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="#4D6A8A"/></marker></defs>\n'
            f'<text x="34" y="46" fill="{INK}" font-family="Menlo, monospace" font-size="22" '
            f'font-weight="700">{esc(title)}</text>\n'
            f'<text x="34" y="70" fill="{MUTED}" font-family="Menlo, monospace" font-size="13">'
            f'{esc(subtitle)}</text>\n')


def legend(y: int) -> str:
    items = [("你要做的", USER_FILL, USER_LINE), ("Agent 做的", SYS_FILL, SYS_LINE),
             ("停点（等你）", STOP_FILL, STOP_LINE), ("产物 / 落盘", PROD_FILL, PROD_LINE)]
    out, x = [], 34
    for label, fill, line in items:
        out.append(box(x, y, 22, 14, [], fill=fill, line=line, ink=INK, rx=4))
        out.append(f'<text x="{x + 30}" y="{y + 12}" fill="{MUTED}" font-family="Menlo, monospace" '
                   f'font-size="12">{esc(label)}</text>')
        x += 34 + 12 * len(label) + 22
    return "\n".join(out)


# ──────────────────────────────────────────────── 唯一的图：泳道 + 进度带
# 设计（按用户的两条口味改）：
#  * 只要一张图（游泳道），不再有流程图；
#  * 线要软：贝塞尔曲线 + 圆头 + 低不透明度 + 圆点箭头，停点用圆角胶囊而不是八边形。
# 阶段 = 票：Agent 的步骤就是 T1…Tn；T0 是开工前的准备（数据 + grill + 切票）。
STAGES = [
    ("T0 准备", ["你：给数据 · 答一轮提问 · 确认表列", "Agent：摸事实 → grill.md → 对账 → 切 T1…Tn"], "t0"),
    ("T1 结构", ["你：放行规格（停点 1）", "Agent：01-structure / 02-meaning"], "t1"),
    ("T2 指标", ["你：看回执", "Agent：metrics_ext + samples"], "t2"),
    ("T3 看板", ["你：看成品", "Agent：dashboard.json"], "t3"),
    ("T4 教程", ["你：读拒绝清单", "Agent：tutorial + truth"], "t4"),
    ("T5 发布", ["你：点 apply（停点 2）", "Agent：压 staged"], "t5"),
]
SYS = [
    "摸清事实\n逐 sheet / 逐表 → grill → 对账",
    "01-structure.ttl\n02-meaning.ttl",
    "metrics_ext.ttl\nsamples.json",
    "dashboard.json\n10 KPI + 12 面板",
    "tutorial.json\ntruth.json（R2）",
    "staged 候选\n四族门禁 + 拒绝清单",
]
EVIDENCE = [  # 这次 TPC-H v3 的真实证据（每票一行）
    "2 sheet / 10 表 · 对账 0 差异",
    "93 checks · 0 failed",
    "32 可编译 + 3 拒绝",
    "112 checks, 0 failed",
    "T1–T5 + R2 2/2",
    "apply → git commit",
]
STATE = {k: ("done", "",) for k in ("t0", "t1", "t2", "t3", "t4", "t5")}
DONE_FILL, DONE_LINE, DONE_INK = "#16301C", "#4ADE80", "#BBF7D0"
BUSY_FILL, BUSY_LINE, BUSY_INK = "#1B2A46", "#60A5FA", "#BFDBFE"
TODO_FILL, TODO_LINE, TODO_INK = "#161C24", "#3A4450", "#7E8B99"


def lanes_progress() -> str:
    s = [head("图 · 数据 Agent 的泳道与进度",
              "上泳道是你，下泳道是 Agent；上方进度带用三态标出这次跑到哪（绿=已完成，蓝=进行中，灰=未开始）")]

    # 进度带
    bx, by, bw, bh = 40, 96, W - 80, 54
    s.append(box(bx, by, bw, bh, [], fill="#0E141A", line="#1F2A33", ink=INK, rx=16))
    n = len(STAGES)
    step = bw / n
    s.append(soft_line(bx + step / 2, by + bh / 2, bx + bw - step / 2, by + bh / 2,
                       colour="#4ADE80", opacity=0.35, width=2))
    for i, (title, _lines, key) in enumerate(STAGES):
        cx = bx + step * (i + 0.5)
        state, num = STATE[key]
        fill, line, ink = {"done": (DONE_FILL, DONE_LINE, DONE_INK),
                           "busy": (BUSY_FILL, BUSY_LINE, BUSY_INK),
                           "todo": (TODO_FILL, TODO_LINE, TODO_INK)}[state]
        dot = {"done": "●", "busy": "◐", "todo": "○"}[state]
        s.append(f'<circle cx="{cx}" cy="{by + bh/2}" r="7" fill="{fill}" stroke="{line}" stroke-width="1.4"/>')
        s.append(f'<text x="{cx}" y="{by + bh/2 + 4}" fill="{ink}" font-family="Menlo, monospace" '
                 f'font-size="9" text-anchor="middle">{dot}</text>')
        s.append(f'<text x="{cx}" y="{by + bh - 10}" fill="{MUTED}" font-family="Menlo, monospace" '
                 f'font-size="11" text-anchor="middle">{esc(title)}</text>')

    # 两条泳道
    lane_h = 168
    top_you, top_sys = 190, 190 + lane_h + 22
    s.append(box(28, top_you, W - 56, lane_h, [], fill="#101B18", line="#1E2B25", ink=INK, rx=18))
    s.append(box(28, top_sys, W - 56, lane_h, [], fill="#0F1621", line="#1C2735", ink=INK, rx=18))
    s.append(f'<text x="46" y="{top_you + 28}" fill="{USER_INK}" font-family="Menlo, monospace" '
             f'font-size="13" font-weight="700">你</text>')
    s.append(f'<text x="46" y="{top_sys + 28}" fill="{SYS_INK}" font-family="Menlo, monospace" '
             f'font-size="13" font-weight="700">Agent</text>')

    col_w = (W - 110) / n
    for i, (title, you_lines, key) in enumerate(STAGES):
        cx = 62 + i * col_w + col_w / 2
        s.append(box(cx - col_w / 2 + 6, top_you + 44, col_w - 20, 78, you_lines,
                     fill=USER_FILL, line=USER_LINE, ink=USER_INK, fs=12))
        s.append(box(cx - col_w / 2 + 6, top_sys + 44, col_w - 20, 78, SYS[i].split("\n"),
                     fill=SYS_FILL, line=SYS_LINE, ink=SYS_INK, fs=12))
        # 证据行：这一票"凭什么说完成"
        s.append(f'<text x="{cx}" y="{top_sys + 140}" fill="{DONE_INK if STATE[key][0]=="done" else MUTED}" '
                 f'font-family="Menlo, monospace" font-size="10" text-anchor="middle">'
                 f'{esc(EVIDENCE[i])}</text>')
        # 同一泳道内：细、半透明、无箭头（顺序，不是交接）
        if i < n - 1:
            s.append(soft_line(cx + col_w / 2 - 12, top_you + 83, cx + col_w / 2 + 4, top_you + 83))
            s.append(soft_line(cx + col_w / 2 - 12, top_sys + 83, cx + col_w / 2 + 4, top_sys + 83))
        # 交接：只在三处画，软曲线 + 圆点箭头
        if key in ("t0", "t1", "t5"):
            s.append(soft_curve(cx, top_you + 122, cx, top_sys + 40, colour=STOP_LINE, opacity=0.8))
            tag = {"t0": "给数据", "t1": "放行", "t5": "apply"}[key]
            s.append(f'<text x="{cx + 8}" y="{(top_you + 122 + top_sys + 40) / 2}" fill="{STOP_LINE}" '
                     f'font-family="Menlo, monospace" font-size="10" text-anchor="start">{tag}</text>')

    # 结论带：这次跑完的证据（真实数字）
    s.append(box(28, 620, W - 56, 96, [], fill="#0E141A", line="#1F2A33", ink=INK, rx=16))
    s.append(f'<text x="48" y="652" fill="{DONE_INK}" font-family="Menlo, monospace" font-size="13" '
             f'font-weight="700">这次（tpch_sales_v3）的真实证据</text>')
    s.append(f'<text x="48" y="676" fill="{MUTED}" font-family="Menlo, monospace" font-size="12">'
             f'T1 结构 93 checks · 0 failed　|　T2 指标 32 可编译 + 3 声明式拒绝　|　'
             f'T3 看板 112 checks, 0 failed　|　T4 教程 8 步 + R2 2/2　|　T5 发布 staged → apply</text>')
    s.append(f'<text x="48" y="698" fill="{MUTED}" font-family="Menlo, monospace" font-size="12">'
             f'发布：staged → 人 apply → git commit「ontology(tpch_sales_v3): publish …」</text>')

    s.append(legend(730))
    return "\n".join(s)


def write_svg(name: str, body: str) -> None:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
           f'\n{body}\n</svg>\n')
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(W * 2), "-o", str(OUT / f"{name}.png"),
                        str(OUT / f"{name}.svg")], check=True)
        note = "png: rsvg-convert"
    else:
        note = "png: skipped (rsvg-convert missing)"
    print(f"{name}: svg + {note}")


def main() -> int:
    write_svg("data-agent-lanes", lanes_progress())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

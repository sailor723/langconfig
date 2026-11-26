#!/usr/bin/env python3
"""把文档里的 ASCII 图改画成 SVG（同一套"软线"风格，手排坐标）。

    python scripts/build_data_agent_diagrams.py

生成五张图（SVG + PNG，PNG 供 docx 嵌入）：
  data-agent-pipeline7.svg  七格流水线 + 两处停点 + 每格产物（原 ASCII 图）
  data-agent-layers.svg     五层分层图（L4 对话 / L3 劳动 / L2 契约 / L1 声明 / L0 平台）
  data-agent-publish.svg    发布通道：stage() 的五个动作 → staged → 人 confirm → apply()
  data-agent-gates4.svg     一个数的四道门：声明 → 编译 → 护栏 → 执行
  data-agent-grill.svg      grill：三轮把「前沿」问空，答不了的进「有意未定」

画布外的东西会被静默裁掉，SVG 不会报错。所以要量，不要用眼睛：文字是否越框、是否出画布，
用 `scripts/check_svg_overflow.py` 跑一遍。这一轮就是这么发现 STOP-2 的胶囊落在 720 高的画布之外
（cy=762）—— 图上只渲染了半个框。

ASCII 图的问题不是丑，是**进不了 docx/md 的排版**：框线靠空格对齐，换个字体就散；
而且中文与框线的宽度在等宽字体以外对不上。这里沿用 `build_data_agent_charts.py` 的
文字测量与折行（同一套字宽规则），保证文字留在框内。
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("charts", HERE / "build_data_agent_charts.py")
charts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(charts)

OUT = HERE.parent / "docs" / "assets"
BG, INK, MUTED = charts.BG, charts.INK, charts.MUTED
USER_FILL, USER_LINE, USER_INK = charts.USER_FILL, charts.USER_LINE, charts.USER_INK
SYS_FILL, SYS_LINE, SYS_INK = charts.SYS_FILL, charts.SYS_LINE, charts.SYS_INK
STOP_FILL, STOP_LINE, STOP_INK = charts.STOP_FILL, charts.STOP_LINE, charts.STOP_INK
PROD_FILL, PROD_LINE, PROD_INK = charts.PROD_FILL, charts.PROD_LINE, charts.PROD_INK


def head(title: str, subtitle: str, w: int, h: int) -> tuple[list[str], int, int]:
    charts.W, charts.H = w, h
    return ([f'<rect x="0" y="0" width="{w}" height="{h}" fill="{BG}"/>',
             f'<text x="34" y="46" fill="{INK}" font-family="Menlo, monospace" font-size="22" '
             f'font-weight="700">{charts.esc(title)}</text>',
             f'<text x="34" y="70" fill="{MUTED}" font-family="Menlo, monospace" font-size="13">'
             f'{charts.esc(subtitle)}</text>'], w, h)


def write(name: str, body: str, w: int, h: int) -> None:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
           f'\n{body}\n</svg>\n')
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    if charts.shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", str(w * 2), "-o", str(OUT / f"{name}.png"),
                        str(OUT / f"{name}.svg")], check=True)
    print(f"{name}: {w}×{h}")


# ─────────────────────────────────────────── 图：七格流水线（+ 两处停点 + 产物）
def pipeline7() -> None:
    W, H = 1240, 800
    s, W, H = head("七格流水线：从一句话到 staging 候选",
                   "上排 1→4，下排 5→7；▣ 是必须等你的两处停点；每格下方是它落盘的产物", W, H)
    bw, bh = 250, 92
    xs = [40, 330, 620, 910]
    y1, y2 = 150, 430
    steps = [
        (1, "grill（393 自己）", "只问当前前沿 · 一题一决定", "work/_grill.md"),
        (2, "方案（tables）", "db_plan_from_file · 不建库", "方案（不建库）"),
        (3, "并进问题（393）", "把待确认点问清", "work/<key>/grill.md"),
        (4, "建库 + 对账（tables）", "db_build_from_file · db_verify_against_file", "真库 + PASS 报告"),
        (5, "登记（393）", "ontology_register", "→ <name>_v<N> 入库"),
        (6, "声明三连（modeller→metrics→board）", "S1 结构 → S2 含义 → S3 指标 → S4 护栏 → S5 样例 → S6 看板 → S7 教程 → S8 拒绝清单",
         "01-structure.ttl … tutorial.json"),
        (7, "发布（393）", "ontology_publish · 只到 staged", "拒绝清单 + 人工 apply"),
    ]
    row1 = steps[:3]
    row2 = steps[3:]
    for i, (num, who, what, art) in enumerate(row1):
        x = xs[i]
        s.append(charts.box(x, y1, bw, bh, [f"{num} · {who}", what], fill=SYS_FILL, line=SYS_LINE,
                            ink=SYS_INK, fs=12))
        s.append(charts.box(x, y1 + bh + 30, bw, 34, [art], fill=PROD_FILL, line=PROD_LINE,
                            ink=PROD_INK, fs=10))
        if i < len(row1) - 1:
            s.append(charts.soft_line(x + bw, y1 + bh / 2, xs[i + 1], y1 + bh / 2, colour=SYS_LINE))
        s.append(charts.soft_curve(x + bw / 2, y1 + bh, x + bw / 2, y1 + bh + 28, colour=PROD_LINE,
                                   head=False, opacity=0.4))
    # STOP-1
    s.append(charts.pill(xs[3] + bw / 2, y1 + bh / 2, 230, 78,
                         ["▣ STOP-1", "前沿已空，尚未实现任何东西"], fill=STOP_FILL,
                         line=STOP_LINE, ink=STOP_INK, fs=12))
    s.append(charts.soft_curve(xs[2] + bw, y1 + bh / 2, xs[3], y1 + bh / 2, colour=STOP_LINE))

    for i, (num, who, what, art) in enumerate(row2):
        x = xs[i] if i < 3 else xs[3]
        y = y2 if i < 3 else y2 + 120
        s.append(charts.box(x, y, bw, bh, [f"{num} · {who}", what], fill=SYS_FILL, line=SYS_LINE,
                            ink=SYS_INK, fs=12))
        s.append(charts.box(x, y + bh + 22, bw, 34, [art], fill=PROD_FILL, line=PROD_LINE,
                            ink=PROD_INK, fs=10))
        if i < 2:
            s.append(charts.soft_line(x + bw, y + bh / 2, xs[i + 1], y + bh / 2, colour=SYS_LINE))
    s.append(charts.soft_curve(xs[3] + bw / 2, y1 + bh + 100, xs[0] + bw / 2, y2, colour=SYS_LINE,
                               head=True))
    # 下排 7 → STOP-2（cy 必须留在画布内：原来的 762 落在 720 的画布外，被裁掉了）
    pill_cy = 750
    s.append(charts.pill(xs[3] + bw / 2, pill_cy, 230, 74,
                         ["▣ STOP-2", "只到 staged · 安装由人点"], fill=STOP_FILL,
                         line=STOP_LINE, ink=STOP_INK, fs=12))
    s.append(charts.soft_curve(xs[3] + bw / 2, y2 + 120 + bh + 22 + 34, xs[3] + bw / 2,
                               pill_cy - 37, colour=STOP_LINE))
    write("data-agent-pipeline7", "\n".join(x for x in s if x), W, H)


# ─────────────────────────────────────────── 图：五层分层
def layers() -> None:
    W, H = 1100, 560
    s, W, H = head("五层：从对话到平台", "L4 只有总控有用户通道；L3 四个专家各自独立上下文；越往下越像契约", W, H)
    rows = [
        ("L4 对话层", "manager agent（唯一有用户通道的 agent）", "grill · 汇总 · 登记 · 发布 · 汇报拒绝清单", SYS_FILL, SYS_LINE, SYS_INK),
        ("L3 劳动层", "4 个 subagent（各自上下文，只读文件、只回一条消息）", "tables │ modeller │ metrics │ board", SYS_FILL, SYS_LINE, SYS_INK),
        ("L2 契约层", "文件即接口 + 回执即契约", "work/<key>/grill.md · NOTES.md · JSON {produced, unverified, …}", PROD_FILL, PROD_LINE, PROD_INK),
        ("L1 声明层", "profiles/<key>/：本体声明", "01-structure.ttl · 02-meaning.ttl · metrics_ext.ttl · samples.json · dashboard.json · tutorial.json", PROD_FILL, PROD_LINE, PROD_INK),
        ("L0 平台层", "编译器 · 门禁 · 发布通道 · 工作台", "sqlgen/guard/nl · check_* · stage→apply · Settings → Ontology", "#1A1226", "#8B5CF6", "#E5DBFF"),
    ]
    y = 110
    for name, one, two, fill, line, ink in rows:
        s.append(charts.box(40, y, W - 80, 74, [f"{name}   {one}", two], fill=fill, line=line,
                            ink=ink, fs=13))
        y += 88
    write("data-agent-layers", "\n".join(s), W, H)


# ─────────────────────────────────────────── 图：发布通道
def publish() -> None:
    W, H = 1100, 470
    s, W, H = head("发布通道：stage() 做什么，apply() 由谁点",
                   "左边是 agent 能做的（压到 staged），右边是人才能做的（confirm → apply）", W, H)
    s.append(charts.box(40, 150, 250, 90, ["work/<key>/*.ttl", "本体声明（已过四族门禁）"],
                        fill=PROD_FILL, line=PROD_LINE, ink=PROD_INK, fs=12))
    s.append(charts.box(360, 130, 330, 250, [
        "ontology_publish → stage()",
        "① 备份已安装版本 → 暂存副本",
        "② 逐指标编译（compiler）",
        "③ 跑 gates.json 声明的族",
        "④ new_refusals / carried 分开列",
        "⑤ 停在 staged（不安装）",
    ], fill=SYS_FILL, line=SYS_LINE, ink=SYS_INK, fs=12))
    s.append(charts.box(760, 130, 300, 250, [
        "人 · confirm → apply()",
        "① 再跑门禁",
        "② 字节级备份",
        "③ git commit（平台身份）",
        "④ _versions.json latest 指向新版本",
    ], fill=USER_FILL, line=USER_LINE, ink=USER_INK, fs=12))
    s.append(charts.soft_curve(290, 195, 360, 195, colour=SYS_LINE))
    s.append(charts.soft_curve(690, 255, 760, 255, colour=STOP_LINE))
    s.append(charts.pill(725, 88, 370, 46, ["▣ STOP-2：安装只能由人点"], fill=STOP_FILL,
                         line=STOP_LINE, ink=STOP_INK, fs=12))
    write("data-agent-publish", "\n".join(s), W, H)


# ─────────────────────────────────────────── 图：四道门
def gates4() -> None:
    W, H = 1100, 300
    s, W, H = head("一个数的四道门", "只有编译器产出的 SQL 会被执行；护栏在数字出现之前先拒绝", W, H)
    items = [("声明（TTL）", "类/属性/关系/指标"), ("编译", "唯一一条 SELECT"),
             ("护栏", "LIMIT · 预算 · 超时"), ("执行", "数字或按名拒绝")]
    x = 40
    bw = 230
    for i, (t, sub) in enumerate(items):
        s.append(charts.box(x, 140, bw, 84, [t, sub], fill=SYS_FILL, line=SYS_LINE, ink=SYS_INK, fs=14))
        if i < len(items) - 1:
            s.append(charts.soft_curve(x + bw, 182, x + bw + 30, 182, colour=SYS_LINE))
        x += bw + 30
    s.append(charts.pill(x - bw / 2 + 10, 250, 300, 42, ["任何一步拒绝 → 按名给出缺哪条声明"],
                         fill=STOP_FILL, line=STOP_LINE, ink=STOP_INK, fs=11))
    write("data-agent-gates4", "\n".join(s), W, H)


# ─────────────────────────────────────────── 图：grill（决策树 + 前沿）
def grill() -> None:
    W, H = 1240, 620
    s, W, H = head("grill：把决策树问空，再动手",
                   "每轮只问「前沿」= 现在就能答的问题；答案把前沿往外推；没人能答的写成「有意未定」，不猜",
                   W, H)
    bw, bh = 240, 84
    xs = [40, 335, 630]
    heads = [("第 1 轮 · 前沿（现在能答）", xs[0]), ("第 2 轮 · 答案解锁的", xs[1]),
             ("第 3 轮 · 只剩一问", xs[2])]
    for label, x in heads:
        s.append(f'<text x="{x + bw / 2}" y="116" fill="{MUTED}" font-family="Menlo, monospace" '
                 f'font-size="12" text-anchor="middle">{charts.esc(label)}</text>')

    def q(x, y, lines, dash=None):
        s.append(charts.box(x, y, bw, bh, lines, fill=SYS_FILL, line=SYS_LINE, ink=SYS_INK,
                            fs=12, dash=dash))

    # 第 1 轮：前置条件已满足，现在就能问的三问
    q(xs[0], 136, ["Q1 退货率分母", "A 订单数 / B 行数", "→ A ·「一单退一单」"])
    q(xs[0], 232, ["Q2 时间轴", "A 下单 / B 发货", "→ A · 与对账单同期"])
    q(xs[0], 328, ["Q3 金额", "A 含税扣退货 / B 不含税", "→ A · 财务口径"])
    # 第 2 轮：答案刚落下来，挂在后面的问题才成为前沿
    q(xs[1], 184, ["Q4 城市维度（靠 Q1 的粒度）", "A 客户最新地址 / B 首单地址", "→ A · 两种地址常不一致"])
    q(xs[1], 280, ["Q5 回款口径（靠 Q3 的金额）", "A 到账日 / B 开票日", "➡️ A · 与 D1 同期"])
    q(xs[1], 376, ["Q6 成本口径（谁都没有答案）", "财务：还没给", "→ 下一轮再问，不进计划"], dash="6 5")
    # 第 3 轮：再问一次，仍然是"没人能定"
    q(xs[2], 376, ["Q7 成本口径（再问一次）", "财务：还是没给", "→ 不猜，写成有意未定"], dash="6 5")
    s.append(charts.box(xs[2], 474, bw, 76, ["有意未定（交付物）", "成本口径 · 汇率",
                                             "→ :refusalReason 按名拒绝"],
                        fill=STOP_FILL, line=STOP_LINE, ink=STOP_INK, fs=12))
    # 答案 → 解锁：金色软线，代表"前沿外推"
    for y1, y2 in ((178, 226), (274, 322), (370, 418)):
        s.append(charts.soft_curve(xs[0] + bw, y1, xs[1], y2, colour=STOP_LINE, opacity=0.8))
    s.append(charts.soft_curve(xs[1] + bw, 418, xs[2], 418, colour=STOP_LINE, opacity=0.8))
    s.append(charts.soft_curve(xs[2] + bw / 2, 460, xs[2] + bw / 2, 474, colour=STOP_LINE,
                               opacity=0.8, dash="4 4"))
    # 落入决定表
    px, py, pw, ph = 910, 136, 290, 320
    s.append(f'<text x="{px + pw / 2}" y="116" fill="{MUTED}" font-family="Menlo, monospace" '
             f'font-size="12" text-anchor="middle">{charts.esc("产物：决定表，每条一行理由")}</text>')
    s.append(charts.box(px, py, pw, ph, [
        "work/<key>/grill.md",
        "D1 时间口径 = 下单日期",
        "D2 金额 = 含税、扣退货",
        "D3 退货率分母 = 订单数",
        "D4 城市 = 客户最新地址",
        "未定：成本口径、汇率",
        "「前沿已空。",
        "尚未实现任何东西。」",
    ], fill=PROD_FILL, line=PROD_LINE, ink=PROD_INK, fs=12))
    s.append(charts.soft_curve(xs[2] + bw, 512, px, 420, colour=STOP_LINE, opacity=0.7))
    # 每轮发生了什么（图的读法）
    for cap, x, y in (("答 A / A / A → 解锁 3 个新问题", xs[0] + bw / 2, 440),
                      ("答 A / A → 1 个没人能答", xs[1] + bw / 2, 488)):
        s.append(f'<text x="{x}" y="{y}" fill="{MUTED}" font-family="Menlo, monospace" '
                 f'font-size="11" text-anchor="middle">{charts.esc(cap)}</text>')
    s.append(charts.pill(620, 580, 900, 44,
                         ["停点 1 · 你确认 SPEC 与口径之后，才允许建库 / 登记 / 编译"],
                         fill=STOP_FILL, line=STOP_LINE, ink=STOP_INK, fs=12))
    write("data-agent-grill", "\n".join(s), W, H)


# ─────────────────────────────── 图：DSH 造 / Carrier 跑 的双向回路
def dsh_loop() -> None:
    W, H = 1140, 470
    s, W, H = head("DSH 造，Carrier 跑：一次改动的完整回路",
                   "左列是「造」的地方（有仓库、shell、DB、测试）；右列是「跑」的地方（只有自己的工具结果）",
                   W, H)
    lx, lw = 40, 520
    steps = [
        ("① 改 artefact", "agent 行 / prompt / SKILL.md / native_impl.py", SYS_FILL, SYS_LINE, SYS_INK),
        ("② 该 refresh 的 refresh", "seed_builtin_tools --refresh · POST /api/skills/reload-all", SYS_FILL, SYS_LINE, SYS_INK),
        ("③ 重启后端", "工具行里是代码副本：不重启就还在跑旧代码", STOP_FILL, STOP_LINE, STOP_INK),
        ("④ 一次真实 turn 验收", "run_agent_turn --agent N --msg …；看 SSE 的 complete 与工具调用", USER_FILL, USER_LINE, USER_INK),
        ("⑤ 守卫测试 + commit → push", "prompt 不是门禁，tests/ 才是；推 main 与 deploy", PROD_FILL, PROD_LINE, PROD_INK),
    ]
    y = 108
    for title, sub, fill, line, ink in steps:
        s.append(charts.box(lx, y, lw, 60, [title, sub], fill=fill, line=line, ink=ink, fs=12))
        if y > 108:
            s.append(charts.soft_curve(lx + 26, y - 12, lx + 26, y, colour=line, opacity=0.5, head=False))
        y += 70
    # 右侧：Carrier
    rx, rw = 640, 460
    s.append(charts.box(rx, 108, rw, 318, [
        "Carrier :8765",
        "前端 dist/（后端托管）· FastAPI",
        "deep_agent_templates（agent 行）",
        "custom_tools（工具行，含代码副本）",
        "skills/（SKILL.md 是产物本身）",
        "",
        "它只能说「我缺什么」",
        "改不了自己的行、也起不了进程",
    ], fill=PROD_FILL, line=PROD_LINE, ink=PROD_INK, fs=12))
    s.append(charts.soft_curve(lx + lw, 178, rx, 240, colour=USER_LINE, opacity=0.85))
    s.append(f'<text x="{(lx + lw + rx) / 2}" y="196" fill="{USER_LINE}" font-family="Menlo, monospace" '
             f'font-size="11" text-anchor="middle">pull → build → seed → restart</text>')
    s.append(charts.soft_curve(rx, 330, lx + lw, 300, colour=STOP_LINE, opacity=0.85, dash="5 4"))
    s.append(f'<text x="{(lx + lw + rx) / 2}" y="336" fill="{STOP_LINE}" font-family="Menlo, monospace" '
             f'font-size="11" text-anchor="middle">报「缺什么」/ unverified</text>')
    s.append(charts.pill(570, 444, 900, 40,
                         ["铁律：in-app agent 报缺 → 回 DSH 改 → refresh → 一次真实 turn 才算改完"],
                         fill=STOP_FILL, line=STOP_LINE, ink=STOP_INK, fs=11))
    write("data-agent-dsh-loop", "\n".join(s), W, H)


def main() -> int:
    pipeline7()
    layers()
    publish()
    gates4()
    grill()
    dsh_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

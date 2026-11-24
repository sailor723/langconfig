#!/usr/bin/env python3
"""生成**总览文档** `work/talent/OVERVIEW.md` —— 拿去给用户演示的那一页。

## 为什么要有它

`PROCESS.md` 是流程的**权威说明**（规则、判据、每条为什么），`STATUS.md` 是**按日期堆的流水账**。
演示时两样都不合适：一个太重，一个太散。这个脚本产出的是一页
"**从客户原文到最终 5 个人**"的全景 —— 每一步谁做、产出什么、门禁卡什么、现在是什么数。

## 数字从哪来

- 漏斗数字：`jd_links/`、`shortlist/`、`picks/` 现场扫出来的，**不手写**；
- 教程类数字：复用 `tutorial_facts.collect()`（同一份 facts，避免两处各算一遍）；
- 门禁汇总行：现场跑一次 `check_component_catalog` 取最后一行（`--skip-gate` 可跳过）。

用法:
    python -m scripts.talent.build_overview            # 生成 OVERVIEW.md
    python -m scripts.talent.build_overview --skip-gate # 不跑门禁（快）
    python -m scripts.talent.build_overview --check     # 只校验文件是否最新
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import yaml

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent import tutorial_facts as TF  # noqa: E402

TALENT = ROOT / 'work' / 'talent'
DEST = TALENT / 'OVERVIEW.md'


# ── 流程图（SVG，样式沿用本体教程里的那张 graph：同样的圆角框、同样的字阶与箭头）──
FLOW_NODES = [
    ('1', '上传 JD → 缺口', '#eef3fb', '#0b4f9c',
     ['_source/<JD>.txt + 缺口 md', '对 40 格模板逐格：原文/空值/缺']),
    ('2', 'HR + 业务定稿', '#eef3fb', '#0b4f9c',
     ['定稿(标准40格).md', '缺的格 mock 满 · 逐格标来源与待签']),
    ('3', '初筛 + HR 一面（必须）', '#fdf6e3', '#8a6d3b',
     ['shortlist/<JD>.yaml + cv_interview', '只剔硬证据 · 读不到一律留；补齐 CV + HR 评语']),
    ('4', '加面（可选）', '#f4f4f4', '#6b7280',
     ['cv_interview 追加', '跳过不是缺 · 跳过那几格记未知']),
    ('5a', '短名单 ≤10', '#fbe9e7', '#b3261e',
     ['目标名单.yaml · selected', '九层证据阶梯 · 切线 tie_band']),
    ('5b', '最终 ≤5 + 业务面问题', '#fbe9e7', '#b3261e',
     ['final + 业务面问题清单.md', '门槛 0 不满足 + 硬证据≥1 + 未知≤3']),
]
FLOW_EDGES = [
    (0, 1, '客户原话'), (1, 2, '闸门'), (2, 3, '面试名单'),
    (4, 3, '10 人以内'), (5, 4, '5 人'),
]


def _esc(x: str) -> str:
    """SVG 里的文字要转义 —— `jd_links/_source/<JD>.txt` 里的尖括号否则会被当成标签,
    整张图变成非法 XML(浏览器直接不显示)。"""
    return (str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


#: 字阶(2026-11-23 用户要求:字号整体 +30%,框按内容重新量)
F_TITLE, F_SUB, F_EDGE, F_FOOT = 11.0, 9.8, 12.0, 10.5
#: 框内边距与行高
PADX, PADY, TITLE_H, SUB_H = 26.0, 20.0, 16.0, 15.0
#: 框与框之间的呼吸（放大内边距后同步加大，否则图会挤成一团）
ACCENT_H = 5.0          # 框顶的高亮条

GAPX, GAPY = 70.0, 86.0


def _text_w(t: str, size: float) -> float:
    """粗估一行文字宽度:CJK 按 1.0em、ASCII 按 0.55em。不上渲染器也能算出框该多宽。"""
    w = 0.0
    for ch in str(t):
        w += size * (1.0 if '\u4e00' <= ch <= '\u9fa5' or ch in '，。；：、（）「」·—≤≥' else 0.55)
    return w


def flow_svg(gate: str = '') -> str:
    """六段流程图。字号与框尺寸**按内容算**，不再写死 —— 改文案不会再溢出。

    布局(蛇形,箭头只朝前):
        row1:  ① → ② → ③
                          ↓
        row2:  ⑤b ← ⑤a ← ④
    """
    nodes = FLOW_NODES
    # ① 每个框按内容定宽高
    sizes = []
    for num, title, _fill, _stroke, lines in nodes:
        w = max([_text_w(f'{num} · {title}', F_TITLE)] +
                [_text_w(l, F_SUB) for l in lines]) + 2 * PADX
        h = ACCENT_H + PADY + TITLE_H + SUB_H * len(lines) + PADY
        sizes.append((max(w, 190.0), h))
    # 统一成同一尺寸:六个框同宽同高才像张图(内容最长的那个决定格子多大)
    colw = max(w for w, _h in sizes)
    rowh = max(h for _w, h in sizes)
    sizes = [(colw, rowh) for _ in sizes]

    M = 34.0                                  # 画布留白
    x0, x1, x2 = M, M + colw + GAPX, M + 2 * (colw + GAPX)
    y0 = M
    y1 = M + rowh + GAPY
    pos = [(x0, y0), (x1, y0), (x2, y0), (x2, y1), (x1, y1), (x0, y1)]
    W = int(x2 + colw + M)
    H = int(y1 + rowh + M + 30)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" font-family="ui-sans-serif,-apple-system,Segoe UI,Roboto,sans-serif">',
           '<defs><marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
           'markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" '
           'fill="#334e68"/></marker></defs>',
           f'<rect width="{W}" height="{H}" fill="#f6f7f9"/>']

    def box(i):
        return (pos[i][0], pos[i][1], sizes[i][0], sizes[i][1])

    # ② 连线:只朝前(①→②→③→④→⑤a→⑤b)
    edges = [(0, 1, '缺口'), (1, 2, '闸门'), (2, 3, '可选'),
             (3, 4, '10 人以内'), (4, 5, '5 人')]
    for a, b, label in edges:
        ax, ay, aw, ah = box(a)
        bx, by, _bw, _bh = box(b)
        if abs(ay - by) < 1:                                    # 同一行:左→右
            x1_, y1_ = ax + aw, ay + ah / 2
            x2_, y2_ = bx, by + sizes[b][1] / 2
            mx, my = (x1_ + x2_) / 2, y1_ - 9
        elif abs(ax - bx) < 1:                                  # 同一列:上→下
            x1_, y1_ = ax + aw / 2, ay + ah
            x2_, y2_ = bx + sizes[b][0] / 2, by
            mx, my = x1_ + 8, (y1_ + y2_) / 2 + 4
        else:                                                   # 回折行:右→左
            x1_, y1_ = ax, ay + ah / 2
            x2_, y2_ = bx + sizes[b][0], by + sizes[b][1] / 2
            mx, my = (x1_ + x2_) / 2, y1_ - 9
        out.append(f'<line x1="{x1_:.1f}" y1="{y1_:.1f}" x2="{x2_:.1f}" y2="{y2_:.1f}" '
                   f'stroke="#334e68" stroke-width="1.6" marker-end="url(#ag)"/>')
        if label:
            out.append(f'<text x="{mx:.1f}" y="{my:.1f}" font-size="{F_EDGE}" fill="#687b8f" '
                       f'text-anchor="middle">{_esc(label)}</text>')

    # ③ 框与文字：**文字全部居中**（text-anchor=middle，x 取框中心），
    #    并且给每个框加"高亮"——顶部一条与描边同色的高亮带 + 轻投影，
    #    这样一眼看得出这是一张卡片，而不是浮在背景上的几行字。
    out.append('<defs><filter id="card" x="-8%" y="-8%" width="116%" height="120%">'
               '<feDropShadow dx="0" dy="1.5" stdDeviation="1.6" flood-color="#1f2933" '
               'flood-opacity="0.16"/></filter></defs>')
    for i, (num, title, fill, stroke, lines) in enumerate(nodes):
        x, y, w, h = box(i)
        cx = x + w / 2
        # 底板（带投影）
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10" '
                   f'fill="{fill}" stroke="{stroke}" stroke-width="1.6" filter="url(#card)"/>')
        # 顶部高亮条：整张卡片的"抬头"，颜色跟框的语义一致
        out.append(f'<path d="M{x + 10:.1f} {y:.1f} H{x + w - 10:.1f} '
                   f'Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + 10:.1f} '
                   f'V{y + ACCENT_H:.1f} H{x:.1f} V{y + 10:.1f} '
                   f'Q{x:.1f} {y:.1f} {x + 10:.1f} {y:.1f} Z" fill="{stroke}" opacity="0.9"/>')
        # 标题：居中
        ty = y + ACCENT_H + PADY + F_TITLE - 2
        out.append(f'<text x="{cx:.1f}" y="{ty:.1f}" font-size="{F_TITLE}" font-weight="600" '
                   f'fill="{stroke}" text-anchor="middle">{_esc(num + " · " + title)}</text>')
        # 副行：同样居中（等宽字，行距 SUB_H）
        for j, ln in enumerate(lines):
            yy = ty + TITLE_H - 2 + SUB_H * (j + 1)
            out.append(f'<text x="{cx:.1f}" y="{yy:.1f}" font-size="{F_SUB}" fill="#687b8f" '
                       f'text-anchor="middle" font-family="ui-monospace,Menlo,monospace">'
                       f'{_esc(ln)}</text>')

    foot = '每一步都落成文件；下一步只读上一步的产物，不靠人转述。'
    if gate:
        foot += f'　门禁：{gate}'
    out.append(f'<text x="{M}" y="{H - 14}" font-size="{F_FOOT}" fill="#687b8f">{_esc(foot)}</text>')
    out.append('</svg>')
    return '\n'.join(out)

STEP_NAMES = ('1 出初始 JD', '2 定稿', '3 初筛', '4 一面', '5a 短名单', '5b 最终名单')


def jds() -> list[str]:
    return sorted(p.stem for p in (TALENT / 'jd_links').glob('*.yaml'))


def _n(v) -> int:
    """count.excluded 是数字,旧产物里是列表 —— 两种都要能读。"""
    return int(v) if isinstance(v, (int, float)) else len(v or [])


def funnel() -> list[dict]:
    out = []
    for jd in jds():
        sl = yaml.safe_load((TALENT / 'shortlist' / f'{jd}.yaml').read_text(encoding='utf-8')) or {}
        lst = (TALENT / 'shortlist' / f'{jd}.面试名单.yaml')
        tgt = (TALENT / 'shortlist' / f'{jd}.目标名单.yaml')
        picks = (TALENT / 'picks' / f'{jd}.yaml')
        lst_d = yaml.safe_load(lst.read_text(encoding='utf-8')) if lst.is_file() else {}
        tgt_d = yaml.safe_load(tgt.read_text(encoding='utf-8')) if tgt.is_file() else {}
        pk_d = yaml.safe_load(picks.read_text(encoding='utf-8')) if picks.is_file() else {}
        fin = (tgt_d.get('final') or {})
        out.append({
            'jd': jd,
            'kept': len(sl.get('kept') or []),
            'excluded': _n((sl.get('count') or {}).get('excluded')
                           if (sl.get('count') or {}).get('excluded') is not None
                           else len(sl.get('excluded') or [])),
            'interview': len(lst_d.get('selected') or []),
            'shortlist': len(tgt_d.get('selected') or []),
            'final': int(fin.get('count') or 0),
            'judgeable': (pk_d.get('count') or {}).get('judgeable_requirements'),
            'total_req': (pk_d.get('count') or {}).get('total_requirements'),
            'tie_band': (tgt_d.get('cut') or {}).get('tie_band'),
        })
    return out


def gate_line() -> str:
    try:
        proc = subprocess.run([sys.executable, '-m', 'scripts.talent.check_component_catalog'],
                              cwd=str(BACKEND), capture_output=True, text=True, timeout=600)
        out = (proc.stdout or '') + (proc.stderr or '')
        for ln in reversed(out.splitlines()):
            if 'checks ·' in ln:
                return ln.strip()
    except Exception:                                             # noqa: BLE001
        pass
    return '（未跑）'


def phases() -> dict:
    """今天新增的四层：数字全部从产物现算。

    · Phase 0 读 catalog.json（标准目录：分类/组件/要求 + 标准模板字段数）
    · Phase 1 读模板的判据（22 格文本可判 / 18 格需引用）+ 上传件的缺口状态分布
    · Phase 2 读 jd_draft/*.draft.json（客户原文/HR 侧/HR 模拟确认/不适用）
    · 第 3/5 步读 cv_interview 的 review 数与 picks/*.业务面问题.md 数
    """
    cat = json.loads((TALENT / 'catalog.json').read_text(encoding='utf-8')) \
        if (TALENT / 'catalog.json').is_file() else {}
    cov = cat.get('coverage') or {}
    std = cat.get('standard_templates') or {}
    ph0 = {'cats': cov.get('categories'), 'comps': cov.get('components'),
           'reqs': cov.get('requirements'),
           'jd': (std.get('jd') or {}).get('field_count'),
           'cv': (std.get('cv') or {}).get('field_count')}

    # 文本可判 vs 需引用：直接问 Phase 1 的规则表
    try:
        from scripts.talent.check_template_fill import PROBES
        need_cite = sum(1 for v in PROBES.values() if v.get('reqs'))
        text_can = len(PROBES) - need_cite
    except Exception:                                              # noqa: BLE001
        text_can, need_cite = 0, 0
    ph1 = {'text_can': text_can, 'need_cite': need_cite}

    ph2 = {'jds': 0, 'client': 0, 'hr': 0, 'hrmock': 0, 'na': 0}
    for dp in (TALENT / 'jd_draft').glob('*.draft.json'):
        d = json.loads(dp.read_text(encoding='utf-8'))
        t = d.get('tally') or {}
        ph2['jds'] += 1
        ph2['client'] += t.get('客户原文', 0)
        ph2['hr'] += t.get('HR 侧', 0)
        ph2['hrmock'] += t.get('HR 模拟确认', 0)
        ph2['na'] += t.get('不适用', 0)

    reviews = 0
    for f in (TALENT / 'cv_interview').glob('*.yaml'):
        try:
            if (yaml.safe_load(f.read_text(encoding='utf-8')) or {}).get('review'):
                reviews += 1
        except yaml.YAMLError:
            continue
    ph3 = {'reviews': reviews,
           'bq': len(list((TALENT / 'picks').glob('*.业务面问题.md')))}
    return {'ph0': ph0, 'ph1': ph1, 'ph2': ph2, 'ph3': ph3}


def render(facts: dict, rows: list[dict], gate: str, svg_v: str = '') -> str:
    s5, s7, s8, s13 = facts['step5_gates'], facts['step7_states'], facts['step8_evidence'], facts['step13_replay']
    s10, s12, s2 = facts['step10_two_sources'], facts['step12_refusals'], facts['step2_individuals']
    pt = facts['pipeline_truth']
    lib = s5['library_size']
    cites = sum(v['citations'] for v in s5['per_jd'].values())
    client = sum(v['client'] for v in s5['per_jd'].values())
    hr = sum(v['hr'] for v in s5['per_jd'].values())
    _ph = phases()
    ph0, ph1, ph2, ph3 = _ph['ph0'], _ph['ph1'], _ph['ph2'], _ph['ph3']
    L: list[str] = []
    A = L.append

    A('# 招聘流水线 · 总览（演示用）')
    A('')
    A('> 一页讲完：**怎么走完一次招聘**、**每一步业务做什么、技术怎么实现**、**凭什么信结论**。')
    A('> 数字由 `scripts/talent/build_overview.py` 从产物现算，不手写（`--check` 可校验是否过期）。')
    A('')
    A('## 一句话')
    A('')
    A('**客户 JD 上传 → 对 40 格标准模板查缺口 → HR 与业务定稿（缺的格先 mock 满）→ '
      '初筛 + HR 一面补齐 CV 并写评语 → 短名单 ≤10 → 选 5 人给业务面，并附每人一份问题清单。**')
    A('')
    A('## 全流程图')
    A('')
    A(f'![招聘流水线全流程](/api/talent/raw?path=flow.svg{("&v=" + svg_v) if svg_v else ""})')
    A('')
    A('::: details 同样的流程，纯文本版（图片看不清时看这个）')
    A('```')
    A('  ① 上传 JD → 出缺口    ② HR + 业务定稿       ③ 初筛 + HR 一面（必须）')
    A('  ──────────────────    ──────────────────    ─────────────────────────')
    A('  原文抽文本，一字不改   缺的格 mock 满（标来源）  只剔"简历上明确不合格"的')
    A('  对 40 格模板逐格查     逐格等客户/HR 签字        读不到一律留 + 进待核清单')
    A('        │                    │                   一面补齐 CV + 写 HR 评语')
    A('        ▼                    ▼                       │')
    A('  _source/<JD>.txt      定稿(标准40格).md           ▼')
    A('  <JD>.缺口.md                                shortlist/<JD>.yaml + cv_interview')
    A('                                                   │')
    A('  ⑤b 最终 ≤5 + 业务面问题 ← ⑤a 短名单 ≤10 ←     ④ 加面（可选）')
    A('  ────────────────────    ──────────────        ─────────────────')
    A('  门槛 0 不满足           九层证据阶梯排序         跳过不是缺：')
    A('  硬证据 ≥1               切线并列数写进产物       没问的格子记「未知」')
    A('  未知 ≤3 · 附每人的                              不是「不合格」')
    A('  业务面问题清单（A/B/C）')
    A('```')
    A('::: ')
    A('')
    A('**交接关系**：业务交原文 → HR+业务交定稿 → HR 交面试名单与一面记录（含评语）→ '
      'HR+业务交短名单 → 业务+HR 交最终 5 人 + 业务面问题清单 → 用人部门面这 5 人。')
    A('每一步都落成文件；下一步只读上一步的产物，不靠人转述。')
    A('')
    A('> **阶段口径**（2026-11-24 定）：Phase 0 = 标准定义（字段/组件/要求/模板，跟具体 JD 无关）；'
      'Phase 1 = 上传一份 JD、抽原文、出缺口；Phase 2 = HR 与业务定稿；之后才是第 3–5 步的选人。')
    A('')
    A('## 今天新增的四层（数字从产物现算）')
    A('')
    A('| 层 | 产物 | 现算结果 |')
    A('|---|---|---|')
    A(f'| **Phase 0 · 标准定义** | `CATALOG.md` / `catalog.json` | 分类 **{ph0["cats"]}** · 组件 **{ph0["comps"]}**'
      f' · 要求 **{ph0["reqs"]}** · 标准 JD **{ph0["jd"]}** 字段 / CV **{ph0["cv"]}** 字段 |')
    A(f'| **Phase 1 · 上传出缺口** | `jd_docs/<JD>.缺口.md` + `_source/<JD>.txt` | '
      f'四状态（原文/原文·空值/缺/不适用）· 40 格里 {ph1["text_can"]} 格纯文本可判、'
      f'{ph1["need_cite"]} 格原本要逐字引用 |')
    A(f'| **Phase 2 · 定稿（缺的格 mock 满）** | `jd_docs/<JD>.定稿(标准40格).md` | '
      f'{ph2["jds"]} 份 JD 全部 40 格无空格：客户原文 {ph2["client"]} · HR 侧 {ph2["hr"]} · '
      f'**HR 模拟确认 {ph2["hrmock"]}** · 不适用 {ph2["na"]}（每份带「AI 模拟清单」） |')
    A(f'| **第 3/5 步新增产物** | HR 评语 + 业务面问题清单 | HR 评语 **{ph3["reviews"]}** 份'
      f'（模拟，不进判定）· 业务面问题清单 **{ph3["bq"]}** 份（覆盖最终 5 人） |')
    A('')
    A('')
    A('## 现在跑出来的漏斗（五条线）')
    A('')
    A('| JD | 初筛保留 | 排除 | 面试 | 短名单 | 最终 | 可判要求 | 切线并列 |')
    A('|---|---|---|---|---|---|---|---|')
    for r in rows:
        A(f"| {r['jd']} | {r['kept']} | {r['excluded']} | {r['interview']} | {r['shortlist']} | "
          f"**{r['final']}** | {r['judgeable']}/{r['total_req']} | {r['tie_band']} |")
    A('')
    A(f'> 判定说明 **{s7["docs"]}** 份 · 判定格 **{s7["total_cells"]}** 个 · 引用 **{cites}** 条'
      f'（客户 {client} + 我方 HR 侧 {hr}）· 要求库 {lib} 条。')
    A('')
    A('---')
    A('')
    A('## 第 ① 步 · 出初始 JD')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：业务（招聘需求方）。**什么时候**：岗位一开就做。')
    A('- **做什么**：把客户给的职务说明书**原样**交上来。不解释、不润色、不改错别字、不合并同类项。')
    A('- **判断标准**：客户到底写了什么。业务不做"意思大概是这样"的翻译 —— 那一步是第 ② 步、而且要签字。')
    A('- **交付**：一份原始文件 + 一句"这份是哪个岗位"。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 落盘 | `work/talent/jd_links/_source/<JD>.txt`（.doc/.docx/.xlsx 抽平成文本，每行带行号） |')
    A('| 为什么保留原文 | 后面每一条要求都要能**逐字回查**到这里的某一行；原文动了，所有引用立刻作废 |')
    A('| 工具 | `extract_jd` / `llm_draft_jd` 起草引用；`jd_links/_source` 是只读锚点 |')
    A('| 门禁 | 逐字回查：`verbatim` 必须在原文里且 `txt_line` 真的指向那一行（改一个字就红） |')
    A('')
    A('## 第 ② 步 · 定稿（把原文变成闸门）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR + 业务一起。**什么时候**：初筛之前，必须定稿。')
    A('- **做什么**：逐条确认"这句是客户的意思吗"；把客户没写清的地方列成待确认；我方要补的要求（例如到岗周期）必须标明**我方提出**并写依据。')
    A('- **判断标准**：客户原文优先。客户说"优先"就是优先，不许写成"必须"；客户没说阈值，就记"没法判"，**不许替客户定一个数**。')
    A('- **交付**：一张要求清单（每条带客户原话和行号）+ 一份决策账本（谁定了什么、哪天、为什么还没签）。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A(f'| 引用文件 | `jd_links/<JD>.yaml`：{cites} 条引用（客户 {client} + 我方 HR 侧 {hr}），每条带 `verbatim` / `txt_line` / `origin` / `tier` / 阈值 `value` |')
    A(f'| 要求库 | `requirement_library.yaml`（{lib} 条）：阈值算子、数据项、可判性（`assessable`）、阈值口径 |')
    A('| 转正脚本 | `promote_jd`：草稿逐条复核 verbatim 与行号，**任一条对不上就整体拒绝、一个文件都不写** |')
    A('| 决策账本 | `jd_reviews/<JD>.yaml`：粒度/阈值/覆盖三类决定，一律 `signoff: pending` 等业务签字 |')
    A('| 回填参数 | `jd_inputs/<JD>.yaml`：面试人数、短名单区间、`final_max`、业务优先条件 |')
    A('| 门禁 | 引用逐字性、行号真实、HR 侧不许冒充客户原话、带拆分信号的引用必须有粒度决定且账本里有对应条目 |')
    A('')
    A('## 第 ③ 步 · 初筛 + HR 一面（必须）：决定谁值得面，并把 CV 补齐')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR。**什么时候**：定稿之后、打电话之前。')
    A('- **做什么**：从简历池里**只**剔除"简历上明确写着不合格"的人（例如客户写 25~40 岁、简历写 45 岁）。')
    A('- **判断标准**：读不到 ≠ 不合格。凡是拿不准的，一律留在池子里，进**待核清单**，等电话里问。')
    A('- **交付**：一份面试名单（HR 真能打完电话的数量）+ 一份待核清单（按谁问、怎么问写清楚）'
      '+ **补齐的 CV**（每人一份定稿）+ **HR 评语**（这个人怎么样，一句话也要有证据）。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 初筛 | `screen_cv`：只对"简历直接写着"的属性阈值判；算子不是阈值的、推导出来的量、白名单带"等/类"的**都不拿来排除人** |')
    A('| 账要平 | `kept + excluded = pool`，门禁断言；差一个人就说明有人被静默丢掉 |')
    A('| 面试名单 | `pick_interview_list`：九层证据阶梯排序 + 切线 `tie_band`（并列几个人写进产物，名次可读不可读由它决定） |')
    A('| 待核清单 | `open_questions`：按人 × 按条款生成；每条写清谁问、给什么问法 |')
    A('| 一面（必须） | `simulate_hr_round`（演练；真访谈时换成真人记录）：按待核清单把 JD 要的数据问齐，'
      '答案 `basis` 标 `interview` / `simulated` |')
    A('| CV 补齐 | `render_all_cv` → `cv_docs/<人>.定稿.md`（31 字段逐格标来源）+ `index_cv` → '
      '`<JD>.CV清单.md`（含 **HR 评语** 列） |')
    A('| HR 评语 | `mock_hr_comment` → `cv_interview/<人>.yaml` 的 `review`：**不进判定**，只给人读；'
      '每条都要能追到证据（硬证据几项、一面几条、填充度） |')
    A('| 门禁 | **排除必须有硬证据**；待核的人必须还在池里；每条排除都能追到值；'
      'CV 定稿每格必须标来源 |')
    A('')
    A('## 第 ④ 步 · 加面（**可选**）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR / 业务。**什么时候**：第 ③ 步之后，**需要时**才做 —— 这一步不是必须的。')
    A('- **做什么**：对拿不准的人再补一轮（能力举例、加面确认）。'
      '**跳过不是缺**：没问的格子记「未知」，不是「不合格」。')
    A('- **判断标准**：**不问"你觉得他行不行"**，也不打分。只记录：问了什么、他怎么答、能不能举例。')
    A('- **交付**：追加的问答记录（并回 CV 定稿）；没有加面就什么都不用交，流程照样往下走。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A(f'| 记录 | `cv_interview/<候选人>.yaml`：`answers[]` 每条带 `basis`（`interview` 真访谈 / `simulated` 代拟）、`establishes`（坐实了哪条要求的能力项） |')
    A('| 采信规则 | 规则是**数据**：`interview_policy.yaml` 的 `mode`。默认 `real_only` —— 代拟答案不进判定 |')
    A('| 档案 | `render_cv_final` 产出 `cv_docs/<候选人>.定稿.md`：字段全集 + 每格标来源（`resume` / `代拟(模拟)` / `interview`），并写明填充度 |')
    A('| 演练模式 | `simulate_hr_round`：按待核清单 + JD 能力项生成答案，**坐实/否认跟着简历证据走**，不按哈希随机 |')
    A('| 门禁 | 每条答案 `basis` 必须诚实；`establishes` 必须落回某条要求；能力「满足」必须标证据强度 |')
    A('')
    A('## 第 ⑤a 步 · 短名单（谁排前面）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR。**什么时候**：一面做完。')
    A('- **做什么**：把面过的人排一个"够格进下一轮评估"的名单，人数按 HR 定的上限（当前 ≤10）。')
    A('- **判断标准**：**证据多的排前面**（有载体/能核实的证据优先于只有自述），然后才看业务偏好、客户写的"优先"条款、年限、稳定性。')
    A('- **交付**：一份有顺序的名单 + 切线说明（切在第几名、那里是否并列）。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 脚本 | `shortlist_after_interview` → `shortlist/<JD>.目标名单.yaml` 的 `selected` |')
    A('| 证据 | 简历抽到的能力项 ∪ 一面坐实的；按 `component_catalog` 的 `evidence_role` 分硬/软 |')
    A('| 排序 | 九层阶梯：硬证据 → 软证据 → 业务优先条件 → 客户「优先」条款 → 年限 → 稳定性 → 待核项 → 品质岗经历 → 哈希兜底 |')
    A('| 门槛口径 | `REQ-B-MAJOR`（专业）**不进硬门槛**：客户写的是"…等"开区间，且口径未定（DEF-04） |')
    A('| 门禁 | 进名单的人必须面过且在本 JD 面试名单内；人数 ≤ 上限；切线 `tie_band` 必须交代 |')
    A('')
    A('## 第 ⑤b 步 · 最终名单（谁没有硬伤）')
    A('')
    A('### 业务视角')
    A('')
    A('- **谁**：HR + 业务。**什么时候**：短名单之后，送去用人部门面之前。')
    A('- **做什么**：从短名单里取出**送去面试的那 5 个人**。')
    A('- **判断标准**：三条硬条件 —— 客户硬门槛 **0 条不满足**、至少 **1 项硬证据**、未知 **≤3 条**；上限 5 人。**不够 5 个就如实说不够，不硬凑。**')
    A('- **交付**：5 人名单 + 每人一段"为什么是他" + **每人一份业务面问题清单**'
      '（A 能力举例 / B 当面确认未知项 / C 岗位必答）。')
    A('')
    A('### 技术视角')
    A('')
    A('| 项 | 内容 |')
    A('|---|---|')
    A('| 产物 | 同文件的 `final`（含 `unknown_max` / `min_hard` / `max`，门禁照产物复核，不写死数字） |')
    A('| 选人 | `pick_final`：**不重排**，直接按名单顺序取；只补逐人理由与判定说明 |')
    A('| 判定说明 | `explain_rejection` → `verdicts/<JD>/<人>.md|yaml`：每条判定带客户原文、行号、数据项、他的值、阈值、值来源、四态 |')
    A('| 业务面问题 | `business_questions` → `picks/<JD>.业务面问题.md`：每人三段 —— '
      'A 能力项（软证据要举例 / 硬证据当面核对载体）、B 当面确认（判定「未知」格 + 客户门槛「不满足」格，'
      '逐条带客户原话）、**C 岗位必答**。**不生成"你觉得他行不行"这类问题** |')
    A('| 门禁 | 最终名单 ⊂ 短名单、人数 ≤ 上限、**人数明显更少**、每人真的过三条硬条件（从 `rows` 复算，不信自报）、说明不得过期 |')
    A('')
    A('---')
    A('')
    A('## 排序口径：名单是怎么"切"出来的')
    A('')
    A('> 唯一权威就是本节。代码在 `pick_interview_list`（面试名单）与 '
      '`shortlist_after_interview`（短名单/最终名单），两处产物里都写着 `rank_rule` 与 `cut`。')
    A('> **本节与代码不一致时，以代码 + 产物为准**，并回来把本节改掉 —— 文档不能变成第二个真相。')
    A('')
    A('**九个层，前面的决定后面的。** 上一层分不出胜负才看下一层；越靠前越硬，哈希永远在最后。')
    A('')
    A('| 层 | 依据 | 数据来源 | 谁能改 |')
    A('|---|---|---|---|')
    A('| ① | **硬证据项数**（可验证载体：系统/报告/客户审核/图表） | 简历抽取能力项 ∩ JD 要求组件中 `evidence_role: hard`，按**能力**去重 | 系统固定 |')
    A('| ② | **软证据项数**（只能靠陈述） | 同上，`evidence_role: soft` | 系统固定 |')
    A('| ③ | **业务优先规则命中数** | `priority_catalog.yaml` 里用户挑的那几条 | **用户** |')
    A('| ④ | **客户原文「…优先」条款命中数** | JD 中 `verbatim` 含「优先」的条款，判定=满足才计 | 客户原文（自动） |')
    A('| ⑤ | **总年限**（多者前） | 平台计算年限 | 系统固定 |')
    A('| ⑥ | **稳定性：平均在职年限** | `hr_facts.avg_tenure_years`（从工作段算出） | 系统固定 |')
    A('| ⑦ | **待核项数**（少者前） | `open_questions/<JD>.yaml` | 系统固定 |')
    A('| ⑧ | **品质岗经历强度**（有 > 待核 > 读不出 > 无） | `cv_quality.verdict` | 系统固定；**本 JD 不要求品质经历时这一层关闭** |')
    A('| ⑨ | **`sha256(候选人 id)`** | — | 系统固定；**不按姓名/文件名排** |')
    A('')
    A('### 只能动的三个旋钮')
    A('')
    A('| 旋钮 | 命令 | 影响 |')
    A('|---|---|---|')
    A('| 人数 | `set_target --jd <JD> --interview N --shortlist M~K` | 切几刀 |')
    A('| 业务优先规则 | `priorities --jd <JD> --select 2 5` | 只影响第 ③ 层 |')
    A('| 清空规则 | `priorities --jd <JD> --clear` | 第 ③ 层归零，回到纯证据排序 |')
    A('')
    A('**其余七层不能靠对话改。** 要改先改政策，改完同时更新本节、代码里的 `rank_rule`、'
      '以及 agent prompt —— 三处必须一致。')
    A('')
    A('### "他的名次能不能读"——看 `cut.tie_band`')
    A('')
    A('```yaml')
    A('cut:')
    A('  position: 10          # 切在第几位')
    A('  tie_band: 1           # 这个位置上有几个人排序键完全相同')
    A('  hash_decided: false   # 名次是否由哈希决定')
    A('  note: 切线唯一 —— 名次可读')
    A('```')
    A('')
    A('| tie_band | 含义 | 汇报怎么说 |')
    A('|---|---|---|')
    A('| **1** | 切线唯一 | 名次可读，可以说"他排第 N" |')
    A('| 2~3 | 小并列 | "这几个人键相同，谁上都行，按哈希排" |')
    A('| >3 | 大片并列 | "**切线落在并列区内，名次不可读**；集合有意义，顺序没有" |')
    A('')
    A('**不许**在 `tie_band > 1` 时说"他更合适"—— 那是把哈希说成判断。')
    A('当前五条线的 `tie_band` 见上面漏斗表的「切线并列」列。')
    A('')
    A('### 为什么是这个顺序（设计理由，不是偏好）')
    A('')
    A('1. **证据在最前**：能不能干这个活是第一位，偏好不能压过证据。'
      '（曾把用户规则放最前，结果"规则全中但零能力证据"的人排到第 5 —— 已改。）')
    A('2. **客户的「优先」在第 ④**：排用户规则之后，因为用户规则是本轮招聘的临时取舍，客户原文是长期口径；两者都是"偏好"，不是"资格"。')
    A('3. **年限在稳定性之前**：客户写了「N 年以上经验」，这是客户口径；稳定性是我方推断。')
    A('4. **待核项数是成本指标**：信息完整的人先面能省钱，但**不代表他更合适**。')
    A('5. **哈希兜底而不是 id**：按 id 排等于按文件名/姓氏排，是一种看不见的偏差。')
    A('')
    A('### 已知偏差（必须一起说）')
    A('')
    A('| 层 | 偏差 | 方向 |')
    A('|---|---|---|')
    A('| ① ② | 用的是**简历抽取词表**，偏向"简历写得细的人"（DEF-01） | 会漏判能力：说不清的人被排后 |')
    A('| ④ | 客户只写"专业优先"这类弱条款时，该层常命中 0 人 | 该层失效，不产生偏差也不起作用 |')
    A('| ⑤ | 年限**读不出来**的排最后 —— 这是**排序口径，不是判他不合格** | 信息不全的人被排后 |')
    A('| ⑥ | 平均在职年限是我方推断量，客户原文没要求 | 可能压掉"跳槽多但能力强"的人 |')
    A('')
    A('### 怎么验证这份口径没走样')
    A('')
    A('```bash')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.pick_interview_list --jd <JD>')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.shortlist_after_interview --jd <JD>')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog')
    A('```')
    A('')
    A('门禁会核：`rank_rule` 必须是 **9 层**、必须有 `cut` 段、`tie_band` 必须是整数、'
      '面试名单人数等于 `interview_target`、账必须平（`kept + excluded = pool`）、'
      '最终名单必须是短名单真子集且明显更少。**同输入重跑必须逐字节相同** —— 不确定就不算"可复算"。')
    A('')
    A('## 四个设计决定（演示时最该讲的四句）')
    A('')
    A(f'**① 四种判定状态永不合并。** 满足 / 不满足 / **未知**（材料里读不到）/ **不可判**（这条要求没有数据项）。')
    A(f'当前 {s7["total_cells"]} 格：满足 {s7["counts"]["满足"]}、不满足 {s7["counts"]["不满足"]}、'
      f'**未知 {s7["counts"]["未知"]}**、不可判 {s7["counts"]["不可判"]}。把「未知」当「不满足」= 把"我们没读到"判成"他不行"。')
    A('')
    A(f'**② 能力「满足」要标证据档次。** 组件目录 {s8["components"]} 个，已标 {s8["roles"]["hard"]} 硬 / '
      f'{s8["roles"]["soft"]} 软；**还有 {s8["roles"]["未声明"]} 个没标**（待办，演示时如实说）。')
    A('')
    A('**③ 本体给事实、LLM 给判定，冲突分四类。** A 数据值 / B 阈值 / D 不可判 → 跟本体；**C 判定 → 不进结论、进复议**。')
    A('依据：只看本体 7/31，本体给料 + LLM 判 15/31（31 格人工核对过的基准）。')
    A('')
    A(f'**④ 「可复算」= 重放，不是重调。** {s13["run_pairs"]} 对存档里 {s13["same_verdicts"]} 对结论一致'
      f'（按格 {s13["cells_same"]}/{s13["cells_compared"]}）；再问一次模型会漂移，那不叫可复算。')
    A('')
    A('## 凭什么信它（机器检查）')
    A('')
    A('| 检查 | 挡什么 | 在哪 |')
    A('|---|---|---|')
    A('| 逐字回查 | 客户原文改一个字，引用立刻对不上行 | 门禁 / `verify_jd_report` |')
    A('| 排除必须有硬证据 | 不许拿"读不到"排除人 | 门禁 |')
    A('| 两道闸 | 最终名单必须是短名单真子集且明显更少 | 门禁 |')
    A('| 判定说明不过期 | 输入一变（JD/阈值/简历事实/一面记录），旧说明立刻红 | 门禁 |')
    A('| 教程数字不过期 | 教程里每个数字都由脚本现算，手改一个数就红 | `check_tutorial` |')
    A('')
    A(f'当前门禁：**{gate}**')
    A('')
    A('## 现在的状态（演示时必须同时说的部分）')
    A('')
    A(f'- **一面数据全是代拟**：{pt["interview_docs"]} 份记录里真访谈 **{pt["real_interview_docs"]}** 份 —— '
      '所以每份名单只能当演练看，不能当录用依据。')
    A(f'- **一个数两个来源还没定真源**：{s10["candidates"]} 人里 {s10["differ"]} 人技能集合两边不一致'
      f'（ABox 独有 {s10["only_abox"]}、LLM 独有 {s10["only_llm"]}）。')
    A(f'- **三种按名拒绝**：没 JD 的岗位 {s12["roles_without_jd_candidates"]} 人、没数据项的要求 '
      f'{len(s12["requirements_without_data_item"])} 条、全库无人命中的组件 {len(s12["components_zero_holder"])} 个。')
    A('- **还有 5 个 JD 停在客户原文**（业务助理 / 人资专员 / 工程文员 / 招聘专员 / 管理课长），有草稿未转正。')
    A(f'- **本体 ABox 是 {s2["candidates"]} 人的快照**，当前可用 OCR 文本 {facts["step1_records"]["source_files"]} 份，差的那几份是后来的清洗。')
    A('')
    A('## 在哪里看、怎么复算')
    A('')
    A('| 想看什么 | 打开哪里 |')
    A('|---|---|')
    A('| 一个 JD 的全部产物 | Talent 侧栏选 JD → 按层展开 1 → 5 |')
    A('| 名单 + 每人的证据 | `5 目标名单 · 人读` → 表格每行「看 CV」读完整档案 |')
    A('| 判定说明 | `5 判定总览` → 点人，每条带客户原文/行号/值来源 |')
    A('| 这套流程怎么来的 | `教程 v2 · 从记录到判定`（14 步，每步一个真数字 + 一个能变红的反证） |')
    A('| 跑第 5 步 | 文档页右上角「跑第 5 步」（白名单端点 + 跨进程锁，跑完自动重读） |')
    A('')
    A('```bash')
    A('cd backend && set -a && source ../.env; set +a')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.build_overview          # 重新生成本页')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.build_overview --check  # 是否过期')
    A('env -u PGPORT .venv/bin/python -m scripts.talent.check_component_catalog # 门禁')
    A('```')
    A('')
    return '\n'.join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-gate', action='store_true')
    ap.add_argument('--check', action='store_true', help='只校验是否最新')
    args = ap.parse_args()

    facts = json.loads(json.dumps(TF.collect(), ensure_ascii=False))
    rows = funnel()
    gate = '（本次未跑；见 STATUS 最近一次记录）' if args.skip_gate else gate_line()
    svg = flow_svg(gate)
    import hashlib as _hl
    svg_v = _hl.sha256(svg.encode()).hexdigest()[:8]
    md = render(facts, rows, gate, svg_v)
    (TALENT / 'flow.svg').write_text(svg, encoding='utf-8')

    if args.check:
        old = DEST.read_text(encoding='utf-8') if DEST.is_file() else ''
        same = old.strip() == md.strip() or (args.skip_gate and old.strip().split('\n当前门禁：')[0]
                                            == md.strip().split('\n当前门禁：')[0])
        print('OVERVIEW.md 是最新的' if same else 'OVERVIEW.md 已过期 —— 重跑 build_overview')
        return 0 if same else 1
    DEST.write_text(md, encoding='utf-8')
    print(f'写出 {DEST.relative_to(ROOT)} · {len(md.splitlines())} 行 · 图 flow.svg · 门禁 {gate}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

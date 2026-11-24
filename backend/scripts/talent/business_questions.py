#!/usr/bin/env python3
"""给第 5 步选出的 5 个人，生成**业务面（用人部门面）的问题清单**。

## 为什么要有这一份

HR 那通电话（第 3 步·必须）负责**把数据问齐**：到岗、通勤、薪资、在职时长。
业务面负责的是**另两件事**，混在一起问就是浪费业务的时间：

1. **能力项要举例** —— 简历/一面里只有自述的能力项（软证据），必须现场让他讲一段具体做法；
2. **未知项要落地** —— 判定里还挂着「未知」的格子，要业务面当面确认（不是 HR 电话能问清的）。

所以每人的问题分三段：

    A 必问（能力举例）   来自 evidence_role=soft 的能力项 + 判定里「满足但只有自述」
    B 待确认（未知项）   来自该人判定里的「未知」格（问不到就一直是未知，别写在简历上装成有）
    C 岗位必答（客户原文）来自客户 JD 的硬要求（如 8D/CPK/客户验厂），统一问法

**不许生成"你觉得他行不行"这种问题** —— 那不是数据，是印象（OVERVIEW 第 ④ 步的红线）。

产物：`work/talent/picks/<JD>.业务面问题.md`

用法:
    python -m scripts.talent.business_questions --jd 品质经理
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
TALENT = ROOT / 'work' / 'talent'
SHORTLIST = TALENT / 'shortlist'
PICKS = TALENT / 'picks'
VERDICTS = TALENT / 'verdicts'
CV_FACTS = TALENT / 'cv_facts.json'
NAMES = TALENT / 'fake_names.yaml'


EDU = {1: '初中', 2: '高中/中专', 3: '大专', 4: '本科', 5: '硕士', 6: '博士'}


def _names() -> dict:
    try:
        d = yaml.safe_load(NAMES.read_text(encoding='utf-8')) or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for k, v in (d.get('names') or {}).items():
        out[str(k)] = str(v.get('name')) if isinstance(v, dict) else str(v)
    return out


def _verdict_cells(jd: str, cid: str) -> dict:
    """某人的判定四态（verdicts/<JD>/<人>.yaml）。

    真实文件名是候选人 id（含 cand_ 前缀），另一处落盘规则去掉前缀 —— 两个都试。
    """
    for name in (f'{cid}.yaml', f"{str(cid).replace('cand_', '')}.yaml"):
        p = VERDICTS / jd / name
        if p.is_file():
            return yaml.safe_load(p.read_text(encoding='utf-8')) or {}
    return {}


def build(jd: str) -> str:
    tgt_p = SHORTLIST / f'{jd}.目标名单.yaml'
    tgt = yaml.safe_load(tgt_p.read_text(encoding='utf-8')) or {}
    final = list((tgt.get('final') or {}).get('ids') or [])
    rows = {r.get('candidate'): r for r in (tgt.get('rows') or [])}
    names = _names()
    facts = json.loads(CV_FACTS.read_text(encoding='utf-8')) if CV_FACTS.is_file() else {}

    L = [f'# {jd} · 业务面问题清单（最终 {len(final)} 人）', '',
         '> 用途：业务（用人部门）面这 5 个人时照着问。HR 那通电话（第 3 步）已经把数据问齐，',
         '> 这一份只问**两件事**：能力项让他讲一段具体做法；判定里还「未知」的格子当面落地。',
         '> **不问"你觉得他行不行"** —— 那不是数据，是印象。', '']
    for i, cid in enumerate(final, 1):
        r = rows.get(cid) or {}
        nm = names.get(cid, cid)
        v = _verdict_cells(jd, cid)
        known = (facts.get(cid) or {})
        L += [f'## {i}. {nm}', '',
              f'- 判定：满足 **{r.get("满足")}** / 不满足 **{r.get("不满足")}** / 未知 **{r.get("未知")}** · '
              f'硬证据 {r.get("hard_hits")} · 软证据 {r.get("soft_hits")} · 待核 {r.get("n_ask")}',
              f'- 身份：{EDU.get(r.get("edu"), r.get("edu") or "学历未知")} · '
              f'{r.get("years") or "年限未知"} 年经验 · '
              f'一面 {"模拟" if r.get("iv_real") in (0, None) else "真"} '
              f'{r.get("iv_sim") or r.get("iv_real") or 0} 条', '']

        # A 必问：软证据的能力项（要举例）
        # 能力项：硬证据（有载体）要复核、软证据（只有自述）要举例；简历里一条都没有时退回 JD 硬要求
        hard_items = [x for x in (r.get('hard_items') or []) if isinstance(x, str)]
        soft_items = [x for x in (r.get('soft_items') or []) if isinstance(x, str)]
        L.append('**A. 能力项（必问）**')
        L.append('')
        if soft_items:
            L.append('*软证据 —— 只有自述，必须让他讲一段具体做法：*')
            L.append('')
            for it in soft_items[:5]:
                L.append(f'- 「{it}」：请他讲**最近一次**的具体做法 —— 什么产品、他负责哪一步、'
                         f'结果用什么数字衡量。讲不出细节就记「只有自述」。')
        if hard_items:
            L.append('')
            L.append('*硬证据 —— 简历里提到载体，当面核对载体是否真由他做：*')
            L.append('')
            for it in hard_items[:5]:
                L.append(f'- 「{it}」：让他拿出那份报告/记录（8D、CPK 报表、验厂不符合项闭环），'
                         f'并说清他在里面的角色。')
        if not hard_items and not soft_items:
            L.append('- 简历里没有可举的能力证据 → 按 C 段逐条问，答不上就记「未知」。')
        L.append('')

        # B 待确认：判定里「未知」的格 + 客户门槛里「不满足」的格（业务要知道他差在哪）
        unknown, failed = [], []
        for cell in (v.get('rows') or []):
            if not isinstance(cell, dict):
                continue
            label = (cell.get('name') or cell.get('requirement') or cell.get('data_item') or '')
            st = str(cell.get('state') or '')
            if st == '未知':
                unknown.append((label, cell.get('why') or '简历里读不到',
                                cell.get('threshold'), cell.get('client_text')))
            elif st == '不满足':
                failed.append((label, cell.get('value'), cell.get('threshold'),
                               cell.get('client_text'), cell.get('why')))
        L.append(f'**B. 当面确认（判定「未知」{len(unknown)} 项'
                 + (f' · 客户门槛「不满足」{len(failed)} 项' if failed else '') + '）**')
        L.append('')
        if unknown:
            for label, why, thr, ctext in unknown[:8]:
                L.append(f'- {label}（客户要求：{thr or "—"}｜原文「{(ctext or "")[:24]}」）：'
                         f'{why} → 当面问清；答不上就保持「未知」，别当成"没有"。')
        if failed:
            for label, val, thr, ctext, why in failed[:6]:
                L.append(f'- ⚠ {label}：他的值是 {val}，客户要求是 {thr}'
                         f'{"（客户门槛，已挡人）" if label else ""} —— 已判「不满足」；'
                         f'若这条只是举例/开放口径（原文「{(ctext or "")[:20]}」），业务要判断它是否真该挡人。')
        if not unknown and not failed:
            L.append('- 没有未知项、也没有客户门槛不满足：数据是齐的，只问 A 段能力举例即可。')
        L.append('')

        # C 岗位必答：客户原文的硬要求（从 requirement_library 里带"客户原文"的来源）
        L.append('**C. 岗位必答（客户原文的硬要求）**')
        L.append('')
        L.append('- 线束/连接器产品：做过哪类产品、哪个工序、什么体系（IATF16949 / ISO9001）。')
        L.append('- 品质工具：现场给一组数据，让他说 8D 的 D4 会怎么写；CPK 怎么算、多少算够。')
        L.append('- 客户验厂：最近一次接待的是哪家客户、验的是哪几条、他在里面做什么。')
        L.append('')
    PICKS.mkdir(parents=True, exist_ok=True)
    p = PICKS / f'{jd}.业务面问题.md'
    p.write_text('\n'.join(L), encoding='utf-8')
    return str(p.relative_to(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--jd', required=True)
    args = ap.parse_args()
    print('写出', build(args.jd))
    return 0


if __name__ == '__main__':
    sys.exit(main())

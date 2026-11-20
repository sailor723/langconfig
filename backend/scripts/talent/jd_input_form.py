#!/usr/bin/env python3
"""把定稿里「JD 未写」的字段,变成一张**可填写的回填表** —— 不是一句"待客户补"。

为什么要分级:29 个空白字段里,有的不填这个岗就招不了人(班制、工作环境),
有的不填只是归档不完整(文件编号、核准人)。**混在一张表里问,客户会全都不填。**

三级影响:
    A 阻断  不填 → 这个岗的需求描述不完整,候选人无法自评,匹配结果会误导
    B 解释  不填 → 匹配能算,但解释不了"为什么这个岗要这样的人"
    C 归档  不填 → 只影响文档完整性,不影响招聘判断

用法:
    python -m scripts.talent.jd_input_form --jd 品质经理
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DOCS = ROOT / "work" / "talent" / "jd_docs"

#: 字段 → (影响级别, 为什么需要, 建议填法)
SPEC = {
    "S1.02": ("C", "归档用", "例:QC-JD-2026-003"),
    "S1.05": ("C", "归档用", "例:核准 张三 / 审核 李四 / 制订 王五"),
    "S1.09": ("B", "跨岗比较与外部标准对齐需要它", "人社部《职业分类大典》6-08-xx-xx"),
    "S1.10": ("B", "职级决定薪酬带宽与晋升路径", "例:P6 / 5职等"),
    "S5.01": ("B", "作业明细整段为空 —— 这是JD里信息量最大的一块(全批占73%字数)",
              "逐条列出:序号 / 内容 / 频次"),
    "S5.02": ("B", "同上", "例:1. 每日核对来料检验记录"),
    "S5.03": ("A", "不知道一件事一天做几次,就无法判断这个岗的真实负荷", "每日 / 每周 / 每月 / 偶发"),
    "S5.04": ("A", "时长决定人力编制,也决定候选人能不能接受", "例:约 30 分钟/次"),
    "S5.05": ("B", "2026年新增字段:这项工作能否被工具替代,直接决定岗位是否长期存在",
              "是 / 部分 / 否"),
    "S5.06": ("B", "操作标准流程是培训与考核的依据", "例:接异常→到现场→协调→跟进→回复"),
    "S5.07": ("C", "关联表单决定系统权限与数据归属", "例:来料检验表 / 品质异常单"),
    "S6.01": ("A", "工作地点决定通勤半径 —— 制造业招聘的第一道筛子", "例:东莞石排厂区 / 需驻厂"),
    "S6.02": ("A", "班制决定候选人能否接受(白班/两班倒/三班倒)", "白班 / 两班倒 / 三班倒"),
    "S6.03": ("A", "工时与加班情况是候选人最关心的一项", "例:8小时,月加班约40小时"),
    "S6.04": ("A", "环境(噪音/粉尘/温度)是这个厂区最现实的约束", "例:车间噪音80dB,需长时站立"),
    "S6.05": ("B", "体力要求影响性别与年龄的限制是否能站住脚", "例:需搬抬15kg"),
    "S6.06": ("C", "出差频次", "例:每月1次,省内"),
    "S6.07": ("C", "劳保用品", "例:耳塞/手套/工衣"),
    "S7.03": ("C", "归档用", "例:2026-11-01"),
    "S7.04": ("C", "归档用", "例:2026-12-31"),
    "S7.05": ("B", "招几个决定名单要多长", "例:2人"),
    "S7.06": ("C", "背景信息", "例:扩编 / 替补"),
    "S7.07": ("C", "渠道影响后续发布", "例:智通 / BOSS直聘"),
    "S8.01": ("A", "保密要求属于 G 维合规约束 —— 不填就判不了,而这一条常是硬性的",
              "例:需签保密协议"),
    "S8.02": ("A", "同上", "例:需提供无犯罪记录证明"),
    "S8.03": ("C", "竞业限制", "例:不涉及"),
    "S8.04": ("B", "用工类型(正式/派遣/外包)决定合同与社保", "正式 / 派遣"),
    "S8.05": ("B", "试用期长度", "例:3个月"),
    "S8.06": ("B", "社保缴纳", "例:五险一金"),
}

LEVEL_MEAN = {"A": "阻断 —— 不填则需求不完整、匹配会误导",
              "B": "解释 —— 匹配能算,但解释不了为什么",
              "C": "归档 —— 只影响文档完整性"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", default="品质经理")
    args = ap.parse_args()

    f = DOCS / f"{args.jd}.fields.json"
    if not f.is_file():
        print(f"先跑 render_jd_final --jd {args.jd}")
        return 2
    doc = json.loads(f.read_text(encoding="utf-8"))
    fields = doc["fields"]

    missing = [(c, v) for c, v in fields.items() if v["status"] == "JD 未写"]
    # 「归纳/提案」已从正文挪到附录 F,不再出现在字段状态里 —— 从 proposals 读
    proposals = doc.get("proposals") or []
    prop = [({"label": x["label"]}, ) for x in []]
    derived = [({"label": x["label"]}, ) for x in []]

    by_level = {"A": [], "B": [], "C": []}
    for c, v in missing:
        lvl = SPEC.get(c, ("B", "", ""))[0]
        by_level[lvl].append((c, v))

    L = []
    A = L.append
    A(f"# {args.jd} · 定稿待补清单")
    A("")
    A(f"定稿:`{args.jd}.定稿.md`。本文只列**需要你输入**的部分 —— "
      f"共 {len(missing)} 个空字段、{len(prop)} 项待拍板。")
    A("")
    A("按影响分三级。**A 级不填,这个岗的需求描述就是不完整的**,建议优先处理。")
    A("")
    A("| 级别 | 字段数 | 含义 |")
    A("|---|---|---|")
    for lvl in ("A", "B", "C"):
        A(f"| **{lvl}** | {len(by_level[lvl])} | {LEVEL_MEAN[lvl]} |")
    A("")

    for lvl in ("A", "B", "C"):
        if not by_level[lvl]:
            continue
        A(f"## {lvl} 级 · {LEVEL_MEAN[lvl]}")
        A("")
        A("| 码 | 字段 | 为什么需要 | 建议填法 | 填写 |")
        A("|---|---|---|---|---|")
        for c, v in by_level[lvl]:
            _, why, how = SPEC.get(c, ("B", v.get("note") or "", ""))
            A(f"| {c} | {v['label']} | {why} | {how} | ______ |")
        A("")

    if proposals:
        A("## 我方建议(原文没有,需你确认或拍板)")
        A("")
        A("| 码 | 字段 | 我方建议 | 推导依据 | 需要你做什么 |")
        A("|---|---|---|---|---|")
        for x in proposals:
            act = ("确认归纳对不对" if x["code"] in ("S2.01", "S4.03")
                   else "选哪几项、目标值定多少" if x["code"] == "S2.02"
                   else "是否等权;若不等权,各条占比")
            A(f"| {x['code']} | {x['label']} | {str(x['value'])[:60]} | {x['basis'][:50]} | {act} |")
        A("")
        A("> 这些不是客户原文。它们放在附录里,就是为了让你能直接反驳。")
        A("")
    if False:
        A("## 旧占位")
        A("")
        A("| 码 | 字段 | 我们的建议值 | 要你定什么 |")
        A("|---|---|---|---|")
        for c, v in prop:
            if c == "S2.02":
                A(f"| {c} | {v['label']} | {v['value']} | 选哪几个作为考核指标、目标值定多少 |")
            elif c == "S4.02":
                A(f"| {c} | {v['label']} | {v['value']} | 是否等权;若不等权,各条占比 |")
            else:
                A(f"| {c} | {v['label']} | {v['value']} | 确认 |")
        A("")

    if derived:
        A("## 已由原文归纳(供你复核,不需填写)")
        A("")
        A("| 码 | 字段 | 归纳结果 | 依据 |")
        A("|---|---|---|---|")
        for c, v in derived:
            A(f"| {c} | {v['label']} | {(v['value'] or '')[:60]} | {v['note']} |")
        A("")
        A("> 这两项**不需要你从零写**,只要确认归纳得对不对。若不对,指出来我们改 —— "
          "它们都是从你已有的职责条目推出来的。")
        A("")

    A("## 回填方式")
    A("")
    A("把上表「填写」一列填好后,直接改 `work/talent/jd_links/` 下对应的 yaml,或告诉我要改哪个字段。")
    A("填进来的值会走同一条门禁:有出处的标「有值」,没出处的进「提案」。")
    A("")

    out = DOCS / f"{args.jd}.待补清单.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"写出 {out.relative_to(ROOT)}  {len(L)} 行")
    print(f"  空字段 {len(missing)}(A {len(by_level['A'])} · B {len(by_level['B'])} · "
          f"C {len(by_level['C'])}) · 待拍板 {len(prop)} · 已归纳 {len(derived)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

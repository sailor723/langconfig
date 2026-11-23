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
import yaml

from scripts.talent.jd_template_loader import load as load_template, role_of
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DOCS = ROOT / "work" / "talent" / "jd_docs"
LINKS = ROOT / "work" / "talent" / "jd_links"
TEMPLATE = ROOT / "work" / "talent" / "jd_template.yaml"
SHORTLIST = ROOT / "work" / "talent" / "shortlist"

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




def _template_fields(jd: str) -> tuple[dict[str, dict], list[str], str]:
    """按岗位类别取模板 → `(by_code, not_applicable, role)`。

    和 `render_jd_final` 用**同一个** loader:两份脚本各写一套合并逻辑,迟早有一处忘记
    `inherits`,于是同一份 JD 在两个脚本里字段集不同 —— 上一轮 render(42)与 input_form(29)
    的分叉就是这么来的。
    """
    link_f = LINKS / f"{jd}.yaml"
    if not link_f.is_file():
        return {}, [], ""
    role, _ = role_of(yaml.safe_load(link_f.read_text(encoding="utf-8")) or {})
    if role is None:
        return {}, [], ""
    tpl = load_template(role)
    return tpl["by_code"], tpl["not_applicable"], role


def _unused_template_fields() -> dict[str, dict]:
    """读正式模板 `jd_template.yaml` → {码: {level, owner, why, how, shape, label}}。

    为什么要从数据读:这份模板原先有两份**代码字面量**(本文件的 SPEC 29 条 +
    render_jd_final 的段落字符串 42 条),结果 13 个字段在回填表里「为什么需要 / 建议填法」
    两列是空的 —— 业务方看到的就是空格子,而 A 级归责只能靠 agent 猜。
    模板变成数据以后,42 条都有 level/owner/why/how,还多一列「谁填」。
    """
    if not TEMPLATE.is_file():
        return {}
    doc = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8")) or {}
    out: dict[str, dict] = {}
    for sec in doc.get("sections") or []:
        for f in sec.get("fields") or []:
            code = str(f.get("code") or "").strip()
            if code:
                out[code] = {**f, "section": sec.get("code"), "section_title": sec.get("title")}
    return out


def _undefined_statements(jd: str) -> list[dict]:
    """读 `jd_links/<JD>.yaml` 里登记的 undefined_statements。

    读不到就返回空 —— 这个字段是本轮才加进约定的,旧 JD 没有它,不该因此报错。
    """
    f = LINKS / f"{jd}.yaml"
    if not f.is_file():
        return []
    try:
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    return doc.get("undefined_statements") or []



def _escalations(jd: str) -> list[dict]:
    """第 3 步发现「客户写的门槛」与「候选人池」冲突时,把它提成一条待客户拍板的事项。

    为什么放在待补清单里:这是**客户要做的决定**,不是我们的判断。而"要不要放宽门槛"
    如果只写在短名单报告里,HR 转给客户时就丢了。所以它必须出现在客户真正会填的那份表上。

    数据来源:shortlist/<JD>.yaml 的 `quality_gate.blocked_by_other_requirements`
    —— 做过品质、但被另一条要求挡掉的人。**门槛本身一个字都不改**,只提出问题。
    """
    f = SHORTLIST / f"{jd}.yaml"
    if not f.is_file():
        return []
    try:
        sl = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    gate = sl.get("quality_gate") or {}
    blocked = gate.get("blocked_by_other_requirements") or []
    if not blocked:
        return []
    link_f = LINKS / f"{jd}.yaml"
    verbs = {}
    if link_f.is_file():
        for c in (yaml.safe_load(link_f.read_text(encoding="utf-8")) or {}).get("citations") or []:
            verbs[c.get("requirement")] = c.get("verbatim")
    by_req = {}
    for x in blocked:
        for b in x.get("blocked_by") or []:
            by_req.setdefault(b["requirement"], []).append((x, b))
    out = []
    for rid, items in by_req.items():
        best = max(items, key=lambda it: (len(it[0]["quality"].get("hard") or []),
                                          it[0]["quality"].get("months") or 0))
        out.append({
            "requirement": rid,
            "verbatim": verbs.get(rid) or "",
            "n": len(items),
            "sample": best[0]["candidate"],
            "evidence": best[0]["quality"],
            "why": best[1].get("why", ""),
        })
    return out


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

    tpl, na_codes, role = _template_fields(args.jd)
    if not tpl:
        print(f"NOT RUN — {args.jd}:岗位类别未定,先用 jd_templates 定 role_type 再出回填表")
        return 3

    def meta(code: str) -> dict:
        """一个字段的 level/owner/why/how。模板优先,SPEC 兜底。"""
        m = tpl.get(code)
        if m:
            return m
        lvl, why, how = SPEC.get(code, ("B", "", ""))
        return {"level": lvl, "why": why, "how": how, "owner": ""}

    na_set = set(na_codes)
    by_level = {"A": [], "B": [], "C": []}
    for c, v in missing:
        if c in na_set:
            continue          # 本版不适用 —— 不该出现在"待你填"的清单里
        by_level[meta(c)["level"]].append((c, v))

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
        A("| 码 | 字段 | 谁填 | 为什么需要 | 建议填法 | 填写 |")
        A("|---|---|---|---|---|---|")
        OWNER_CN = {"business": "业务方", "hr": "HR"}   # 客户就是业务方 —— 没有第三个角色
        for c, v in by_level[lvl]:
            m = meta(c)
            why = m.get("why") or v.get("note") or ""
            how = m.get("how") or ""
            who = OWNER_CN.get(str(m.get("owner") or ""), "—")
            A(f"| {c} | {v['label']} | {who} | {why} | {how} | ______ |")
        A("")

    # 客户**自己说还没定**的句子。放在最前面(比 A 级还靠前):这些不是我们猜出来的空白,
    # 是客户亲口承认的空白 —— 问起来最该先问,也最容易被写成"客户没说"而漏掉。
    undefined = _undefined_statements(args.jd)
    if undefined:
        A("## 客户自己说「还没定」的")
        A("")
        A("| 原文行 | 原文 | 看起来对应什么 | 要问客户什么 | 填写 |")
        A("|---|---|---|---|---|")
        for x in undefined:
            A(f"| {x.get('txt_line')} | {x.get('text', '')} | {x.get('likely_field') or '未知(原文没有标签)'} "
              f"| 这一项现在有没有定?没定的话计划什么时候定 | ______ |")
        A("")
        A(f"> 共 {len(undefined)} 条。来源是 `jd_links/{args.jd}.yaml` 的 `undefined_statements` ——")
        A("> 客户亲口承认的空白,比我们猜出来的空白可信得多,所以单独列在最前面。")
        A("")

    # ── 需客户拍板:门槛与候选人池的冲突(数据来自第 3 步)
    esc = _escalations(args.jd)
    if esc:
        A("## ⚠ 需客户拍板:门槛与候选人池的冲突")
        A("")
        A("第 3 步跑完短名单时发现:**做过目标岗位的人,被客户写的硬门槛挡住了**。")
        A("门槛是客户原话(逐字可回查),**我方一个字没改**,只把冲突提出来请客户定。")
        A("")
        A("| 客户写的门槛 | 挡住几人 | 最典型的一个 | 他的证据 |")
        A("|---|---|---|---|")
        for e in esc:
            ev = e["evidence"]
            A(f"| 「{e['verbatim']}」 | {e['n']} | {e['sample'].replace('cand_','')} | "
              f"{ev.get('kind')}档 "
              + (f"{ev.get('months')} 月" if ev.get("months_known") else "起止未读到(不按月判)")
              + f"「{ev.get('title','')[:14]}」"
              f"{','.join(ev.get('hard') or [])} |")
        A("")
        A("**请客户在三种处理里选一个**:")
        A("")
        A("1. **维持原门槛** —— 那本岗位本轮可面人数会很少,并建议补采该岗位的简历")
        A("2. **放宽门槛**(如年龄 25~40 → 45) —— 请给出新数字,我们按新数字重跑")
        A("3. **改为按经验判** —— 该条不再作为排除条件,只在匹配里参考")
        A("")

    # 我方填补的格子:客户没写、我们按依据填了 —— 交出去之前必须有人点头
    ours_rows = [(c, v) for c, v in fields.items()
                 if not c.startswith("dim_") and v.get("status") == "我方填补"]
    need_ok = [(c, v) for c, v in ours_rows if "须客户确认" in str(v.get("note") or "")]
    if ours_rows:
        A("## 我方填补的字段(客户没写,交了这份就要请人确认)")
        A("")
        A(f"共 **{len(ours_rows)}** 条,其中 **{len(need_ok)}** 条标了「须客户确认」。"
          "这些不是客户原话,是我们按行业惯例 + 这份 JD 的内容填的;依据见每条说明。")
        A("")
        A("| 码 | 字段 | 我方填的值 | 依据 | 必须确认 |")
        A("|---|---|---|---|---|")
        for c, v in ours_rows:
            note = str(v.get("note") or "")
            basis = note.split("]", 1)[-1].replace("【须客户确认】", "").strip()
            A(f"| {c} | {v['label']} | {str(v.get('value'))[:60]} | {basis[:70]} | "
              f"{'**是**' if '须客户确认' in note else '否'} |")
        A("")

    if na_codes:
        A(f"## 本版不适用({role} 版,不用填)")
        A("")
        for c in na_codes:
            m = tpl.get(c) or {}
            A(f"- **{c} {m.get('label','')}** —— {str(m.get('why','')).replace('**本版不适用**:','')}")
        A("")

    if proposals:
        A("## 我方建议(原文没有,需你确认或拍板)")
        A("")
        # 不截断。原先这里是 `[:60]` / `[:50]`,和定稿附录 F 犯的是同一个错:
        # 118 字的建议截到 60 字,客户看到的是半句话 —— 而"这条建议是错的"恰恰要靠读完整句才反驳得了。
        # 表格也放不下长句,所以改成每条一段。
        for x in proposals:
            act = ("确认归纳对不对" if x["code"] in ("S2.01", "S4.03")
                   else "选哪几项、目标值定多少" if x["code"] == "S2.02"
                   else "是否等权;若不等权,各条占比")
            A(f"### {x['code']} · {x['label']}")
            A("")
            A(f"- **我方建议**:{x['value']}")
            A(f"- **推导依据**:{x['basis']}")
            A(f"- **需要你做什么**:{act}")
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

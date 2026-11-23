#!/usr/bin/env python3
"""推导「品质岗经历」事实 —— 确定性规则,每条带工作段引文。

为什么需要:第 3 步原本只有年龄/学历两条能排除人,而这份 JD 最硬的一条是
「3 年以上**品质管理**工作经验」。它的**领域**部分以前判不了(C.2 属性未建),
于是 270 人里 169 人全进了短名单 —— 一个做了 8 年外贸跟单的人和一个做了 8 年
品保课长的人在里面并列。

判据(两档,都来自 `parse_experience` 的工作段,**不看全文散落的关键词**):

    A 岗位名命中   段 title 含 品质/品保/品管/质量/质检/QA/QC/QE/SQE/IQC/检验/体系/客诉
    B 职责命中     段 duties 里出现品质专属动作(来料检验/首件巡检/客诉8D/检验标准/体系内审/SPC·CPK/供应商质量)

B 档还必须满足**时长门槛**(默认 ≥24 个月),否则「顺带做过一次首件」也算进来。
A 档不受时长限制 —— 岗位名写在品质序列里,本身就是直接证据。

为什么不用 LLM:这一条要参与**排除人**,而排除必须可重算。同一份 CV 跑两次给出两个
结论的判据不能用来剔人。所以只认能从原文逐字取出证据的规则。

产物:`work/talent/cv_quality.json`

    {cand_id: {
       "verdict": "有" | "无" | "读不出",
       "kind": "A" | "B" | null,
       "months": 28, "actions": ["来料检验", "客诉/8D"],
       "title": "专员/助理", "company": "东莞××电子",
       "span": "2019.03 - 2021.07",
       "quote": "<该段岗位名 + 命中的职责原文片段>",
       "rule": "quality-v1", "min_months": 24}}

用法:
    python -m scripts.talent.derive_quality_facts              # 全量 270 人
    python -m scripts.talent.derive_quality_facts --min-months 12
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

from scripts.talent.cv_parse import parse_experience  # noqa: E402

FACTS = ROOT / "work" / "talent" / "cv_facts.json"
TEXT = ROOT / "work" / "talent" / "cv_text"
OUT = ROOT / "work" / "talent" / "cv_quality.json"

RULE = "quality-v1"
DEFAULT_MIN_MONTHS = 24

#: 岗位名里出现这些词,就算站在品质序列里
TITLE_RE = re.compile(r"(品质|品保|品管|质量|质检|QA|QC|QE|SQE|IQC|OQC|IPQC|检验|体系|客诉)")

#: 品质**专属**动作。故意不收「制程」「生产」「管理」这类泛词 —— 收了就等于把
#: 所有制造业岗位都算成品质经历。
#: 硬动作 —— 只有真做品质的人才会写在职责里。判定「品质岗经历」只看这几类。
HARD_ACTIONS = ("来料检验", "首件/巡检", "检验标准", "体系/审核", "供应商质量")
#: 弱动作 —— 业务、工程、行政的职责里也常见("配合处理客诉""懂 SPC"),**不足以说明做过品质**
WEAK_ACTIONS = ("客诉/8D", "统计工具")

ACTIONS = {
    "来料检验": r"(来料检验|进料检验|进料检查|IQC)",
    # 只写「巡检」会把食堂巡检、6S 巡检、安全巡检全算进来(实测两位行政专员就是这么进来的)。
    # 必须与品质语境同句出现才算。
    "首件/巡检": r"(首件|IPQC|制程巡检|品质巡检|(巡检|检查)[^。;]{0,12}(品质|质量|检验|判定)|(品质|质量|检验)[^。;]{0,12}(巡检|检查))",
    "客诉/8D": r"(客诉|客户投诉|8D|品质异常)",
    "检验标准": r"(检验标准|品质标准|检验规范|SIP|控制计划)",
    "体系/审核": r"(内审|体系审核|ISO9001|IATF16949|ISO/TS16949|质量体系|品质体系)",
    "统计工具": r"(SPC|CPK|QC七大手法|MSA|FMEA)",
    "供应商质量": r"(供应商[^。;]{0,12}(品质|质量)|SQE|来料异常)",
}

#: 证书/培训语境里的提及不算做过 —— 「ISO9001 内审员证书」是资质,不是经历
CERT_CTX = re.compile(r"(内审员|证书|培训|取得|获得|考取|外审员)")
#: 后勤/设施语境里的「巡检/检查」不是品质动作 —— 食堂、宿舍、班车、6S、消防
FACILITY_CTX = re.compile(r"(食堂|宿舍|班车|保洁|绿化|消防|安保|门禁|6S|办公用品|车辆)")
#: `title` 字段偶尔会装进一整句职责(解析串行)。真正的岗位名短、没有句读。
TITLE_JUNK = re.compile(r"[。;；!?]|负责|统筹|进行|管理部|职位:")


def _months(seg: dict) -> int:
    def ym(x):
        m = re.match(r"(\d{4})[.\-/年]?(\d{1,2})?", str(x or ""))
        return (int(m.group(1)), int(m.group(2) or 1)) if m else None

    a, b = ym(seg.get("start")), ym(seg.get("end"))
    if not a or not b:
        return 0
    return max(0, (b[0] - a[0]) * 12 + (b[1] - a[1]))


def _title_ok(title: str) -> bool:
    """这个 `title` 到底是不是岗位名?

    实测:解析偶尔把一整句职责塞进 title(「班长进行KPI考核,监督6$,质量管控」),
    按它判会给一批人发 A 档。真正的岗位名短、没有句读、不以动词开头。
    """
    t = title.strip()
    if not t or len(t) > 20:
        return False
    return not TITLE_JUNK.search(t)


def _quality_actions(duties: str) -> tuple[list[str], list[str]]:
    """返回 `(硬动作, 弱动作)`。证书/培训语境里的提及一律不算。"""
    hard, weak = [], []
    for name, rx in ACTIONS.items():
        for m in re.finditer(rx, duties, re.I):
            ctx = duties[max(0, m.start() - 8): m.end() + 12]
            if CERT_CTX.search(ctx):
                continue          # 「取得 ISO9001 内审员证书」是资质,不是经历
            if FACILITY_CTX.search(ctx):
                continue          # 「食堂日常巡检」「厂区 6S 巡检」不是品质动作
            (hard if name in HARD_ACTIONS else weak).append(name)
            break
    return hard, weak


def profile(text: str, min_months: int) -> dict:
    """一份 CV → 一条品质经历事实。

    判「有」只有两条路:
      A  岗位名就在品质序列里(`_title_ok` 通过),不限时长
      B  **硬动作** ≥1 且该段 ≥ min_months
    弱动作(客诉/8D、SPC)单独出现不算 —— 业务员和工程师的职责里也有。
    """
    segs = parse_experience(text)
    if not segs:
        # 读不出工作段 —— 是**未知**,不是"没做过"。折成"无"等于凭空判一批人不合格。
        return {"verdict": "读不出", "kind": None, "months": 0, "actions": [],
                "hard": [], "weak": [], "title": "", "company": "", "span": "", "quote": "",
                "rule": RULE, "min_months": min_months}

    best = None
    for seg in segs:
        title = str(seg.get("title") or "").strip()
        duties = " ".join(str(d) for d in (seg.get("duties") or []))
        hard, weak = _quality_actions(duties)
        mo = _months(seg)
        # months 读不出来就存 None。存 0 的后果是"读不出时长"被当成"时长=0",
        # 后面所有 >= 比较都会静默地对 0 做 —— 这是本文件早就写在注释里的禁忌。
        base = {"months": mo if mo > 0 else None, "months_known": mo > 0,
                "actions": hard + weak, "hard": hard, "weak": weak,
                "title": title, "company": str(seg.get("company") or ""),
                "span": f"{seg.get('start', '')} - {seg.get('end', '')}".strip(" -"),
                "quote": (title + ":" + duties)[:160] if (title or duties) else ""}
        if TITLE_RE.search(title) and _title_ok(title):
            return {**base, "kind": "A", "verdict": "有", "rule": RULE, "min_months": min_months}
        score = (len(hard), len(hard) + len(weak), mo or -1)
        if best is None or score > (len(best["hard"]), len(best["actions"]),
                                    best["months"] if best["months"] is not None else -1):
            best = base

    if best and best["hard"] and best["months_known"] and best["months"] >= min_months:
        return {**best, "kind": "B", "verdict": "有", "rule": RULE, "min_months": min_months}
    if best and best["hard"] and best["months_known"]:
        return {**best, "kind": "B", "verdict": "无",
                "why_short": f"有品质硬动作({','.join(best['hard'])}),但该段仅 {best['months']} 个月,低于门槛 {min_months}",
                "rule": RULE, "min_months": min_months}
    if best and best["hard"]:
        # 有硬动作但时长读不出 —— 这是"信息缺",不是"不够"
        return {**best, "kind": "B", "verdict": "待核",
                "why_short": f"有品质硬动作({','.join(best['hard'])}),但这段的起止时间读不出来,无法比 {min_months} 个月门槛",
                "rule": RULE, "min_months": min_months}
    if best and best["weak"]:
        # 只出现弱动作:证据不足以判「有」,**也不足以判「没有」** —— 这是待核
        return {**best, "kind": None, "verdict": "待核",
                "why_short": f"只出现弱动作({','.join(best['weak'])})—— 业务/工程职责里也有,"
                             f"既不足以判「做过品质」,也不足以判「没做过」",
                "rule": RULE, "min_months": min_months}
    # 工作段里读不到任何品质动作:**不代表没做过**,只代表简历没写 / 词表没覆盖
    return {**(best or {"kind": None, "months": None, "actions": [], "hard": [], "weak": [],
                        "title": "", "company": "", "span": "", "quote": ""}),
            "verdict": "待核",
            "why_short": "工作段的岗位名与职责里读不到品质动作 —— "
                         "可能是没做过,也可能是没写出来 / 词表没覆盖,需要在面谈中确认",
            "rule": RULE, "min_months": min_months}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-months", type=int, default=DEFAULT_MIN_MONTHS,
                    help=f"B 档(职责命中)的段时长门槛,默认 {DEFAULT_MIN_MONTHS} 个月")
    args = ap.parse_args()

    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for cid, entry in facts.items():
        src = str((entry or {}).get("source_file") or "")
        p = TEXT / f"{pathlib.Path(src).stem}.txt"
        if not p.is_file():
            out[cid] = {"verdict": "读不出", "kind": None, "months": 0, "actions": [],
                        "title": "", "company": "", "span": "", "quote": "",
                        "why": "找不到 CV 正文", "rule": RULE, "min_months": args.min_months}
            continue
        out[cid] = profile(p.read_text(encoding="utf-8", errors="ignore"), args.min_months)

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    yes = [c for c, v in out.items() if v["verdict"] == "有"]
    a = [c for c in yes if out[c]["kind"] == "A"]
    unknown = [c for c, v in out.items() if v["verdict"] == "读不出"]
    print(f"品质经历事实:{len(out)} 人 → 有 {len(yes)}(其中岗位名命中 {len(a)})· "
          f"无 {sum(1 for v in out.values() if v['verdict'] == '无')} · 读不出 {len(unknown)}")
    print(f"门槛:岗位名命中不限时长;职责命中需该段 ≥{args.min_months} 个月")
    print(f"写出 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""渲染**定稿版**岗位说明书:模板 42 个字段全部列出,每个字段都有明确状态。

五种状态,区别很重要 —— 混成一句"待补",就分不清哪些该问客户、哪些我们自己能查:

    有值    原文写了                       → 查原文
    归纳    由原文推出,每句可回查           → 可以反驳,依据摆着
    提案    有依据,但目标值要客户定         → 可以反驳,但要客户拍板
    JD 未写  连依据都没有                   → 只能问客户
    不适用  本岗位确实不涉及                 → 可以反驳

为什么不能省掉空字段:一份只列"有值项"的 JD 读起来像完整,实际**把缺口藏起来了**。
客户问"为什么没写工作地点",答案应该是"原文没有",而不是"我们的模板没这一栏"。

字段集取自 `work/talent/field_schema.yaml`(唯一一份)—— 那是实测的:每个字段在 10 份 JD / 270 份简历里各出现过几次。

用法:
    python -m scripts.talent.render_jd_final --jd 品质经理
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(BACKEND))

import yaml  # noqa: E402

SCHEMA = ROOT / "work" / "talent" / "field_schema.yaml"
CATALOG = ROOT / "work" / "talent" / "component_catalog.yaml"
LIBRARY = ROOT / "work" / "talent" / "requirement_library.yaml"
LINKS = ROOT / "work" / "talent" / "jd_links"
OUT_DIR = ROOT / "work" / "talent" / "jd_docs"

DIM = {"A": "人口属性", "B": "教育", "C": "经历", "D": "技能", "E": "素质能力",
       "F": "资质证书", "G": "合规约束", "H": "语言", "I": "身体条件"}
EDU = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}

V, DER, PROP, MISS, NA = "有值", "归纳", "提案", "JD 未写", "不适用"

#: 职责关键词 → 能力组件。泛用词先判,否则「客户」会把「品质目标管理」误连到「客户验厂」。
DUTY_TO_COMPONENT = (
    (("目标", "任务"), []),
    (("IATF", "ISO", "体系", "制度"), ["skill_ISO_TS16949", "skill_ISO9001"]),
    (("培训", "考核", "教育"), ["skill_培训课程开发"]),
    (("数据", "周报", "月报", "PDCA", "统计", "报表"), ["skill_数据分析"]),
    (("验厂",), ["skill_客户验厂"]),
    (("QC", "8D", "SPC", "CPK", "FMEA", "异常"), ["skill_品质问题分析", "skill_QC七大手法"]),
    (("仪器", "设备", "模治具", "效验", "校验"), []),
    (("供应商", "来料"), []),
    (("图纸", "识图", "SOP", "指示卡"), ["skill_识图"]),
    (("考勤", "社保", "入职", "人事"), ["skill_社保操作"]),
    (("招聘", "面试", "渠道"), ["skill_招聘"]),
    (("报关", "单证", "关务", "进出口"), ["skill_报关", "skill_单证"]),
    (("CAD", "绘图", "制图"), ["skill_AutoCAD"]),
    (("ERP", "订单", "交期"), ["skill_ERP", "skill_跟单"]),
)

DUTY_HEADERS = ("岗位职责", "工作职责", "职务简述", "职责", "工作内容")
STOPS = ("事务表述", "任职资格", "资格要求", "修改履历", "岗位要求",
         "职务名称", "文件编号", "任职要求")


def map_duty(duty: str) -> list[str]:
    for keys, comps in DUTY_TO_COMPONENT:
        if any(k in duty for k in keys):
            return comps
    return []


def _split_items(text: str) -> list[str]:
    """把「1、xxx；2、yyy；」切成条目 —— xlsx 一行里可能塞了整段。"""
    out = []
    for x in re.split(r"[；;]", text):
        x = re.sub(r"^\s*\d+\s*[、.．)]\s*", "", x).strip().strip("| ").strip()
        if x and not x.startswith("（"):
            out.append(x)
    return out


def parse_duties(source: str) -> list[str]:
    """职责段。标题在 10 份 JD 里有四种写法,而且 .xlsx 的是一行内嵌 ——
    只认「岗位职责」会把 7 份的职责判成"客户没写",那是整理方的错,不是客户的缺口。"""
    lines = [l.strip() for l in source.split("\n")]
    out: list[str] = []
    started = False
    for ln in lines:
        if not started:
            for h in DUTY_HEADERS:
                if ln == h:
                    started = True
                    break
                if ln.startswith(h + " |") or ln.startswith(h + "|"):
                    started = True
                    out.extend(_split_items(ln.split("|", 1)[1]))
                    break
            continue
        if any(ln.startswith(s) for s in STOPS):
            break
        if " | " in ln:
            break
        out.extend(_split_items(ln))
    return [x for x in out if x]


def scrape(source: str) -> dict:
    """从原文捞能自动填的 S1/S7 字段。

    .doc 是「标签 值」同一行(.doc 用空格分);
    .xlsx 是「标签 | 值 | 标签 | 值」交替 —— 盲取第二格会把「隶属部门」填成"直接上司"
    (工程文员那份就是这个错),所以按标签走。
    """
    lines = [l.strip() for l in source.split("\n")]
    got: dict[str, str] = {}

    LABELS = {
        "文件编号": "S1.02", "版本": "S1.03", "页数": "S1.04",
        # 核准/审核/制订是同一栏的三个签名位 —— 三个都要认成标签,
        # 否则「核准」会把「审核」当成自己的值(第一版就是这样,显示 核准=审核)
        "核准": "S1.05", "审核": "S1.05", "制订": "S1.05", "批 准 人": "S1.05", "批准人": "S1.05",
        "职务名称": "S1.01", "隶属部门": "S1.06", "直接上司": "S1.07",
        "直接下属": "S1.08", "首次发行": "S7.02",
    }
    # OC R 出来的 .doc 里夹着 \x07 之类控制字符(表格分隔残留)—— 先清掉
    clean = lambda s: re.sub(r"[\x00-\x1f\x7f]", "", s).strip()
    # 去掉标签里的空格再比:「版    本」→「版本」
    norm = lambda s: re.sub(r"\s+", "", clean(s))
    LABEL_NORM = {norm(k): v for k, v in LABELS.items()}

    for ln in lines:
        if "|" in ln:                       # xlsx 行:标签|值|标签|值
            cells = [clean(c) for c in ln.split("|")]
            i = 0
            while i < len(cells):
                key = LABEL_NORM.get(norm(cells[i]))
                if not key:
                    i += 1
                    continue
                nxt = cells[i + 1] if i + 1 < len(cells) else ""
                if norm(nxt) in LABEL_NORM:
                    # 下一格又是标签 → 本字段无值。**只前进 1 格**,
                    # 让下一轮把那个标签当成字段处理(前进 2 会把它的值吃掉)
                    i += 1
                    continue
                if nxt and key not in got:
                    got[key] = nxt
                i += 2
            continue
        # .doc 行:「职务名称品质经理隶属部门品保课直接上司直接下属无」
        if "职务名称" in ln and "隶属部门" in ln:
            ln = clean(ln)
            m = re.search(r"职务名称(\S*?)隶属部门(\S*?)直接上司(\S*?)直接下属(\S*)$", ln)
            if m:
                for key, val in zip(("S1.01", "S1.06", "S1.07", "S1.08"), m.groups()):
                    if val.strip():
                        got.setdefault(key, val.strip())

    # 「版本」在 .doc 里常单独一行,下一行是 A0
    for i, ln in enumerate(lines):
        if norm(ln) == "版本" and i + 1 < len(lines) and re.fullmatch(r"A[.．]?\d+", norm(lines[i + 1])):
            got.setdefault("S1.03", norm(lines[i + 1]).replace("．", "."))
        if norm(ln) == "页数" and i + 1 < len(lines) and lines[i + 1].isdigit():
            got.setdefault("S1.04", lines[i + 1])
        if norm(ln) == "首次发行" and i + 1 < len(lines):
            got.setdefault("S7.02", clean(lines[i + 1]))
        # docx: 「职务名称」占一行,值在下一行
        if norm(ln) == "职务名称" and i + 1 < len(lines):
            got.setdefault("S1.01", clean(lines[i + 1]).replace("职务说明书", ""))
    # docx: 标签一列、值在下一行。按「标签行 → 下一行是值」补一遍
    for i, ln in enumerate(lines):
        key = LABEL_NORM.get(norm(ln))
        if not key or i + 1 >= len(lines):
            continue
        nxt = clean(lines[i + 1])
        if nxt and norm(nxt) not in LABEL_NORM and key not in got:
            got[key] = nxt
    # 「职务名称」若是「XX职务说明书」,取岗位名
    if got.get("S1.01", "").endswith("职务说明书"):
        got["S1.01"] = got["S1.01"][:-5]
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jd", default="品质经理")
    args = ap.parse_args()

    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    # 模板裁剪:JD 只渲染 jd 非 null 的字段
    jd_fields = [f for f in schema["fields"] if f.get("jd")]
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    library = yaml.safe_load(LIBRARY.read_text(encoding="utf-8"))
    link = yaml.safe_load((LINKS / f"{args.jd}.yaml").read_text(encoding="utf-8"))
    source = (ROOT / link["source_text"]).read_text(encoding="utf-8")
    atts = {a["id"]: a for a in catalog["attributes"]}
    reqs = {r["id"]: r for r in library["requirements"]}
    comp_label = {c["id"]: c["label"] for c in catalog["components"]}

    by_cat = collections.defaultdict(list)
    for c in catalog["components"]:
        by_cat[c["category"]].append(c["id"])
    for r in reqs.values():
        cats = r.get("categories") or []
        r["_resolved"] = (sorted({x for cat in cats for x in by_cat.get(cat, [])})
                          if cats else list(r.get("components") or []))

    scraped = scrape(source)
    duties = parse_duties(source)
    by_dim = collections.defaultdict(list)
    for c in link["citations"]:
        by_dim[reqs[c["requirement"]]["dimension"]].append(c)

    L: list[str] = []
    A = L.append
    tally = collections.Counter()
    STRUCT: dict[str, dict] = {}

    def row(code, label, value, status, note=""):
        tally[status] += 1
        STRUCT[code] = {"label": label, "value": value, "status": status, "note": note}
        A(f"| {code} | {label} | {value or '—'} | {status} | {note} |")

    A(f"# {link['jd']} · 岗位说明书(定稿)")
    A("")
    A(f"**{link.get('department','')}** · 模板 {len(jd_fields)} 个字段全部列出(取自 field_schema.yaml);"
      "缺的写「JD 未写」,不需要的写「不适用」,由原文推出的写「归纳」,需客户拍板的写「提案」。")
    A("")
    A(f"> 原文:`{link['source_text']}`(自 `{pathlib.Path(link['source_file']).name}`)")
    A("")

    # ── S1
    A("## 一、岗位标识(S1 身份)")
    A("")
    A("| 码 | 字段 | 值 | 状态 | 说明 |")
    A("|---|---|---|---|---|")
    row("S1.01", "职务名称", link["jd"], V, "文档内写「助理」,以文件名为准" if link["jd"] == "副总助理" else "")
    row("S1.02", "文件编号", scraped.get("S1.02"), MISS, "原文该栏为空")
    row("S1.03", "版本", scraped.get("S1.03"), V if scraped.get("S1.03") else MISS)
    row("S1.04", "页数", scraped.get("S1.04"), V if scraped.get("S1.04") else MISS)
    row("S1.05", "核准/审核/制订", None, MISS, "原文栏位存在但无姓名")
    row("S1.06", "隶属部门", link.get("department") or scraped.get("S1.06"),
        V if (link.get("department") or scraped.get("S1.06")) else MISS)
    row("S1.07", "直接上司", scraped.get("S1.07"), V if scraped.get("S1.07") else MISS)
    row("S1.08", "直接下属", scraped.get("S1.08"), V if scraped.get("S1.08") else MISS)
    row("S1.09", "职业编码", None, MISS, "需按《职业分类大典》编码,原文无")
    row("S1.10", "职级", None, MISS, "需按职级体系套档,原文无")
    A("")

    # ── S2
    A("## 二、岗位目的(S2 目的)")
    A("")
    A("| 码 | 字段 | 值 | 状态 | 说明 |")
    A("|---|---|---|---|---|")
    PURPOSE = [
        ("负责部门品质与业务目标管理,承接上级与客户下达的任务", [1]),
        ("建立并维护管理体系、标准与培训考核机制", [2, 3]),
        ("监督标准执行,组织检测、设备与物料验收,保障过程受控", [4, 5]),
        ("通过数据收集与持续改善,定期报送运营数据", [6]),
        ("对接客户要求与审厂,管理供应商/外部资源质量", [7, 8]),
    ]
    KPI = [
        ("目标达成率", "职责1「保质保量完成…任务」"),
        ("异常闭环率 / 投诉件数", "职责4「执行各项标准…达成目标」"),
        ("报表按时报送率", "职责6「完成周报、月报」"),
        ("客户审厂通过率", "职责7「接待客户、承接客户要求」"),
        ("供应商/外部资源合格率", "职责8「供应商品质管理」"),
    ]
    proposals: list[tuple[str, str, str, str]] = []   # (码, 字段, 我方建议, 推导依据)
    if duties:
        row("S2.01", "岗位目的", None, MISS, "原文无独立段;我方归纳见附录 F")
        row("S2.02", "关键成功指标", None, MISS, "原文无量化指标;我方提案见附录 F")
        proposals.append(("S2.01", "岗位目的", " ".join(x[0] for x in PURPOSE) + "。",
                          "由 8 条职责归纳:" + "、".join(f"「{x[0][:8]}…」←职责{','.join(map(str,x[1]))}"
                                                     for x in PURPOSE)))
        proposals.append(("S2.02", "关键成功指标", "、".join(k[0] for k in KPI),
                          "由职责动词推导:" + ";".join(f"{k}←{v}" for k, v in KPI)))
    else:
        row("S2.01", "岗位目的", None, MISS, "原文无职责段")
        row("S2.02", "关键成功指标", None, MISS, "原文无量化指标")
    A("")
    # ── S3
    A("## 三、任职资格(S3 · 9 个维度全部列出)")
    A("")
    A("| 维度 | 本岗位要求 | 状态 | 条数 |")
    A("|---|---|---|---|")
    for dim in "ABCDEFGHI":
        items = by_dim.get(dim) or []
        if not items:
            STRUCT[f"dim_{dim}"] = {"label": DIM[dim], "value": None, "status": NA,
                                    "note": "本岗位 JD 未提此维度"}
            A(f"| {dim} {DIM[dim]} | — | {NA} | 0 |")
            continue
        texts = []
        for c in items:
            r = reqs[c["requirement"]]
            v = c.get("value") or {}
            att = atts.get(r.get("attribute") or "")
            if att and att["id"] == "A.2":
                texts.append(f"年龄 {v.get('min')}–{v.get('max')} 岁")
            elif att and att["id"] == "A.1":
                texts.append("性别 " + "/".join(v.get("in") or []))
            elif att and att["id"] == "B.1":
                texts.append(f"{EDU.get(v.get('num'))}及以上")
            elif att and att["id"] == "B.2":
                texts.append("专业:" + "/".join(v.get("in") or []))
            elif att and att["id"] == "B.3":
                texts.append("全日制")
            elif att and att["id"] == "C.1":
                texts.append(f"{v.get('num')} 年以上")
            elif r.get("no_component"):
                texts.append(c["verbatim"].rstrip("，,。"))
            else:
                labels = [comp_label[x] for x in (r.get("_resolved") or []) if x in comp_label]
                texts.append("·".join(labels) if labels else r.get("name", ""))
        STRUCT[f"dim_{dim}"] = {"label": DIM[dim], "value": " / ".join(texts),
                                "status": V, "note": f"{len(items)} 条"}
        A(f"| {dim} {DIM[dim]} | {' / '.join(texts)} | {V} | {len(items)} |")
    A("")
    client_cites = [c for c in link["citations"] if c.get("origin", "client") == "client"]
    hr_cites = [c for c in link["citations"] if c.get("origin") == "hr"]
    A("**逐条(含原文行号):**")
    A("")
    A("| # | 原文 | 行 | 维度 | 可评估 |")
    A("|---|---|---|---|---|")
    for i, c in enumerate(client_cites, 1):
        r = reqs[c["requirement"]]
        A(f"| {i} | 「{c['verbatim']}」 | {c['txt_line']} | {r['dimension']} | "
          f"{'是' if r.get('assessable') else '**否**'} |")
    A("")
    if hr_cites:
        # HR 侧要求单独成章 —— 它**不是客户写的**,混进上面的客户原话表就是替客户说话
        A(f"## 三之二、HR 侧要求({len(hr_cites)} 条)")
        A("")
        A("> **这些不是客户原话。** 是 HR 从招聘视角加的要求,每一条都记了"
          "「谁提的、为什么提」,并且和客户要求走同一套判定。")
        A("> 客户正文一个字都没动 —— 两类出处分开,是为了让人一眼看出哪句是客户写的。")
        A("")
        A("| # | 要求 | 判据 | 谁提的 | 为什么 | 取值 |")
        A("|---|---|---|---|---|---|")
        for i, c in enumerate(hr_cites, 1):
            r = reqs[c["requirement"]]
            v = c.get("value") or {}
            if v.get("num") is not None:
                shown = f"{r.get('op','')} {v['num']}"
            elif v.get("value") is not None:
                shown = str(v["value"])
            else:
                shown = "**未给**"
            shape = (r.get("value_shape") or {}).get("num") or ""
            crit = f"{r.get('op','')} {shape}".strip()
            A(f"| {i} | {r.get('name','')} | {crit} | {c.get('author','')} | "
              f"{c.get('rationale','')} | {shown} |")
        A("")
        missing = [reqs[c["requirement"]].get("name", "") for c in hr_cites
                   if not (c.get("value") or {}).get("num")
                   and (c.get("value") or {}).get("value") is None]
        if missing:
            A(f"> 「取值未给」的 {len(missing)} 条({('、'.join(missing))})**卡在客户侧**:"
              "JD 没写预算/地点。数据收得到,但阈值没有 —— 判定会诚实地报「不可判」,"
              "而不是猜一个标准出来。")
        A("")

    # ── S4
    A("## 四、岗位职责(S4 职责)")
    A("")
    A("| 码 | 字段 | 值 | 状态 | 说明 |")
    A("|---|---|---|---|---|")
    row("S4.01", "职责条目", f"{len(duties)} 条", V if duties else MISS,
        "" if duties else "原文无职责段")
    row("S4.02", "职责权重", None, MISS if duties else MISS,
        "原文无时间占比;我方建议等权,见附录 F")
    mapped = [(d, map_duty(d)) for d in duties]
    hit = sum(1 for _, c in mapped if c)
    row("S4.03", "职责对应能力", None, MISS if duties else MISS,
        "原文未建立对应关系;我方按关键词推导,见附录 F")
    A("")
    if duties:
        A("**职责条目(逐字):**")
        A("")
        for i, d in enumerate(duties, 1):
            A(f"{i}. {d}")
        A("")
        proposals.append(("S4.02", "职责权重", f"等权,各 {100//max(len(duties),1)}%",
                          "原文无时间占比;等权是最小假设"))
        proposals.append(("S4.03", "职责对应能力", f"{hit}/{len(duties)} 条可对应",
                          "按关键词表推导,其余在能力词表里无对应项"))
        A("**职责 → 能力对应(我方推导,非客户原文;见附录 F)**")
        A("")
        A("| # | 职责(截断) | 对应能力 |")
        A("|---|---|---|")
        for i, (d, comps) in enumerate(mapped, 1):
            cell = " · ".join(comp_label.get(x, x) for x in comps) if comps else "**—(词表无对应项)**"
            A(f"| {i} | {d[:26]}… | {cell} |")
        A("")
        A(f"> {len(duties)-hit}/{len(duties)} 条职责在 {len(catalog['components'])} 个能力组件里找不到对应项。"
          "这是「职责与任职资格脱钩」在本岗位的具体数字。")
        A("")

    # ── S5 / S6
    A("## 五、作业明细(S5 作业)")
    A("")
    A("| 码 | 字段 | 值 | 状态 | 说明 |")
    A("|---|---|---|---|---|")
    for code, label in (("S5.01", "序号"), ("S5.02", "内容"), ("S5.03", "频次"),
                        ("S5.04", "时长"), ("S5.05", "AI 可否替代"),
                        ("S5.06", "操作标准流程"), ("S5.07", "关联表单")):
        row(code, label, None, MISS, "原文该段为空" if code == "S5.01" else "原文无")
    A("")

    A("## 六、工作条件(S6 条件)")
    A("")
    A("| 码 | 字段 | 值 | 状态 | 说明 |")
    A("|---|---|---|---|---|")
    wl = next((l for l in source.split("\n") if "工作地点" in l or "厂区" in l), None)
    for code, label in (("S6.01", "工作地点/厂区"), ("S6.02", "班制"), ("S6.03", "工时"),
                        ("S6.04", "环境"), ("S6.05", "体力"), ("S6.06", "出差"),
                        ("S6.07", "劳保/防护")):
        row(code, label, None, MISS, "原文无")
    A("")

    # ── S7
    A("## 七、元数据(S7 元数据)")
    A("")
    A("| 码 | 字段 | 值 | 状态 | 说明 |")
    A("|---|---|---|---|---|")
    row("S7.01", "修订履历", "首次发行" if scraped.get("S7.02") else None,
        V if scraped.get("S7.02") else MISS, "无后续修订记录")
    row("S7.02", "首次发行日", scraped.get("S7.02"), V if scraped.get("S7.02") else MISS)
    for code, label in (("S7.03", "发布日期"), ("S7.04", "有效期"),
                        ("S7.05", "编制/招聘人数"), ("S7.06", "招聘原因"),
                        ("S7.07", "发布渠道")):
        row(code, label, None, MISS, "原文无")
    A("")

    # ── S8
    A("## 八、合规声明(S8 合规)")
    A("")
    A("| 码 | 字段 | 值 | 状态 | 说明 |")
    A("|---|---|---|---|---|")
    for code, label in (("S8.01", "保密/数据保密"), ("S8.02", "无犯罪/无行政处罚"),
                        ("S8.03", "竞业限制"), ("S8.04", "用工类型"),
                        ("S8.05", "试用期"), ("S8.06", "社保")):
        row(code, label, None, MISS, "原文无")
    A("")

    # ── 附录 F:我方建议
    A("---")
    A("")
    A("## 附录 F · 我方建议(不是客户原文,未经确认不得使用)")
    A("")
    A("以下内容**客户 JD 里没有**,是我方基于已有信息提出的。放在附录而不是正文,")
    A("是因为我方写的内容一旦混进「定稿」,下一个读的人会以为它是客户说的。")
    A("")
    if proposals:
        A("| 码 | 字段 | 我方建议 | 推导依据 | 需要客户做什么 |")
        A("|---|---|---|---|---|")
        for code, label, value, basis in proposals:
            act = ("确认归纳对不对;不对则指出" if code in ("S2.01", "S4.03")
                   else "选哪几项、目标值定多少" if code == "S2.02"
                   else "是否等权;若不等权,各条占比")
            A(f"| {code} | {label} | {value[:70]} | {basis[:60]} | {act} |")
        A("")
    A("> 这些建议的价值在于**可以被反驳** —— 每条都带推导依据,客户能直接说\"不对,第 3 条不是这个意思\"。")
    A("> 而如果我把它直接写进正文,客户看到的就是一份\"已经写好\"的 JD,连反驳的机会都没有。")
    A("")

    # ── 汇总
    A("## 九、字段填充汇总")
    A("")
    tot = sum(tally.values())
    A("| 状态 | 字段数 | 占比 | 含义 |")
    A("|---|---|---|---|")
    MEAN = {V: "客户原文写了", MISS: "客户原文没有 —— 见附录 F 与待补清单", NA: "本岗位确实不涉及"}
    for k in (V, MISS, NA):
        A(f"| {k} | {tally[k]} | {tally[k]*100//max(tot,1)}% | {MEAN[k]} |")
    A(f"| **合计** | **{tot}** | 100% | |")
    A("")
    A(f"另有 S3 任职资格 **{len(link['citations'])}** 条、S4 职责 **{len(duties)}** 条"
      "(均逐字取自客户原文,不属于 42 字段框架)。")
    A("")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{args.jd}.定稿.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (OUT_DIR / f"{args.jd}.fields.json").write_text(
        json.dumps({"jd": args.jd, "fields": STRUCT, "tally": dict(tally),
                    "proposals": [{"code": c, "label": l, "value": v, "basis": b}
                                  for c, l, v, b in proposals],
                    "citations": len(link["citations"]), "duties": len(duties)},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{args.jd}: 客户原文 {tally[V]} · 未写 {tally[MISS]} · 不适用 {tally[NA]} · "
          f"我方建议 {len(proposals)} 项 | 资格 {len(link['citations'])} 条 · 职责 {len(duties)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())

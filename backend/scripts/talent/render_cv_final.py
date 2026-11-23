#!/usr/bin/env python3
"""渲染**定稿版**候选人档案 —— 字段集由 `field_schema.yaml` 定死,不按好看裁剪。

和 JD 那边同一个原则,而且是**同一份字段全集**:
    field_schema.yaml 是全集;本文件只裁剪 cv 非 null 的字段。
    JD 渲染器裁剪 jd 非 null 的字段。两份模板,一份全集。

字段来源三种,都标出来:
    resume   简历原文有      → 值 + 逐字引文
    derived  由原文推出      → 值 + 推导方式(必须能验算)
    missing  原文没有        → 〔待补〕 + 为什么需要它

另外每条字段会标「两侧可比性」——取自 field_schema 的 compare 判定:
    both / not_comparable / cv_only
这让读的人知道:这一项 JD 那边也在用(能比),还是只有简历有(单边)。

用法:
    python -m scripts.talent.render_cv_final --id cand_xxx
"""
from __future__ import annotations

import argparse
import collections
import json
import os
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
FACTS = ROOT / "work" / "talent" / "cv_facts.json"
#: 这轮新增的两份事实:品质岗经历(确定性判据)与 HR 侧的量(从工作段算出来的)
QUALITY = ROOT / "work" / "talent" / "cv_quality.json"
HR_FACTS = ROOT / "work" / "talent" / "hr_facts.json"
TEXT = ROOT / "work" / "talent" / "cv_text"
OUT = ROOT / "work" / "talent" / "cv_docs"
INTERVIEW = ROOT / "work" / "talent" / "cv_interview"

EDU = {2: "中专/高中", 3: "大专", 4: "本科", 5: "硕士", 6: "博士"}
from scripts.talent.cv_parse import LABELISH, PERIOD, PERIOD_OPEN, QUOTE_CH, SCHOOL, parse_experience  # noqa: E402,E501


def resume_only(text: str) -> dict:
    """简历里**明明写着**、但抽取器没提上来的字段。每条都返回 (值, 引文)。

    只认原文能逐字回查的东西 —— 抓不到就返回空,不猜。
    """
    def grab(pat: str):
        m = re.search(pat, text)
        return m.group(1).strip() if m else None

    out = {}
    # 出生年月:OCR 出来的格式有 "1986 年"、"1985-11-01" 两种,都归一成 YYYY-MM-DD
    if v := grab(r"出生年月[:：]\s*(\d{4})\s*[-年.]\s*(\d{1,2})?"):
        m = re.search(r"出生年月[:：]\s*\d{4}\s*[-年.]\s*(\d{1,2})", text)
        out["F.CV_BIRTH_DATE"] = (f"{v}-{int(m.group(1)) if m else 1:02d}-01", "出生年月")
    # 姓名/电话/籍贯/城市:简历抬头就有,能读就读,别去编
    if v := grab(r"姓\s*名\s*[:：]?\s*([^\s\n]{1,14})"):
        out["F.CV_FULL_NAME"] = (v, "姓名行")
    if v := grab(r"(1[3-9]\d(?:\*{2,}|[\dxX]{2,})[\dxX*]{4,})"):
        out["F.CV_PHONE"] = (v, "简历抬头电话")
    elif v := grab(r"联系电话\s*[:：]\s*(\S+)"):
        out["F.CV_PHONE"] = (v, "联系电话")
    if v := grab(r"期望城市\s*[:：]\s*([^\s|]{2,6})"):
        out["F.WORK_LOCATION"] = (v, "期望城市")
    if v := grab(r"(?:籍\s*贯|ot)\s*[:：]\s*([\u4e00-\u9fa5]{2,8})"):
        out["F.CV_NATIVE_PLACE"] = (v, "籍贯行")
    if v := grab(r"(已婚|未婚)"):
        out["F.CV_MARITAL_STATUS"] = (v, "简历正文")

    if v := grab(rf"求职类型[:：]\s*{QUOTE_CH}?(\S+)"):
        out["F.CV_JOB_TYPE"] = (v, "求职类型")
    # 岗位名:OCR 会把「职位名称」那行读成串,要求含中文且像职位,否则宁可留空交给一面补
    # 只认「像职位」的值:含中文、长度合理、且不是标签词本身(OCR 常把
    # 「意向岗位」「求职类型」「期望城市」这些标签当值读出来)
    _LABEL_WORDS = ("意向", "期望", "求职", "当前", "发展方向", "状态", "地区",
                    "电话", "邮箱", "学历", "职位名称", "岗位")

    def _like_title(x: str) -> bool:
        x = x.strip().strip(":：，,。、“”\"")
        if not (2 <= len(x) <= 12) or not re.search(r"[\u4e00-\u9fa5]", x):
            return False
        return not any(w in x for w in _LABEL_WORDS)

    if (v := grab(rf"职位名称[:：]\s*{QUOTE_CH}?([^\n]+)") or
            grab(r"求职意向\s*[:：]?\s*([^\s|]{2,10})")) and _like_title(v):
        out["F.JOB_TITLE"] = (v.strip().strip(":：，,。、“”\""), "职位名称/求职意向")

    periods = re.findall(rf"毕业院校[:：]\s*{QUOTE_CH}?([^\n(]+?)\s*\(([^)]*)\)", text)
    if periods:
        out["F.CV_EDU_PERIOD"] = (";".join(f"{s.strip()} {p.strip()}" for s, p in periods),
                                  "毕业院校行")
    if v := re.search(r"(具有[^\n]{0,30}内审资格证书)", text):
        out["F.CERTIFICATION"] = (v.group(1), "职业技能第 8 条")
    if v := grab(r"工作经验[:：]\s*([^\s]+)"):
        out["F.EXP_YEARS"] = (v, "工作经验行")
    if v := grab(r"自我评价[:：]\s*\w*\s*([^\n]+)"):
        out["F.COMPETENCY"] = (v, "自我评价")
    if names := re.findall(r"([\u4e00-\u9fa5A-Za-z（）()]{2,20}(?:有限公司|集团|工厂))", text):
        out["F.CV_EMPLOYER"] = (names[0].strip(), "第一段工作经历")
    # 职能域:从担任职位的字面读出,不外推行业
    if titles := re.findall(r"担任职位[:：]\s*" + QUOTE_CH + r"?(\S+)", text):
        zones = []
        for t_ in titles:
            for key in ("品质", "工程", "项目", "开发"):
                if key in t_ and key not in zones:
                    zones.append(key)
        if zones:
            out["F.EXP_DOMAIN"] = ("/".join(f"{z}" for z in zones),
                                   "担任职位行:" + "、".join(titles))
    return out


def _md_cell(x) -> str:
    """表格单元格转义:竖线换成／、换行压成空格、过长的截断。"""
    t = re.sub(r"\s+", " ", str(x if x is not None else "")).replace("|", "／").strip()
    return t if len(t) <= 200 else t[:199] + "…"


def _human(fid: str, v) -> str:
    """把一面答案翻译成档案上看得懂的字面:True→是、4→4 周内。"""
    if isinstance(v, bool):
        return "是" if v else "否"
    if fid == "F.AVAILABILITY" and isinstance(v, int):
        return f"{v} 周内"
    if fid == "F.CV_CURRENT_SALARY" and isinstance(v, int):
        return f"{v}K"
    return str(v)


def load_candidate(cid: str) -> dict:
    import psycopg2
    conn = psycopg2.connect(host=os.environ["ONTOLOGY_DB_HOST"],
                            port=int(os.environ["ONTOLOGY_DB_PORT"]), dbname="talent_db",
                            user=os.environ["ONTOLOGY_DB_USER"],
                            password=os.environ["ONTOLOGY_DB_PASSWORD"])
    with conn.cursor() as cur:
        cur.execute("select id, source_file, salary_min_k, salary_max_k, age, "
                    "education_rank, years_experience from candidate where id=%s", (cid,))
        row = cur.fetchone()
    conn.close()
    if not row:
        raise SystemExit(f"找不到候选人 {cid}")
    return {"id": row[0], "source_file": row[1], "salary_min": row[2], "salary_max": row[3],
            "age": row[4], "edu": row[5], "years": row[6]}



#: 与 derive_quality_facts 同一份动作表 —— 两个脚本对「品质动作」的定义必须一致,
#: 否则同一份简历在两个产物里会给出两种说法。
QUALITY_ACTIONS = {
    "来料检验": r"(来料检验|进料检验|进料检查|IQC)",
    "首件/巡检": r"(首件|IPQC|制程巡检|品质巡检|(巡检|检查)[^。;]{0,12}(品质|质量|检验|判定)|(品质|质量|检验)[^。;]{0,12}(巡检|检查))",
    "客诉/8D": r"(客诉|客户投诉|8D|品质异常)",
    "检验标准": r"(检验标准|品质标准|检验规范|SIP|控制计划)",
    "体系/审核": r"(内审|体系审核|ISO9001|IATF16949|ISO/TS16949|质量体系|品质体系)",
    "统计工具": r"(SPC|CPK|QC七大手法|MSA|FMEA)",
    "供应商质量": r"(供应商[^。;]{0,12}(品质|质量)|SQE|来料异常)",
}


def _months(seg: dict) -> int:
    import re as _re
    def ym(x):
        m = _re.match(r"(\d{4})[.\-/年]?(\d{1,2})?", str(x or ""))
        return (int(m.group(1)), int(m.group(2) or 1)) if m else None
    a, b = ym(seg.get("start")), ym(seg.get("end"))
    return max(0, (b[0] - a[0]) * 12 + (b[1] - a[1])) if a and b else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    args = ap.parse_args()

    from scripts.talent import names as _names
    display = _names.name_of(args.id)
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    facts = json.loads(FACTS.read_text(encoding="utf-8")).get(args.id) or {}
    quality = (json.loads(QUALITY.read_text(encoding="utf-8")).get(args.id)
               if QUALITY.is_file() else {}) or {}
    hr_facts = (json.loads(HR_FACTS.read_text(encoding="utf-8")).get(args.id)
                if HR_FACTS.is_file() else {}) or {}
    cand = load_candidate(args.id)
    textfile = TEXT / (pathlib.Path(cand["source_file"]).stem[:80] + ".txt")
    text = textfile.read_text(encoding="utf-8") if textfile.is_file() else ""
    # 访谈记录:简历没写的字段,由这场对话补。来源标 interview,不混进 resume。
    iv_path = INTERVIEW / f"{args.id.replace('cand_', '')}.yaml"
    iv = yaml.safe_load(iv_path.read_text(encoding="utf-8")) if iv_path.is_file() else {}
    iv_answers = {a["field"]: a for a in (iv.get("answers") or []) if a.get("field")}
    # 新格式的一面答案不带 field,而是 props(数据项→值)/establishes(坐实哪些能力项)。
    # 这两种都要认:否则第 4 步答了半天,CV 定稿上一点看不出来。
    iv_props: dict = {}
    iv_comps: dict = {}
    iv_qa: list = []
    for a in (iv.get("answers") or []):
        basis = str(a.get("basis") or "interview")
        sim = basis in ("simulated", "simulated_interview")
        for k, v in (a.get("props") or {}).items():
            iv_props[k] = {"value": v, "sim": sim, "q": a.get("question"), "a": a.get("answer")}
        for comp in (a.get("establishes") or []):
            iv_comps[comp] = {"sim": sim, "q": a.get("question"), "a": a.get("answer")}
        if a.get("question") or a.get("answer"):
            iv_qa.append({"q": a.get("question") or "", "a": a.get("answer") or "",
                          "sim": sim, "est": a.get("establishes") or [], "props": a.get("props") or {}})

    lang_ans = iv_answers.get("F.LANGUAGE_LEVEL") or {}
    iv_language = None
    for word in ("英文", "英语", "日语", "粤语"):
        if word in str(lang_ans.get("answer") or ""):
            iv_language = {"英文": "英语"}.get(word, word)
            break

    sec_label = schema["sections"]["cv"]
    cv_fields = [f for f in schema["fields"] if f.get("cv")]

    def fv(field):
        return (facts.get(field) or {}).get("value"), (facts.get(field) or {}).get("basis"), \
               ((facts.get(field) or {}).get("quote") or "").strip()

    # 字段 id → (值, 来源, 说明)。prop 已经在 field_schema 的 cv.prop 里声明过。
    age, abasis, aq = fv("age")
    edu, ebasis, eq = fv("education_rank")
    maj, mbasis, mq = fv("major")
    gen, gbasis, gq = fv("gender")
    yrs, ybasis, yq = fv("years")
    ft, ftbasis, ftq = fv("full_time")
    sk = [(s["name"], s.get("quote")) for s in (facts.get("skills") or {}).get("value") or []]

    VALUE = {
        "F.GENDER": (gen, "resume" if gbasis == "stated" else "missing",
                     f"引文「{gq}」" if gq else ""),
        "F.AGE": (age, "derived" if abasis == "computed" else "resume",
                  f"引文「{aq}」({abasis})" if aq else ""),
        "F.EDU_LEVEL": (EDU.get(edu, edu), "resume" if ebasis == "stated" else "derived",
                        f"引文「{eq}」({ebasis})" if eq else ""),
        "F.EDU_MAJOR": (maj, "resume", f"引文「{mq}」" if mq else ""),
        "F.EDU_FULLTIME": (ft, "resume" if ftbasis == "stated" else "missing",
                           f"引文「{ftq}」" if ftq else "270 份里几乎没有直接写「全日制」"),
        "F.EXP_YEARS": (yrs, "resume" if ybasis == "stated" else "missing",
                        f"引文「{yq}」({ybasis})" if yq else ""),
        "F.SKILL": (f"{len(sk)} 项" if sk else None, "resume" if sk else "missing", ""),
        "F.CERTIFICATION": (None, "missing", "证书逐条见下方「已识别能力项」"),
        "F.SALARY": (f"{cand['salary_min']}-{cand['salary_max']}K"
                     if cand["salary_min"] else None,
                     "resume" if cand["salary_min"] else "missing",
                     "来自招聘平台归档,非简历自述"),
    }

    if iv_language:
        VALUE["F.CV_LANGUAGE"] = (iv_language, "interview",
                                  "访谈「英语程度」一问里自述;简历原文未提任何外语")
    # 行业:原文只有「公司产品」行(产品,不是行业),所以这一项不填 —— 留在待补里说清楚。

    # 原文里明写着、但抽取字段没覆盖到的 —— 补上,并保留定位说明。
    extra = resume_only(text)
    for fid, (value, where) in extra.items():
        if fid == "F.CV_FULL_NAME":
            continue          # 已经是"编造(演示)"的完整姓名,别被脱敏写法盖回去
        if VALUE.get(fid, (None,))[0] in (None, ""):
            VALUE[fid] = (value, "resume", f"原文位置:{where}")

    # 姓名:原文是脱敏的(徐* / 华__),显示用编好的完整姓名,来源写「编造(演示)」。
    # **不许标 resume** —— 那不存在的名字不是简历给的。
    VALUE["F.CV_FULL_NAME"] = (display, "编造(演示)",
                               "原文姓名脱敏,这是演练用的完整姓名,与真实简历无关")

    # 年限有三个口径,定稿必须同时露:自述(简历头)/ 逐段累计(可重算但未验)/ 平台文件名(被截断)
    stated_y = (extra.get("F.EXP_YEARS") or (None,))[0]
    if yrs is not None:
        calc = f"逐段累计 {yrs} 年({ybasis},未验算)"
        if stated_y:
            VALUE["F.EXP_YEARS"] = (stated_y, "resume",
                                    f"原文「工作经验」行;逐段累计 {yrs} 年({ybasis})—— 不一致,以自述为准")
        else:
            VALUE["F.EXP_YEARS"] = (yrs, "derived", calc)

    L: list[str] = []
    A = L.append
    A(f"# 候选人档案 · {display}")
    A("")
    A(f"> id:`{args.id}`(文件名与所有产物都以它为键,姓名只是显示)")
    n_sim = sum(1 for a in (iv.get("answers") or [])
                if str(a.get("basis") or "") in ("simulated", "simulated_interview"))
    if n_sim:
        A(f"> ⚠ **本档案有 {n_sim} 个字段来自「模拟访谈」——不是真人说的,是我方按简历与岗位常识推的。**")
        A("> 开发/演练用。**任何对外场合都必须先换成真实访谈记录**(`answers[].basis: interview`)。")
        A("")
    A("")
    A(f"> 字段集取自 `work/talent/field_schema.yaml` —— 该模板裁剪出 **{len(cv_fields)}** 个字段"
      f"(全库共 {len(schema['fields'])} 个字段,两份模板共用一份全集)。")
    A(f"> 原文:`{textfile.relative_to(ROOT) if textfile.is_file() else '缺失'}`(OCR {len(text)} 字)")
    A(f"> 抽取:OCR + 大模型,每条带逐字引文,已过逐字校验。")
    if iv:
        _sim = any(str(a.get("basis") or "") in ("simulated", "simulated_interview")
                   for a in (iv.get("answers") or []))
        A(f"> **访谈**:{iv.get('channel','')} · {iv.get('date','')} · "
          f"{len(iv.get('answers') or [])} 问 · "
          + ("来源标 `代拟(模拟)` 的字段**不是真人说的** —— 模拟补全,开发/演练用。"
             if _sim else "来源标 `interview` 的字段来自这场对话,不是简历原文。"))
    A("")

    # 填充度:先在脑子里过一遍 31 个字段,再打印 —— 读者一眼知道"还缺多少"
    _filled = _from_iv = 0
    for _f in cv_fields:
        _v, _s, _n = VALUE.get(_f["id"], (None, "missing", ""))
        _p = (_f.get("cv") or {}).get("prop")
        _by_iv = (_v in (None, "")) and (_f["id"] in iv_answers or (_p and _p in iv_props))
        if _by_iv:
            _from_iv += 1; _filled += 1
        elif _v not in (None, ""):
            _filled += 1
    A(f"> **填充度**:{len(cv_fields)} 个字段里 **{_filled}** 个有值"
      f"(其中 **{_from_iv}** 个来自一面)· {len(cv_fields) - _filled} 个仍待补。")
    A("")

    by_sec = collections.defaultdict(list)
    for f in cv_fields:
        by_sec[f["cv"]["section"]].append(f)

    missing_fields = []
    for code in sorted(by_sec):
        A(f"## {code} · {sec_label.get(code, code)}")
        A("")
        A("| 字段 | 值 | 来源 | 两侧 | 说明 |")
        A("|---|---|---|---|---|")
        for f in by_sec[code]:
            val, src, note = VALUE.get(f["id"], (None, "missing", ""))
            # 访谈答案(含模拟):用 `from_iv` 单独记"是不是访谈给的",
            # 因为它和"来源该显示成什么"是两件事 —— 混用会出 bug:
            # 把来源标成「代拟(模拟)」以后,下面那些 `src == "interview"` 的分支
            # 就认不出这是访谈值,于是把值丢掉(实测:F.EXP_INDUSTRY / F.EXP_ACTIVITY 两个字段被吞)。
            from_iv = False
            if val in (None, "") and (f.get("cv") or {}).get("prop") in iv_props:
                _iv = iv_props[(f.get("cv") or {}).get("prop")]
                src = "代拟(模拟)" if _iv["sim"] else "面试"
                val = _human(f["id"], _iv["value"])
                _a = str(_iv.get("a") or "")
                for _k, _v in (("True", "是"), ("False", "否")):
                    _a = _a.replace(_k, _v)     # 答案原文里的布尔值也翻成人话
                note = f"一面答:「{_a[:60]}」"
                from_iv = True
            if val in (None, "") and f["id"] in iv_answers:
                a = iv_answers[f["id"]]
                basis = str(a.get("basis") or "interview")
                src = "代拟(模拟)" if basis in ("simulated", "simulated_interview") else "interview"
                val = str(a.get("answer") or "").replace("\n", " ").strip()[:90]
                note = (a.get("note") or "").replace("\n", " ")[:80] or "来源:电话初筛"
                from_iv = True
            # 工作经历/技能这类在下面单独成节 —— 但访谈给了值就不覆盖
            if f["id"] == "F.EXP_INDUSTRY" and not from_iv and src != "interview":
                val, src = None, "missing"
                note = "原文只有「公司产品」行(产品清单),不是行业;不拿产品冒充行业"
            if (f["id"] in ("F.EXP_DOMAIN", "F.EXP_ACTIVITY")
                    and not from_iv and src not in ("interview", "resume")):
                val, src, note = None, "missing", "见下方「工作经历」逐段"
            if val in (None, ""):
                missing_fields.append((f["id"], f["label"], note))
            cmp_ = f.get("compare", "—")
            cell = "〔待补〕" if val in (None, "") else str(val)
            # 引文里常带竖线(「男| 29岁」「商务英语 | 本科」),不转义会把表格撑破
            A(f"| {f['label']} | {_md_cell(cell)} | {src} | {cmp_} | {_md_cell(note or '—')} |")
        A("")

    jobs = parse_experience(text)
    A("## 工作经历(逐段,来自原文)")
    A("")
    A("| 起止 | 公司 | 职位 | 职责条数 | 月数 | 品质动作 |")
    A("|---|---|---|---|---|---|")
    for j in jobs:
        duties_txt = " ".join(str(d) for d in (j.get("duties") or []))
        acts = [k for k, rx in QUALITY_ACTIONS.items() if __import__("re").search(rx, duties_txt, __import__("re").I)]
        mo = _months(j)
        A("| "
          + " | ".join(_md_cell(x) for x in (
              f"{j['start']} - {j['end']}",
              j['company'] or '〔原文没写公司名〕',
              j['title'] or '〔原文没写职位〕',
              str(len(j['duties'])), str(mo or '—'),
              ('·'.join(acts)) if acts else '—'))
          + " |")
    A("")
    gaps = [j for j in jobs if not j["company"] or not j["title"]]
    A(f"> 共 {len(jobs)} 段。语料有两种排法:公司名与起止**分行**写(公司在上)," 
      f"或「公司 职位 起止」**同行**写(公司在前)。以起止行为界切块,块内找公司与职位。")
    if gaps:
        A(f"> 有 {len(gaps)} 段没读出公司或职位 —— 原文缺(OCR 吃字),不是我补的,也不猜。")
    A(f"> 职责原文照抄在下方,不转述、不改写。")
    A("")
    for j in jobs:
        A(f"### {j['start']} - {j['end']} · {j['company'] or '〔公司名缺〕'} · "
          f"{j['title'] or '〔职位缺〕'}")
        A("")
        for d in j["duties"]:
            A(f"- {d}")
        if not j["duties"]:
            A("- 〔原文此段没有可读的编号职责〕")
        A("")

    # ── 品质岗经历(确定性判据,这轮新增)
    A("## 品质岗经历(按工作段判定)")
    A("")
    if quality.get("verdict") == "有":
        A(f"**判定:有**({quality.get('kind')} 档)")
        A("")
        A(f"- 命中段:「{quality.get('title')}」· {quality.get('company')} · {quality.get('span')}")
        A(f"- 该段 {'%d 个月' % quality['months'] if quality.get('months_known') else '起止未读到(不按月判)'}"
          + (f" · 门槛 {quality.get('min_months')} 个月" if quality.get("kind") == "B" else " · A 档不受时长限制"))
        A(f"- 硬动作:{', '.join(quality.get('hard') or []) or '—'}(只有这几类算「做过品质」)")
        A(f"- 弱动作:{', '.join(quality.get('weak') or []) or '—'}(业务/工程职责里也有,单独不算)")
        A(f"- 原文:`{str(quality.get('quote') or '')[:150]}`")
    else:
        A(f"**判定:{quality.get('verdict') or '无'}** —— {quality.get('why_short') or '岗位名与职责都没有品质动作'}")
    A("")
    A("> 判据只认工作段的**岗位名**(A 档)与**职责里的硬动作**(B 档 + 该段 ≥24 个月),")
    A("> 不看全文散落的关键词;「ISO9001 内审员证书」这类证书语境、食堂/6S 巡检这类后勤语境都不算。")
    A("")

    # ── HR 侧的量(从工作段算出来的,标注 basis)
    if hr_facts:
        A("## 稳定性相关(从工作段算出来的,可验算)")
        A("")
        A("| 量 | 值 | 怎么算的 |")
        A("|---|---|---|")
        LABEL = {"segment_count": "任职段数", "recent5y_segments": "近 5 年任职段数",
                 "avg_tenure_years": "平均在职年数", "notice_weeks": "到岗时间(周)"}
        for k, label in LABEL.items():
            v = hr_facts.get(k) or {}
            val = v.get("value") if isinstance(v, dict) else v
            basis = v.get("basis") if isinstance(v, dict) else ""
            why = v.get("why") if isinstance(v, dict) else ""
            A(f"| {label} | {val if val is not None else '〔读不到〕'} | {basis or '—'}{' · ' + str(why)[:40] if why else ''} |")
        A("")
        A("> 这些量是**推出来的**,不是原文写的:`avg_tenure_years` 由各段起止累加得出,")
        A("> `notice_weeks` 只有简历写了「到岗时间」才有。判不了就留空,**不填 0** —— 填 0 等于判人零在职。")
        A("")

    iv_comp_rows = [(comp.replace("skill_", ""), v) for comp, v in iv_comps.items()]
    if sk or iv_comp_rows:
        comp_label = {c["label"]: c["id"] for c in catalog["components"]}
        A("## 已识别能力项(全部带原文引文或一面原话)")
        A("")
        A("| 能力项 | 来源 | 类别 | 原文引文 / 一面原话 |")
        A("|---|---|---|---|")
        for name, quote in sk:
            cid = comp_label.get(name)
            cat = next((c["category"] for c in catalog["components"] if c["id"] == cid), "—")
            A(f"| {name} | 简历 | {cat} | 「{(quote or '')[:44]}」 |")
        for name, rec in iv_comp_rows:
            A(f"| {name} | {'代拟(模拟)' if rec['sim'] else '一面'} | 一面确认 | "
              f"「{str(rec.get('a') or '')[:44]}」 |")
        A("")

    # ── 一面评语(4b 的产物;可能是 HR 真访谈,也可能是**我方代拟**)
    review = (iv or {}).get("review") or {}
    if review:
        drafted = review.get("drafted_by") == "ours" or review.get("needs_hr_confirm")
        A("## 一面评语(4b)")
        A("")
        if drafted:
            A("> ⚠ **这一段是简历复核后的代拟稿,不是 HR 面过的印象。**"
              "`needs_hr_confirm: true` —— 一面完成后必须按访谈重写。")
            A("")
        else:
            A(f"> 来源:{(iv or {}).get('channel', '访谈')} · {(iv or {}).get('date', '')} · "
              f"面试人 {(iv or {}).get('interviewer', '')}")
            A("")
        for key, label in (("heard", "听到了什么"), ("basis", "据此怎么判断"),
                           ("reservation", "保留意见")):
            v = str(review.get(key) or "").strip()
            if v:
                A(f"**{label}**:{v}")
                A("")
        gaps = review.get("known_gaps") or []
        if gaps:
            A("**已知缺口**:")
            A("")
            for g in gaps:
                A(f"- {g}")
            A("")
        A("> 评语**不参与 join**(`not_in_computation: true`):它是判断,不是判定。"
          "要参与判定的东西必须先落成要求或答案。")
        A("")

    # ── 一面记录(逐条问答)──────────────────────────────────────
    if iv_qa:
        sim_any = any(x["sim"] for x in iv_qa)
        A("## 一面记录(" + ("模拟,非真人说的" if sim_any else "真实访谈") + ")")
        A("")
        A("> 这一节就是第 4 步补进来的东西:简历里没有的字段与能力,由这通电话补上。")
        A("")
        A("| # | 问 | 答 | 落成什么 |")
        A("|---|---|---|---|")
        for i, x in enumerate(iv_qa, 1):
            landed = []
            if x["props"]:
                landed.append("字段 " + ", ".join(f"{k}={v}" for k, v in x["props"].items()))
            if x["est"]:
                landed.append("能力项 " + ", ".join(e.replace("skill_", "") for e in x["est"]))
            A(f"| {i} | {str(x['q'])[:50]} | {str(x['a'])[:70]} | {'; '.join(landed) or '—'} |")
        A("")

    # ── 待澄清 + 复核问题 ─────────────────────────────────────────
    # 这两段是给一面对话用的:HR 拿着档案打电话,先问"不清楚的",再问"要复核的"。
    # 全部由本档案已有的事实生成,不在这里重新判定一次。
    A("## 待澄清(资料不清楚,或读不出来)")
    A("")
    clarify: list[tuple[str, str, str]] = []
    qv = (quality or {}).get("verdict")
    if qv in ("待核", "读不出", None):
        clarify.append(("品质岗经历", "品质岗判定",
                        f"判定「{qv or '未判'}」—— {(quality or {}).get('why_short') or '读不到'}"))
    if isinstance(quality, dict) and quality.get("months_known") is False:
        clarify.append(("品质岗时长", "时长读不出来", "该段起止时间读不出来,无法与门槛比较"))
    # 关键字段缺值:两侧都能比(compare=both)的最该先问
    cmap2 = {f["id"]: f.get("compare", "—") for f in cv_fields}
    for fid, label, note in missing_fields:
        if cmap2.get(fid) == "both":
            clarify.append(("CV 字段", label, note or "档案里没有"))
    if clarify:
        A("| 来源 | 项 | 为什么不清楚 |")
        A("|---|---|---|")
        for src, item, why in clarify[:24]:
            A(f"| {src} | {item} | {why} |")
        A("")
    else:
        A("> 没有需要澄清的项。")
        A("")

    A("## 复核问题(怀疑哪里,就问哪里)")
    A("")
    A("> 这些不是「再问一遍」,是**针对性复核**:每一条都指向档案里一个具体薄弱点,")
    A("> 问完能不能站住,当场就知道。")
    A("")
    review_q: list[tuple[str, str]] = []
    if qv == "有":
        review_q.append(("品质岗经历",
                         f"档案认定「{(quality or {}).get('title') or '?'}」"
                         f"({(quality or {}).get('months') or '?'} 月)是品质岗 —— "
                         f"请你复核:当时具体做哪一环?判定 / 异常处理 / 审核,你是哪一个?"))
    elif qv in ("待核", "读不出"):
        review_q.append(("品质岗经历",
                         "档案读不出你是否做过品质岗 —— 近三年有没有做过检验判定、"
                         "异常处理、体系或客户审核?哪一段、多久、具体做什么?"))
    # 能力项:只有自述、没有载体的,按**类别**给不同问法 ——
    # 对 Word/AutoCAD 也问"什么不良、结果如何"是荒唐的(实测首版就这么错)。
    Q_BY_KIND = {
        '软件': "请说清你用它做过什么:哪个项目、产出什么文件?能现场演示吗?",
        '语言': "用这门语言独立处理过什么?能否给一份你写过的报告/邮件(脱敏)?",
        '品质工具': "给一个具体不良,现场走一遍:你怎么判、用什么工具、结论是什么?",
        '行业知识': "说出你们产品的关键工序与最常见的不良,以及你当时怎么处理。",
        '质量体系': "那套体系你负责哪一环?最近一次审核/内审发现的问题是什么?",
        '管理': "你带过几个人?最棘手的一次人员/交期冲突怎么解决的?",
    }
    comp_cat = {}
    for c in catalog.get("components") or []:
        comp_cat[c["label"]] = c.get("category") or ""
    LABEL2KIND = {'AutoCAD': '软件', 'ProE/Creo': '软件', 'SolidWorks': '软件',
                  'Word': '软件', 'Excel': '软件', 'PowerPoint': '软件', 'SAP': '软件',
                  'ERP': '软件', '英语': '语言', '日语': '语言',
                  'SPC': '品质工具', 'CPK': '品质工具', '8D报告': '品质工具',
                  'QC七大手法': '品质工具', '5WHY': '品质工具', '6S': '品质工具',
                  'FMEA': '品质工具', 'MSA': '品质工具',
                  '线束行业知识': '行业知识', '端子': '行业知识', '客户验厂': '行业知识',
                  'ISO9001': '质量体系', 'ISO_TS16949': '质量体系', 'IATF16949': '质量体系',
                  '品质问题分析': '品质工具', '体系管理': '质量体系'}
    for name, quote in (sk or [])[:6]:
        kind = LABEL2KIND.get(name) or ('管理' if '管理' in name else '')
        q = Q_BY_KIND.get(kind) or "请举一个你亲手做的例子:什么场景、你做了什么、结果如何?"
        review_q.append((f"能力项「{name}」",
                         f"档案里只有一句自述「{(quote or '')[:36]}」—— {q}"))
    # 推算量:不是原文写明的
    for k, label in (("years_experience", "总年限"), ("education_rank", "学历")):
        item = (facts or {}).get(k) or {}
        if item.get("value") is not None and item.get("basis") in ("inferred", "computed"):
            review_q.append((label,
                             f"{label}是按简历推算的({item.get('value')}),不是你写明的 —— "
                             f"请确认;有毕业证 / 离职证明请提供。"))
    segs = ((hr_facts or {}).get("segment_count") or {}).get("value")
    if isinstance(segs, int) and segs >= 4:
        review_q.append(("稳定性",
                         f"档案里数到 {segs} 段工作经历 —— 每段为什么离开?下一份打算做多久?"))
    if review_q:
        A("| 复核对象 | 怎么问 |")
        A("|---|---|")
        for obj, q in review_q[:20]:
            A(f"| {obj} | {q} |")
        A("")
    else:
        A("> 没有需要额外复核的点。")
        A("")

    A("## 待补清单")
    A("")
    A(f"按 `field_schema.yaml` 裁剪出的 {len(cv_fields)} 个字段,本档案有 "
      f"**{len(missing_fields)}** 项无值:")
    A("")
    A("| 字段 | 为什么需要 | 两侧可比性 |")
    A("|---|---|---|")
    cmap = {f["id"]: f.get("compare", "—") for f in cv_fields}
    for fid, label, note in missing_fields:
        A(f"| {label} | {note or '—'} | {cmap.get(fid, '—')} |")
    A("")

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{args.id.replace('cand_', '')[:30]}.定稿.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"写出 {out.relative_to(ROOT)}  {len(L)} 行 · 字段 {len(cv_fields)} · "
          f"无值 {len(missing_fields)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

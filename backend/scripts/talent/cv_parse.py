"""简历原文的解析器 —— 只有这一份。

为什么单独成文件:`parse_experience` 有两个消费者(渲染定稿、算 HR 的那些量),
一开始各写一份,结果同一批语料一个切出 243 段、一个切出 95 段。
同一件事有两份实现,迟早会分叉,而且分叉时两边各自都"看起来正常"。
所以这里只留一份,谁要用谁 import。

解析器认三种排法(语料实测):
    ① 公司独占一行,下一行 `起止 + 担任职位`
    ② `公司 职位 起止` 全在一行,公司在前、日期在后
    ③ 起止一行,公司名在上一行或下一行,职位又来一行 `职 务: xx`
"""
from __future__ import annotations

import re



_D = r"((?:19|20)\d{2}(?:\s*[.\-/年]\s*\d{1,2}\s*月?)?)"
PERIOD = re.compile(_D + r"\s*[-—~至]+\s*(至今|现在|" + _D + r")")
#: 终点被 OCR 吃掉的写法(「2020.01 - #4 深圳市龙达…」)—— 起点是真的,终点标截断
PERIOD_OPEN = re.compile(_D + r"\s*[-—~至]+\s*(?=[^\s\d])")
QUOTE_CH = "[\"'\u201c\u201d\u201e]"
#: 标签必须带冒号 —— 否则「项目」会把「项目工程师」的前两个字吃掉(真踩过)
LABELISH = re.compile(r"^(?:公司名称|任职时间|担任职位|工作描述|公司产品|客户群体|"
                      r"主要产品|职业技能|联系方式|手机|电子邮件|教育背景|毕业院校|"
                      r"自我评价|求职意向|基本信息|项目|职务|职位)\s*[:：]")
SCHOOL = re.compile(r"(学校|大学|学院|中学|大专|职校|职业技术学院)")
TITLE_WORD = re.compile(r"(经理|主管|工程师|专员|助理|总监|主任|技术员|文员|课长|组长|"
                        r"班长|副总|厂长|组长)")
#: 「工作经历」之后的第一个别节,只解析到那里为止
SECTION = re.compile(r"^\s*(教育经历|教育背景|项目经历|专业技能|自我评价|培训经历|"
                     r"证书|荣誉|联系方式|基本信息|求职意向|职业技能)\s*$")
PROJECT = re.compile(r"(项目经历|项目经验|培训经历|证书)")
LEAD = re.compile(r"^[\s一二三四五六七八九十\d]+[、.．)）]\s*")
SEP = re.compile(r"\s*[。•·|｜]\s*")


def _clean(s: str) -> str:
    s = (s or "").strip()
    s = LEAD.sub("", s)
    s = LABELISH.sub("", s)
    s = re.sub(r"^[#＃\s\d]+(?=\S)", "", s)
    s = s.strip()
    s = re.sub(rf"^{QUOTE_CH}+|{QUOTE_CH}+$", "", s).strip()
    return re.sub(r"\s{2,}", " ", s)


def _looks_like_employer(line: str) -> bool:
    if not line or len(line) > 30:
        return False
    if LABELISH.match(line) and not re.search(r"(公司|集团|厂)", line):
        return False
    if re.search(r"\d{3}", line):
        return False
    return bool(re.search(r"(公司|集团|厂|实业|科技|电子|有限)", line))


#: 职位标签的 OCR 残形:担任职位 / 职位 / 职务 / 职 HF / 只 务 / 职 务
TITLE_LABEL = re.compile(rf"^(?:担任)?(?:职|只)\s*\S{{0,3}}?\s*[:：]\s*{QUOTE_CH}?(\S+)")


def parse_experience(text: str) -> list[dict]:
    """把「公司 / 职位 / 起止」从简历里读出来 —— 语料至少有三种排法,都得认。

    ① 公司独占一行,下一行 `起止 + 担任职位`            (廖那份)
    ② `公司 职位 起止` 全在一行,公司在前、日期在后      (251/270 份是这个家族)
    ③ 起止一行,公司名在它**上一行或下一行**,职位又来一行 `职 务: xx`

    所以判据不是"行首是什么",而是:**以起止行为界切成块**,块内找公司、找职位。
    教育经历里也有起止,按学校关键词剔掉 —— 不能让它混成一段工作。
    """
    lines = text.splitlines()
    head = next((i for i, ln in enumerate(lines) if "工作经历" in ln), 0)
    # 只解析「工作经历」这一节:教育/项目/培训里也有起止,放进来就变成假的工作段
    tail = next((i for i in range(head + 1, len(lines))
                 if SECTION.search(lines[i]) and not re.search(r"工作经历", lines[i])),
                len(lines))

    marks: list[int] = []
    for i in range(head, tail):
        if SCHOOL.search(lines[i]) or PROJECT.search(lines[i]):
            continue
        if PERIOD.search(lines[i]) or PERIOD_OPEN.search(lines[i]):
            marks.append(i)

    jobs: list[dict] = []
    for k, i in enumerate(marks):
        line = lines[i].strip()
        stop = marks[k + 1] if k + 1 < len(marks) else min(tail, i + 14)
        prev = [ln for ln in lines[max(head, i - 3):i] if ln.strip()]
        block = lines[i + 1:stop]

        pm = PERIOD.search(line) or PERIOD_OPEN.search(line)
        truncated = not PERIOD.search(line)
        span = pm.group(0).strip()
        end = "〔原文截断〕" if truncated else (pm.group(3) or pm.group(2)).strip()

        # ── 职位:标签优先(块内或本行),否则看本行分割出的后半截
        title = None
        raw_before, raw_after = line[:pm.start()], line[pm.end():]
        before, after = _clean(raw_before), _clean(raw_after)
        for cand in [line, raw_after, raw_before, *block]:
            m = TITLE_LABEL.match(cand.strip())
            if m:
                title = _clean(re.sub(r"^[:：]", "", m.group(1)))
                break
        if not title:
            for chunk in (after, before, *block):
                if chunk and TITLE_WORD.search(chunk):
                    title = chunk[TITLE_WORD.search(chunk).start():]
                    break

        # ── 公司:本行 → 上一行(最多 3 行)→ 块内第一行像公司的
        company = None
        for chunk in (before, after):
            for part in SEP.split(chunk):
                if _looks_like_employer(part):
                    company = _clean(part)
                    break
            if company:
                break
        if not company:
            for cand in reversed(prev):
                if _looks_like_employer(cand.strip()):
                    company = _clean(cand)
                    break
        if not company:
            for cand in block:
                if _looks_like_employer(cand.strip()):
                    company = _clean(cand)
                    break
        if company and company == title:
            company = None

        jobs.append({"company": company, "start": pm.group(1).strip(), "end": end,
                     "span": span, "title": title, "pos": i,
                     "duties": [ln.strip() for ln in block
                                if re.match(r"^\d{1,2}[.、]", ln.strip())]})
    return jobs

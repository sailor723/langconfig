"""Parsing a CV that arrived as a SCAN: what can be known without a model, and what cannot.

Measured on the client's dossier (2026-11-14): 277 PDFs, 0 characters extractable — every page is one
`/Image`, no `/Font`, no `/ToUnicode`. So the facts come from three places, in descending honesty:

  1. **the path** — department and role folder are a human's own filing, e.g.
     `04、技术课候选人简历/设计工程师/…` (12 role folders, 3 departments, 277 files);
  2. **the filename** — the recruiting platform already encoded what it asked:
     `【设计助理工程师_东莞 7-10K】雷__ 1年` → role, city, salary band 7–10K, 1 year;
     the legacy shape `唐__-42岁-智通简历-编号(...)` → age only;
  3. **OCR text** — usable but dirty (`SolidWorks` came out as `Solitvedks`, `Photoshop` as
     `Photoshog`), so skill matching is by TOLERANT PATTERN against a small starter vocabulary and
     anything unmatched is kept as raw evidence rather than guessed into a canonical skill.

Every field is returned as `{value, source}` where source is `path` / `filename` / `ocr`; a field
nobody could read stays `None` with `source: "missing"`. That distinction is the whole point: an
unknown year of experience must not become 0, and a résumé that failed OCR must not become a
candidate with every skill absent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

#: OCR mangles Latin brand names; match shapes, not spellings. Each entry is (canonical, regex).
#: The regexes are deliberately loose on vowels and doubled letters — `Solitvedks` must match
#: SolidWorks, `coneidw` must match CorelDRAW — because OCR on these scans drops and swaps them.
SKILL_PATTERNS: list[tuple[str, str]] = [
    ("SolidWorks", r"s[o0]l[i1l]?[dt]?[vw]?[o0]?r?k?s?"),
    ("AutoCAD", r"auto\s*cad|[^a-z]cad[^a-z]"),
    ("ProE/Creo", r"pro\s*[/\\]?\s*e\b|creo"),
    ("CATIA", r"cat[i1]a"),
    ("UG/NX", r"\bug\b|unigraphics|\bnx\b"),
    ("Rhino", r"rh[i1]no"),
    ("KeyShot", r"key\s*shot"),
    ("Photoshop", r"photo\s*sh[o0]?[gp]"),
    ("Illustrator", r"illu\w*[st]rator|\bai\b"),
    ("CorelDRAW", r"corel\s*d\w*|cone\w*dw|core\w*draw"),
    ("Excel", r"excel|\bex[c]?el\b"),
    ("Word", r"\bword\b"),
    ("PowerPoint", r"power\s*point|\bppt\b"),
    ("ERP", r"\berp\b"),
    ("SAP", r"\bsap\b"),
    ("ISO9001", r"iso\s*9001|iso9000|iso\s*体系"),
    ("ISO/TS16949", r"16949|ts16949|iatf"),
    ("精益生产", r"精益|lean"),
    ("5S", r"5s\b"),
    ("外贸业务", r"外贸|外贸业务|国际业务"),
    ("跟单", r"跟单"),
    ("报关", r"报关|关务"),
    ("单证", r"单证"),
    ("招聘", r"招聘"),
    ("薪酬绩效", r"薪酬|绩效|kpi"),
    ("劳动法", r"劳动法|劳动合同"),
    ("行政", r"行政"),
    ("财务", r"财务|会计|成本核算"),
    ("英语", r"英语|CET|四级|六级"),
]

#: Salary band as the platform wrote it: `7-10K`, `10-14K`, `15-20K`, or `面议`.
_SALARY = re.compile(r"(\d{1,2})\s*[-~—]\s*(\d{1,2})\s*[Kk千]?")
#: "1年 / 4年 / 10年以上" is experience; "26年应届生" is a GRADUATION YEAR and "2026年毕业" is a
#: calendar year. Measured on the client's dossier: `马__ 26年应届生` came out as 26 years of
#: experience — a fresher described as a 26-year veteran, which is exactly the kind of number an
#: ontology must never fabricate. Anything over 45 is treated as not-an-experience-count too.
_YEARS = re.compile(r"(?<!\d)(\d{1,2})\s*年(?:以上|以內|以内)?(?!\s*(?:应届|毕业|畢业|屆|届|生|入|份|度|级))")
_MAX_PLAUSIBLE_YEARS = 45
_AGE = re.compile(r"(\d{2})\s*岁")
_CITY = re.compile(r"[_＿\s](东莞|深圳|广州|惠州|中山|佛山|珠海|上海|苏州|杭州|厦门)")
_DEPT = re.compile(r"^(\d{2})[、.]\s*(.+?)(?:候选人简历|侯选人简历)?$")
_MASKED_NAME = re.compile(r"^([\u4e00-\u9fa5]{1,3}[_＿]+)")

EDUCATION = [
    ("博士", r"博士"),
    ("硕士", r"硕士|研究生|MBA"),
    ("本科", r"本科|学士|大学本科"),
    ("大专", r"大专|专科|大專|高职"),
    ("中专/高中", r"中专|中專|高中|技校|职高"),
]


@dataclass
class Field:
    value: object = None
    source: str = "missing"
    note: str = ""

    def to_dict(self) -> dict:
        return {"value": self.value, "source": self.source, **({"note": self.note} if self.note else {})}


@dataclass
class CandidateRecord:
    candidate_id: str
    source_file: str
    department: Field = field(default_factory=Field)
    role_folder: Field = field(default_factory=Field)
    applied_role: Field = field(default_factory=Field)
    city: Field = field(default_factory=Field)
    salary_min_k: Field = field(default_factory=Field)
    salary_max_k: Field = field(default_factory=Field)
    years_experience: Field = field(default_factory=Field)
    age: Field = field(default_factory=Field)
    name_masked: Field = field(default_factory=Field)
    education: Field = field(default_factory=Field)
    skills: list[str] = field(default_factory=list)
    skills_raw: list[str] = field(default_factory=list)
    ocr_chars: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        out = {"candidate_id": self.candidate_id, "source_file": self.source_file}
        for name in ("department", "role_folder", "applied_role", "city", "salary_min_k",
                     "salary_max_k", "years_experience", "age", "name_masked", "education"):
            out[name] = getattr(self, name).to_dict()
        out["skills"] = sorted(set(self.skills))
        out["skills_raw"] = sorted(set(self.skills_raw))[:40]
        out["ocr_chars"] = self.ocr_chars
        out["warnings"] = self.warnings
        return out


def parse_path(rel_path: str) -> tuple[Field, Field]:
    """(department, role folder) from `03、管理科+副总室侯选人简历/人资专员/x.pdf`."""
    parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
    dept = Field()
    role = Field()
    for part in parts[:-1]:
        m = _DEPT.match(part)
        if m and dept.value is None:
            dept = Field(f"{m.group(1)}、{m.group(2).strip()}", "path")
        elif dept.value is not None and role.value is None:
            role = Field(part.strip(), "path")
    return dept, role


def parse_filename(stem: str) -> dict:
    """Everything the recruiting platform encoded in the name — deterministic, no OCR."""
    out: dict[str, Field] = {
        "applied_role": Field(), "city": Field(), "salary_min_k": Field(),
        "salary_max_k": Field(), "years_experience": Field(), "age": Field(),
        "name_masked": Field(),
    }
    working = stem

    # 【岗位_城市 7-10K】…  — the exported shape
    bracket = re.search(r"【([^】]+)】", stem)
    if bracket:
        inner = bracket.group(1)
        body = inner.split("】")[0]
        city_m = _CITY.search(body)
        salary_m = _SALARY.search(body)
        role_part = re.split(r"[_＿\s]", body)[0].strip()
        if role_part:
            out["applied_role"] = Field(role_part, "filename")
        if city_m:
            out["city"] = Field(city_m.group(1), "filename")
        if salary_m:
            out["salary_min_k"] = Field(int(salary_m.group(1)), "filename")
            out["salary_max_k"] = Field(int(salary_m.group(2)), "filename")
        working = stem.replace(bracket.group(0), "")

    years_m = _YEARS.search(working)
    if years_m:
        count = int(years_m.group(1))
        if count <= _MAX_PLAUSIBLE_YEARS:
            out["years_experience"] = Field(count, "filename")
        else:
            out["years_experience"] = Field(
                None, "missing", f"{count} 年 in the file name reads as a year, not experience")
    age_m = _AGE.search(working)
    if age_m:
        out["age"] = Field(int(age_m.group(1)), "filename")
    name_m = _MASKED_NAME.search(working.strip()) or _MASKED_NAME.search(stem.strip())
    if name_m:
        out["name_masked"] = Field(name_m.group(1), "filename")
    return out


def parse_text(text: str) -> dict:
    """Fields that only OCR can give, with the messy bits kept as evidence."""
    lowered = text or ""
    skills: list[str] = []
    for canonical, pattern in SKILL_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            skills.append(canonical)
    education = Field()
    for label, pattern in EDUCATION:
        if re.search(pattern, lowered):
            education = Field(label, "ocr")
            break
    years = Field()
    # "10年经验 / 工作年限：8年 / 8 年以上工作经验" — only take the pattern that names work.
    work_m = re.search(r"(?:工作年限|工作经验|工作经历)[：:\s]*([0-9]{1,2})\s*年", lowered)
    if work_m:
        years = Field(int(work_m.group(1)), "ocr", "work-years phrase")
    return {"skills": skills, "education": education, "years_experience_from_text": years}


def build_record(rel_path: str, stem: str, ocr_text: str) -> CandidateRecord:
    """One record from the three sources. Missing stays missing; nothing is defaulted to 0."""
    dept, role = parse_path(rel_path)
    from_name = parse_filename(stem)
    from_text = parse_text(ocr_text)

    rec = CandidateRecord(candidate_id=stem, source_file=rel_path,
                          department=dept, role_folder=role,
                          applied_role=from_name["applied_role"],
                          city=from_name["city"],
                          salary_min_k=from_name["salary_min_k"],
                          salary_max_k=from_name["salary_max_k"],
                          years_experience=from_name["years_experience"],
                          age=from_name["age"],
                          name_masked=from_name["name_masked"],
                          education=from_text["education"],
                          skills=list(from_text["skills"]),
                          ocr_chars=len(ocr_text or ""))
    # A year count that exists ONLY in the text is kept, and marked as such (source stays "ocr") —
    # it must not silently outrank the filename, which is the platform's own statement.
    if rec.years_experience.value is None and from_text["years_experience_from_text"].value is not None:
        rec.years_experience = from_text["years_experience_from_text"]

    if rec.ocr_chars == 0:
        rec.warnings.append("no OCR text — the record rests on path and filename only")
    if rec.skills == []:
        rec.warnings.append("no skill recognised in the text")
    if rec.years_experience.value is None:
        rec.warnings.append("years of experience unknown (not 0)")
    return rec


def as_dict(rec: CandidateRecord) -> dict:
    return asdict(rec) if False else rec.to_dict()

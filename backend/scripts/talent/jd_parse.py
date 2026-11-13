"""Reading a job description: role, education floor, years, and the skills it names.

The client's ten 职务说明书 arrived in three formats (.doc x6, .docx x1, .xlsx x2) and with no shared
template — one has a `资格要求` block, another puts everything in a table cell, a third only has a
职务简述. So this module extracts what is *stated*, in the same vocabulary the CV parser uses, and
reports what it could not find instead of filling it in:

    education_floor : 高中 / 中专 / 大专 / 本科 / 硕士  (None when the JD names no level)
    min_years       : an integer when the text says "N年以上" / "N年经验", else None
    skills          : canonical skill names matched with the SAME tolerant patterns as the CVs, so a
                      requirement and a candidate say the same word for the same thing

Why the same vocabulary matters: the ontology's role classes are built out of `:hasSkill some <Skill>`
restrictions. If the JD side says "ERP订单管理模块" and the CV side says "ERP", a requirement that the
client plainly meant would never match — the reasoner would be right and the answer would be useless.
"""
from __future__ import annotations

import re

from scripts.talent.parse import SKILL_PATTERNS, EDUCATION

#: Role names as the client writes them in the file name, plus the department each belongs to.
_ROLE_NOISE = re.compile(r"(职务说明书|岗位说明书|最新修改版|\d+\s*[.、]|-\s*11\.7|编号)")
_VERSION_TAIL = re.compile(r"[-—_ ]*(v?\d+(\.\d+)*)$")

EDUCATION_RANK = {"中专/高中": 2, "高中": 2, "中专": 2, "大专": 3, "本科": 4, "硕士": 5, "博士": 6}


def role_from_filename(stem: str) -> str:
    """`2. 业务跟单职务说明书` -> `业务跟单`; `关务报关员职务说明书-11.7` -> `关务报关员`."""
    name = _ROLE_NOISE.sub("", stem)
    name = _VERSION_TAIL.sub("", name)
    return name.strip(" -—_·.")


def _education_floor(text: str) -> str | None:
    """The highest level named, because "本科及以上" is a floor of 本科, not of 高中."""
    found: list[tuple[int, str]] = []
    for label, pattern in EDUCATION:
        if re.search(pattern, text):
            rank = EDUCATION_RANK.get(label)
            if rank:
                found.append((rank, label))
    if not found:
        # "高中及以上学历" is common and EDUCATION's label for it is 中专/高中
        if re.search(r"高中|中专|技校|职高", text):
            found.append((2, "中专/高中"))
    if not found:
        return None
    label = max(found)[1]
    return "中专/高中" if label in ("高中", "中专") else label


def _min_years(text: str) -> int | None:
    """`3年以上经验` / `2 年经验` / `10年以上` — none of these is a graduation year."""
    best: int | None = None
    for m in re.finditer(r"(\d{1,2})\s*年\s*(?:以上)?(?:的)?\s*(?:相关)?(?:工作)?\s*(?:经验|经历)",
                         text):
        value = int(m.group(1))
        if 0 < value <= 45 and (best is None or value > best):
            best = value
    if best is None:
        for m in re.finditer(r"(\d{1,2})\s*年\s*以上", text):
            value = int(m.group(1))
            if 0 < value <= 45 and (best is None or value > best):
                best = value
    return best


def _skills(text: str) -> list[str]:
    return sorted({canonical for canonical, pattern in SKILL_PATTERNS
                   if re.search(pattern, text, re.IGNORECASE)})


def requirements_from_text(role: str, text: str) -> dict:
    """Everything the JD states, with a `missing` list for what it does not."""
    skills = _skills(text)
    floor = _education_floor(text)
    years = _min_years(text)
    missing = []
    if floor is None:
        missing.append("education_floor")
    if years is None:
        missing.append("min_years")
    if not skills:
        missing.append("skills")
    return {
        "role": role,
        "education_floor": floor,
        "education_rank": EDUCATION_RANK.get(floor or "", None),
        "min_years": years,
        "skills": skills,
        "missing": missing,
        "chars": len(text or ""),
    }


def as_ttl_comment(req: dict) -> str:
    """A one-line, human-readable summary — the ABox builder writes it into the profile."""
    bits = [f"role {req['role']}"]
    if req.get("education_floor"):
        bits.append(f"education>={req['education_floor']}")
    if req.get("min_years") is not None:
        bits.append(f"years>={req['min_years']}")
    if req.get("skills"):
        bits.append("skills=" + "/".join(req["skills"]))
    if req.get("missing"):
        bits.append("NOT STATED: " + ",".join(req["missing"]))
    return " · ".join(bits)

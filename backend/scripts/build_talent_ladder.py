#!/usr/bin/env python3
"""Generate the cumulative ladder of `talent_steps` — one ontology, seven snapshots.

WHY A GENERATOR: the tutorial's promise is "stepNN is a strict superset of step(N-1): each step
adds exactly one thing". Hand-maintaining seven cumulative copies of the same TTL made that promise
false — a class added in step 5 was missing from step 6, so step 6 was NOT a superset and the
Protégé walkthrough would have shown a file whose ontology had changed under the reader's feet.
That is exactly the class of drift the ladder exists to prevent.

So the ladder has ONE source of truth (the STEPS list below) and the seven files are written from
it. The teaching comments live in the same place, so a comment can never describe a TTL that is
not there.

Run:  python backend/scripts/build_tutorial_steps.py
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "talent_steps"

PREFIXES = """@prefix :    <http://example.org/talent#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""

#: (number, title, teaching-note, [(comment, ttl), ...]) — the ONE source of truth
STEPS: list[tuple[int, str, str, list[tuple[str, str]]]] = [
    (1, "一个空筐",
     "整个本体只有【一个实体】：候选人这个类。它是一个空筐——还没有任何人，也没有任何属性。\n"
     "                      这一步回答「世界上有哪几类东西」，不回答「谁在里面」。",
     [("一个空筐：候选人", ":Candidate  a  owl:Class .")]),

    (2, "给筐配一个动词",
     "本步新增唯一的属性：工作年限。主语只能是人（domain），填进去的值只能是整数（range）。\n"
     "                      为什么选它做第一个属性？因为它只依赖第 1 步已有的 :Candidate；\n"
     "                      hasSkill 的宾语要指向第 3 步才存在的 :SkillTag，一次加两样就看不出各自的作用。",
     [("「工作年限」：主语是人，值是整数 → 数据属性",
       ":yearsExperience  a  owl:DatatypeProperty ;\n"
       "    rdfs:domain :Candidate ;\n"
       "    rdfs:range  xsd:integer .")]),

    (3, "第二个筐",
     "本步新增一个类：技能标签。此刻 :Candidate 与 :SkillTag 之间【一条关系都没有】——\n"
     "                      它们还是两个孤岛。记住这个「没有关系」的状态，下一步才知道桥修好了意味着什么。",
     [("另一个空筐：技能标签", ":SkillTag  a  owl:Class .")]),

    (4, "把两个岛连起来",
     "本步新增唯一的属性：会什么技能。domain 是人、range 是技能，有方向。\n"
     "                      桥修好了，但本体里 hasSkill 被用了 0 次——路上还没有车。",
     [("「会什么技能」：主语是人，宾语是技能 → 对象属性（桥）",
       ":hasSkill  a  owl:ObjectProperty ;\n"
       "    rdfs:domain :Candidate ;\n"
       "    rdfs:range  :SkillTag .")]),

    (5, "放一件具体的东西，并归进类别",
     "本步新增两句：一个个体（Python）和一个类别类（Programming），并把个体归进类别。\n"
     "                      【类 vs 个体】:SkillTag 是筐，:Python 是筐里的一件具体东西。\n"
     "                      技能写成类（:Python a owl:Class）就推不出「谁会 Python」——这是本项目踩过的坑。\n"
     "                      :Python a :SkillTag , :Programming . 这一句就是「事实 → 规则」的那座桥。",
     [("技能筐里的第一件东西：Python（还归进了「编程类」这个类别）",
       ":Python  a  :SkillTag , :Programming ."),
      ("类别类「编程类技能」：它是「技能标签」的子类",
       ":Programming  a  owl:Class ;\n"
       "    rdfs:subClassOf :SkillTag .")]),

    (6, "把技能挂到人身上",
     "本步新增两句事实（ABox）：两个人，技能相同、只有年限不同。\n"
     "                      没有对照就看不出规则有没有起作用：等推理跑起来，A 合格、B 不合格，且只差在年限。\n"
     "                      铁律：ABox 里不许出现结论——不能写 :cand_A a :matches_SoftwareEngineer .",
     [("两个具体的人 + 他们的技能和年限 —— 本体里第一批事实（ABox）",
       ":cand_A  a  :Candidate ;\n"
       "    rdfs:label         \"A — Python, 5 years\" ;\n"
       "    :hasSkill        :Python ;\n"
       "    :yearsExperience 5 .\n"
       "\n"
       ":cand_B  a  :Candidate ;\n"
       "    rdfs:label         \"B — Python, 1 year\" ;\n"
       "    :hasSkill        :Python ;\n"
       "    :yearsExperience 1 .")]),

    (7, "写下那条公理",
     "本步新增那条公理：软件工程师 = 是候选人 ∧ 会编程类技能 ∧ 年限 ≥ 3。\n"
     "                      类必须有名字（a owl:Class 不能省），否则推理机答不了「谁在里面」。\n"
     "                      owl:someValuesFrom 指向的是【类别类】，匹配的是个体的类型。\n"
     "                      equivalentClass 是定义不是要求：合格的人不需要写进文件。",
     [("「软件工程师」的定义 —— 本体第一次会推理",
       ":matches_SoftwareEngineer  a  owl:Class ;\n"
       "    owl:equivalentClass [\n"
       "        owl:intersectionOf (\n"
       "            :Candidate\n"
       "            [ a  owl:Restriction ;\n"
       "               owl:onProperty    :hasSkill ;\n"
       "               owl:someValuesFrom :Programming ]\n"
       "            [ a  owl:Restriction ;\n"
       "               owl:onProperty    :yearsExperience ;\n"
       "               owl:someValuesFrom [ a rdfs:Datatype ;\n"
       "                                    owl:onDatatype xsd:integer ;\n"
       "                                    owl:withRestrictions ( [ xsd:minInclusive 3 ] ) ] ] ) ] .")]),
]

HEADER = """# ═════════════════════════════════════════════════════════════════════════════
# 第 {n} 步：{title}
#
{note}#
# 【这一份是第 {n} 步的快照】前面 {prev} 步的内容都在里面 —— 每一份文件都能在
# Protégé 里单独打开，而且第 {n} 步是第 {prev} 步的严格超集（只多出新东西）。
#
# 完整教学说明见 backend/examples/talent_steps/README.md
# ═════════════════════════════════════════════════════════════════════════════

"""


def build(upto: int) -> str:
    """The full TTL of step n: every earlier step's blocks, then this step's."""
    parts = [PREFIXES, "\n"]
    for i, (n, title, note, blocks) in enumerate(STEPS, 1):
        if i > upto:
            break
        parts.append(f"# ── 第 {i} 步{'（新增）' if i == n else ''}"
                     f"{'─' * max(0, 66 - len(str(i)))}\n")
        for comment, ttl in blocks:
            for line in comment.splitlines():
                parts.append(f"# {line}\n")
            parts.append(ttl + "\n\n")
    return "".join(parts)


def _commented(text: str) -> str:
    """Every line of prose becomes a comment. A prose line that reaches the Turtle parser is a
    syntax error, and the first symptom is 'expected directive or statement' with no line number."""
    return "".join(f"# {line}\n" if line.strip() else "#\n" for line in text.splitlines())


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for n, title, note, _ in STEPS:
        head = HEADER.format(n=n, title=title, note=_commented(note), prev=n - 1)
        text = head + build(n)
        path = OUT / f"step{n:02d}.ttl"
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    _write_readme()
    return 0


# ── the README, generated from the same source ───────────────────────────────
README_HEAD = """# CV ↔ JD matching ontology — step by step in Protégé

> **This file is generated.** The ladder (`step01.ttl` … `step07.ttl`) and this page come from one
> source: `backend/scripts/build_talent_ladder.py`. Editing one by hand makes the other start lying
> — which is exactly how the platform's own tutorial prose drifted away from the database once.
>
> Regenerate: `python backend/scripts/build_talent_ladder.py`

Seven snapshots, one thing per step. Every file opens on its own in Protégé, and each is a **strict
superset** of the one before it — a property `backend/tests/test_tutorial_steps.py` enforces.

**Where the files are**

```
backend/features/ontology/profiles/talent_steps/ontology/step01.ttl … step07.ttl
backend/examples/talent_steps/step01.ttl … step07.ttl          (the generator's output)
```

> ⚠️ Opening a file in Protégé and **saving** it rewrites the file and destroys the teaching
> comments. Work on a copy, or on `step07.ttl` (the complete one), and keep the ladder as reference.

---

## 0. Three rules, stated once

### ① The TBox / ABox line

| | TBox (rules) | ABox (facts) |
|---|---|---|
| Talks about | what counts as a match | who has what |
| Subject is | a class / property / axiom | **a concrete individual** |
| Example | `:hasSkill a owl:ObjectProperty` | `:cand_A :hasSkill :Python` |

The test: **is the subject a named individual? → fact. Is it a class or a property? → rule.**

### ② The value's type decides the Protégé panel

| Property type | Value type | Shows up in | Example |
|---|---|---|---|
| `owl:DatatypeProperty` | a number / string (a literal) | **Data properties** | `:yearsExperience 5` |
| `owl:ObjectProperty` | another **entity** | **Object properties** | `:hasSkill :Python` |

> ⚠️ The easiest thing to get wrong: `yearsExperience` and `hasSkill` are **both properties of a
> candidate**, yet one lands in the Data panel and the other in the Object panel. What decides the
> panel is the **type of the value** — not which class the property is about.

### ③ Individuals carry the facts; classes fuel the rules

```
the object of a FACT   → an individual (a concrete thing)   :cand_A :hasSkill :Python
the object of a RULE   → a class (a box)                     ( :hasSkill some :Programming )
```

**The rule of thumb:** the thing you can **have** is an individual; the thing you can **reason
over** is a class.

---

## 1. The ladder

| Step | File | What it adds | Triples | Layer |
"""

README_TAIL = """
The shape of it:

```
step 1  :Candidate            (class)         the thing itself
step 2  :yearsExperience      (data prop)     the first thing we can say
step 3  :SkillTag             (class)         a second kind of thing
step 4  :hasSkill             (object prop)   the link between them
step 5  :Python + :Programming (individual + category class)   a skill in the box
step 6  :cand_A + :cand_B     (individuals)   the facts about two people
step 7  :matches_SoftwareEngineer    (axiom)         what counts — and the reasoner decides
```

---

## 2. What each step looks like in Protégé

| Step | Classes | Data properties | Object properties | Individuals |
|---|---|---|---|---|
| 1 | `Candidate` | — | — | — |
| 2 | `Candidate` | `yearsExperience` | — | — |
| 3 | `Candidate`, `SkillTag` | `yearsExperience` | — | — |
| 4 | `Candidate`, `SkillTag` | `yearsExperience` | **`hasSkill`** | — |
| 5 | + `Programming` | `yearsExperience` | `hasSkill` | **`Python`** |
| 6 | (unchanged) | `yearsExperience` | `hasSkill` | + **`cand_A`**, **`cand_B`** |
| 7 | + `matches_SoftwareEngineer` | `yearsExperience` | `hasSkill` | (unchanged) |

⚠️ **Individuals do not appear in the Classes panel** — they are in the Individuals panel
(Protégé 5.6: `Individuals by class`). That is the usual reason a reader thinks a file is empty.

⚠️ **A class with zero asserted instances can be hidden** by Protégé's default filter. At step 7,
`matches_SoftwareEngineer` has **no asserted instances** (its members are *inferred*), so a filter that
shows only classes with instances hides it. Click the ⊘ filter icon in the Class hierarchy toolbar
to turn the filter off, or use the search box at the top right.

---

## 3. The questions each step can answer

The query box in the tutorial runs against **that step's own file**, so a question asked early gets
the honest answer.

| Question | Step 4 | Step 5 | Step 6 |
|---|---|---|---|
| `SELECT ?c WHERE { ?c a owl:Class }` | `Candidate`, `SkillTag` | + `Programming` | same |
| `SELECT ?p WHERE { ?p a owl:ObjectProperty }` | `hasSkill` | same | same |
| `SELECT (COUNT(?c) AS ?n) WHERE { ?c a :Candidate }` | `0` | `0` | `2` |
| `SELECT ?s WHERE { ?s a :SkillTag }` | *(empty)* | `Python` | `Python` |
| `SELECT ?c ?l WHERE { ?c a :Candidate ; rdfs:label ?l }` | *(empty)* | *(empty)* | `cand_A`, `cand_B` |

**“0” and “no rows” are different answers.** The first says “there are none”; the second says “I
have nothing to tell you”. Which one you get tells you how far the ontology has been built.

---

## 4. “Put a concrete skill on a candidate” — what must exist

| # | What | Turtle | Layer |
|---|---|---|---|
| 1 | the skill **exists** | `:Python a :SkillTag , :Programming .` | **ABox** |
| 2 | the **verb** exists | `:hasSkill a owl:ObjectProperty ; domain :Candidate ; range :SkillTag .` | **TBox** |
| 3 | the **fact** connects them | `:cand_A a :Candidate ; :hasSkill :Python .` | **ABox** |

The fact's payload must be an **individual**:

```turtle
:cand_A :hasSkill :Python .      ✅ says WHICH skill
:cand_A :hasSkill :SkillTag .     ❌ only says "has some skill"
```

---

## 5. The iron rule: no conclusions in the ABox

```turtle
:cand_A  a  :Candidate .             ✅ fact
:cand_A  a  :matches_SoftwareEngineer .    ❌ conclusion — it must be reasoned
```

Only because the conclusion is not written in the file can the **falsification test** hold: delete
the axiom, re-run, and the answer must disappear. Measured on `step07.ttl`:

```
before deleting the axiom : matches_SoftwareEngineer → ['cand_A']
after  deleting the axiom : matches_SoftwareEngineer → []
```

---

## 6. Related files

| File | Purpose |
|---|---|
| `backend/features/ontology/profiles/talent_steps/` | the tutorial as served by the platform (8 chapters, shell, pictures) |
| `backend/features/ontology/profiles/talent_steps/STORYLINE.md` | the story, in plain English, before any of it is drawn |
| `backend/scripts/build_talent_ladder.py` | the ladder and this page — **one source** |
| `backend/scripts/build_tutorial_steps.py` | the 8 HTML chapters (their numbers are measured, not written) |
| `backend/scripts/build_tutorial_graphs.py` | the per-step pictures, derived from each step's TTL |
| `backend/tests/test_tutorial_steps.py` | the guards: the ladder must grow strictly, the pictures must match their files, the working queries must really work |
| `backend/features/ontology/reasoning/reasoner.py` | the platform's reasoner (HermiT via owlready2) |
"""


def _write_readme() -> None:
    """The README is generated from the same STEPS list, so its table cannot go stale."""
    from rdflib import Graph

    rows = []
    for n, title, note, blocks in STEPS:
        g = Graph()
        g.parse(OUT / f"step{n:02d}.ttl", format="turtle")
        adds = "；".join(c.splitlines()[0] for c, _ in blocks)
        layer = "ABox" if n in (5, 6) else "TBox"
        rows.append(f"| {n} | `step{n:02d}.ttl` | {adds} | {len(g)} | **{layer}** |")
    text = README_HEAD + "\n".join(rows) + "\n" + README_TAIL
    path = OUT / "README.md"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    raise SystemExit(main())

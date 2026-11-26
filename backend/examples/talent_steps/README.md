# CV ↔ JD matching ontology — step by step in Protégé

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
| 1 | `step01.ttl` | 一个空筐：候选人 | 1 | **TBox** |
| 2 | `step02.ttl` | 「工作年限」：主语是人，值是整数 → 数据属性 | 4 | **TBox** |
| 3 | `step03.ttl` | 另一个空筐：技能标签 | 5 | **TBox** |
| 4 | `step04.ttl` | 「会什么技能」：主语是人，宾语是技能 → 对象属性（桥） | 8 | **TBox** |
| 5 | `step05.ttl` | 技能筐里的第一件东西：Python（还归进了「编程类」这个类别）；类别类「编程类技能」：它是「技能标签」的子类 | 12 | **ABox** |
| 6 | `step06.ttl` | 两个具体的人 + 他们的技能和年限 —— 本体里第一批事实（ABox） | 20 | **ABox** |
| 7 | `step07.ttl` | 「软件工程师」的定义 —— 本体第一次会推理 | 41 | **TBox** |

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

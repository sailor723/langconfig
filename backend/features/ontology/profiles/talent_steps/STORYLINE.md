# 故事线 —— 从零搭一个 CV ↔ JD 匹配本体

> **中文正文见 `tutorial/ZH.md`**（七步，先结论后术语）。这份英文原件保留作对照：
> 它是**动笔之前**写的工作笔记 —— 故事在这里站不住，再多 HTML 也救不回来。
>
> 读者：任何同事，包括没写过查询、不按逻辑思考的人。
> 技术词会出现，但永远排在一句大白话之后，且标明"可选"。

英文原件正文（保留以便对照术语与原始表述）：

# The storyline — building a CV ↔ JD matching ontology

> A working note, written **before** any of it is drawn. If the story does not hold up here, no
> amount of HTML will save it.
>
> **Who this is for:** anyone on the team — including someone who has never written a query and
> does not think in logic. The technical words appear, but always *after* the plain sentence that
> carries the meaning, and always labelled as optional.

---

## The story in one paragraph

We want the system to answer one question: **"does this person qualify for this job?"**
Today a recruiter answers it by reading résumés. Tomorrow the computer should answer it — and we
want to be able to **show our working** when it says no. So we build the description of a candidate
piece by piece: first the candidate itself, then the things we can say about them, then the rule
that decides.

---

## The shape of the story

**First the thing. Then the details about the thing.**

That is the order a recruiter already uses. You meet a person, and *then* you look at their CV.
You don't start with "five years of experience" — you start with "a candidate".

The reverse order — "let me set up the experience field first" — is how people get stuck. A field
with no person to put it on is a blank column.

---

## The seven steps

Each step adds **one** thing, and each one is the obvious next question after the one before.

### Step 1 · Create the candidate

**What we add:** one class called `Candidate` — an empty box labelled "candidates".

**In plain words:** we write down that *candidates exist*. We don't say anything about them yet.

**Why this is first:** you cannot describe something you haven't named yet.

**What the reader sees:** one box on the right, nothing in it.

> *Optional technical note:* this is a **class** — a category of thing. In Protégé it sits under
> `owl:Thing`, the "everything" box at the top.

---

### Step 2 · Say how many years of experience they have

**What we add:** `yearsExperience` — a slot on the candidate that holds a number.

**In plain words:** now we can say "this candidate has 5 years of experience".

**Why this is next:** it's the simplest thing you can say about a person, and it's the one every
job ad asks for. It is also a **number**, not a thing — which is why it lives in a different place
in the tool than a skill will (step 4).

> *Optional technical note:* a **data property**, holding a literal value like `5`.

---

### Step 3 · Add skills as their own kind of thing

**What we add:** a second empty box called `SkillTag` — for skills.

**In plain words:** a skill is not a person. "Python" is not a candidate. So skills need their own
box, separate from the candidate box.

**This box is the container.** The skills themselves come later (step 5) and are filed inside it,
each under a category that says what kind of skill it is. This step creates the *container*; the
contents go in afterwards.

**Why this is next:** because step 2 showed us candidates have *two kinds* of information about
them — numbers (years) and things (skills). Numbers go in a slot; things need a box of their own.

**What the reader sees:** two boxes, and **no connection between them yet**.

> *Optional technical note:* a second **class**. Two classes with no link between them are two
> separate islands — step 4 joins them. And they must stay separate kinds of thing: writing
> `:SkillTag rdfs:subClassOf :Candidate` would say "every skill is a candidate", and the machine
> would then conclude every candidate is a skill too — the model collapses into one meaningless box.

---

### Step 4 · Join them: a candidate *has* a skill

**What we add:** `hasSkill` — the link from the candidate box to the skill box.

**In plain words:** we write down that a candidate can *have* a skill. The link only points one
way: candidates have skills; skills don't have candidates.

**The skills box is an open list.** This link points at a *box*, not at a fixed set of items. We
never write down "the skills are Python, Java, Excel" as the rule. We say: *a candidate may have any
skill that exists* — and the skills themselves arrive later, one at a time, from whatever the CVs
actually say. On this project 277 CVs mention **hundreds** of different skills, and nobody could
have listed them in advance. The box stays open; the contents are **data, not schema**.

**Why this is next:** we have both boxes; now we connect them.

**Important:** the link is now **defined but unused**. Nowhere yet does it say *who* has *which*
skill. That's step 6 — and this gap is deliberate, so the reader can see it.

> *Optional technical note:* an **object property** (it points at another thing, not at a number).

---

### Step 5 · Put a real skill in the skill box

**What we add:** `Python` as a concrete skill, filed under a "programming" category.

**In plain words:** "Python" is one specific skill. It goes in the skills box, and it's filed as a
programming skill (rather than, say, a spreadsheet skill).

**Why this is next:** the box has been empty for two steps. Now we put something in it.

**The important idea — and the mistake this step exists to prevent:**

> "Python" must be a **specific item**, not a **category**. If we wrote "Python" as a category
> (an empty box), then the rule "has a programming skill" would match **nobody at all** — because
> there'd be no *thing* anyone could have.
>
> *In plain words:* you cannot **have** a category. You can have a **Python**. The category is what
> you *reason over*; the item is what someone *has*.

---

### Step 6 · Say who has what

**What we add:** two people — A (Python, 5 years) and B (Python, 1 year) — with their facts.

**In plain words:** now the candidate box holds people, the link carries something, and the numbers
are filled in.

**Why two people:** so there's a comparison. Both know Python; only one clears the experience bar.
One person would prove nothing.

> *Optional technical note:* these are the **facts** (ABox) — sentences whose subject is a
> concrete individual.

---

### Step 7 · Write the rule, and let the machine decide

**What we add:** the definition of "software engineer".

**In plain words:**

> A software engineer is **someone who** is a candidate, **and** has a programming skill,
> **and** has 3 years or more of experience.

**Why this is last:** every piece of it must already exist. The rule mentions a candidate (step 1),
experience (step 2), skills and their category (steps 3–5), and the link that ties them (step 4).

**The payoff:**

> Nobody writes "A is a software engineer". The rule says it, and the machine works it out.
> A qualifies (5 years, Python). B does not (1 year).
>
> **And we can prove the machine worked it out:** delete the rule, and the answer disappears.
> Before deleting: A qualifies. After deleting: nobody qualifies.
>
> That test is the difference between a system that *describes* and one that *decides*.

---

## The whole thing on one line

```
1  a candidate          →  2  their years      →  3  skills exist
   →  4  candidates have skills  →  5  Python is a real skill
   →  6  A has Python and 5 years, B has Python and 1 year
   →  7  software engineer = candidate + programming skill + 3+ years
```

---

## Three rules of good manners for this course

**1. One thing per step.** Never add two things at once — the reader cannot tell what each one
did. (Step 2 deliberately avoids the skill link: that link needs step 3's box to point at.)

**2. English is the source.** The pages are written in English. A Chinese edition is a dictionary,
not a rewrite.

**3. Every number is measured.** The pages ask the real reasoning engine and print what it said.
We got this wrong once already: our own older tutorial claimed "35 and 22 people" where the
database said "37 and 24". Prose that nobody re-checks is how that happened.

---

## A note for the people who *do* know the technical terms

You can skip the plain-English versions — they carry no extra information, just a different
vocabulary. But the two ideas below are the load-bearing ones, and they are worth naming
explicitly:

**A. Class vs individual.** A **class** is a box (a *kind* of thing): `Candidate`, `SkillTag`.
An **individual** is one concrete thing inside a box: `cand_A`, `Python`.
*Rule of thumb: the thing you can **have** is an individual; the thing you can **reason over** is
a class.*

**B. Facts carry individuals; rules carry classes.**

```
a FACT   :cand_A  :hasSkill  :Python         ← the object is a concrete thing
a RULE   ( :hasSkill some :Programming )     ← the object is a box
```

The bridge between them is the type assertion on step 5: `:Python a :Programming .`

**The TBox/ABox line** (used throughout the platform, worth learning): a sentence whose subject is
a **named individual** is a *fact*; a sentence about a **class or property** is a *rule*. The
whole course lives on that line.

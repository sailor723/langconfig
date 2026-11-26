#!/usr/bin/env python3
"""Build the authored chapters of the `talent_steps` tutorial.

THE STORYLINE LIVES IN `features/ontology/profiles/talent_steps/STORYLINE.md`, and this file is
its other half: the storyline says what the seven steps *mean*, this file turns them into pages.

Four rules this generator obeys, each of which exists because of a way the previous tutorials went
wrong:

  1. ENGLISH IS THE SOURCE LANGUAGE. The profile declares `ui.language: en`. The i18n mechanism
     translates a SOURCE language into a DECLARED one, so a Chinese edition is a dictionary, not a
     rewrite — and an unfinished dictionary leaves the page in English rather than blank.
  2. EVERY NUMBER IS MEASURED. `facts()` runs the real reasoner over the real TTL and returns what
     it said. The platform's own `talent_v1` prose once quoted 35 and 22 members where the
     database said 37 and 24 — prose nobody re-checks is how that happens.
  3. ONE THING PER STEP. Each chapter adds exactly one idea, and the picture on the right shows
     exactly what that step's file contains.
  4. PLAIN ENGLISH FIRST. The technical words come after the sentence that carries the meaning, and
     are marked optional. A recruiter must be able to follow this without knowing what OWL is.

Run:  python scripts/build_tutorial_steps.py
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROFILE = ROOT / "features" / "ontology" / "profiles" / "talent_steps"
OUT = PROFILE / "tutorial"
STEPS = PROFILE / "ontology"

KEY = "talent_steps"
NS = "http://example.org/talent#"

CSS = """
  body { font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif; background:#f6f7f9; margin:0; color:#1c1e21; }
  header { background:#102a43; color:#fff; padding:18px 26px; }
  header h1 { margin:0; font-size:17px; }
  header .rev { display:block; margin-top:4px; font:10px ui-monospace,Menlo,monospace; color:#9fb8cf; }
  nav { background:#16324f; padding:8px 26px; }
  nav a { color:#9fb8cf; font-size:12px; margin-right:14px; text-decoration:none; }
  nav a.on { color:#fff; font-weight:600; }
  main { max-width:1180px; margin:20px auto; padding:0 20px; }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:900px) { .cols { grid-template-columns:1fr; } }
  .card { background:#fff; border:1px solid #e3e6ea; border-radius:10px; padding:16px 18px; }
  h2 { margin:0 0 10px; font-size:12px; letter-spacing:.5px; color:#334e68; text-transform:uppercase; }
  h3 { margin:14px 0 6px; font-size:13px; color:#334e68; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th { text-align:left; font-size:11px; text-transform:uppercase; color:#687b8f; padding:6px 8px; border-bottom:1px solid #e3e6ea; }
  td { padding:6px 8px; border-bottom:1px solid #f0f2f5; vertical-align:top; }
  td.mono, code, pre { font-family:ui-monospace,Menlo,monospace; }
  .box { background:#f2f4f6; border:1px solid #e4e8ec; border-radius:8px; padding:10px 12px; margin-bottom:14px; }
  .label { font-size:9.5px; letter-spacing:.08em; text-transform:uppercase; color:#687b8f; margin:0 0 4px; }
  .note { font-size:12px; color:#687b8f; margin-top:10px; line-height:1.5; }
  .tech { border-left:3px solid #cbd5e1; background:#fbfcfd; }
  .tech .label { color:#94a3b8; }
  pre { background:#0f172a; color:#dbe7f3; border-radius:8px; padding:12px; font-size:12px;
        white-space:pre-wrap; max-height:360px; overflow:auto; }
  .warn { color:#b3261e; font-size:12px; }
  .ok { color:#0b7a3e; font-size:12px; }
  .why { background:#eef3fb; border-color:#cfdff5; }
  pre.sql { background:#f6f8fa; color:#1f2937; border:1px solid #e3e8ef; font-size:12px; }
  .why .label { color:#0b4f9c; }
  /* the query box — the same shape retail's chapters use */
  .ask input#aq { width:100%; box-sizing:border-box; padding:8px 10px; border:1px solid #cdd5df;
                  border-radius:8px; font:13px ui-monospace,Menlo,monospace; background:#fff; }
  .ask button#arun { margin-top:8px; background:#0b4f9c; color:#fff; border:0; border-radius:8px;
                     padding:8px 14px; font-size:12px; cursor:pointer; }
  .ex { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
  .runrow { display:flex; gap:8px; align-items:center; }
  .runrow button { margin:0; }
  .runrow button.ghost { background:#eef2f6; color:#0b4f9c; border:1px solid #cfdff5; }
  .aclass { flex:1; min-width:0; padding:7px 9px; font:12px ui-monospace,Menlo,monospace;
            border:1px solid #cdd5df; border-radius:8px; }
  /* the reasoner panel: a separate, clearly-labelled box, so the reader always knows WHICH
     question is being asked and WHICH tool is being asked */
  .reasoner { margin-top:12px; border:1px solid #cfdff5; border-radius:10px; padding:12px 14px;
              background:#f7faff; }
  .reasoner-head { display:flex; flex-direction:column; gap:3px; margin-bottom:10px; }
  .reasoner-title { font-size:12.5px; font-weight:700; color:#0b4f9c; letter-spacing:.3px; }
  .reasoner-why { font-size:11.5px; color:#687b8f; line-height:1.45; }
  .reasoner-q { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:7px;
                font:12.5px ui-monospace,Menlo,monospace; color:#334e68; }
  .reasoner-q .rq-label { font-size:9.5px; letter-spacing:.08em; text-transform:uppercase;
                           color:#94a3b8; background:#eef2f6; border-radius:4px; padding:2px 6px; }
  .reasoner-q code { background:#eef3fb; border:1px solid #d5e3f7; border-radius:6px;
                      padding:3px 8px; font-size:12.5px; color:#0b4f9c; }
  .reasoner-q .rq-radio { display:flex; align-items:center; gap:4px; font-size:11.5px;
                           color:#334e68; cursor:pointer; }
  .reasoner-q .rq-radio input { width:auto; margin:0; }
  /* the button that produced the answer stays lit */
  .runrow button.active { outline:3px solid #f0a202; outline-offset:1px; }
  .runrow button.active.ghost { background:#fff3d6; color:#8a5a00; border-color:#f0a202; }
  .asrc { font-size:11.5px; font-weight:600; margin:2px 0 6px; letter-spacing:.2px; }
  .asrc.query { color:#0b4f9c; }
  .asrc.reasoner { color:#b45309; }
  .scope { display:flex; gap:14px; margin-top:10px; font-size:12px; color:#334e68; }
  .scope label { display:flex; align-items:center; gap:5px; cursor:pointer; }
  .scope input { width:auto; margin:0; }
  .ex button { margin:0; background:#eef2f6; color:#0b4f9c; font-size:11px; padding:4px 9px;
               border:0; border-radius:6px; cursor:pointer; }
  #ares { display:none; margin-top:12px; border-top:1px dashed #e3e6ea; padding-top:10px; }
  #ahead { font:12px ui-monospace,Menlo,monospace; color:#0b4f9c; font-weight:600; }
  #asql { background:#0f172a; color:#dbe7f3; border-radius:8px; padding:10px 12px; font-size:11.5px;
          white-space:pre-wrap; margin:8px 0 0; }
  #arows { width:100%; margin-top:8px; }
  #arows td { font:12px ui-monospace,Menlo,monospace; }
  .hint { font-size:12px; color:#687b8f; margin-top:10px; line-height:1.5; }
"""


def ttl_of(step: str) -> str:
    """The real TTL of one step, minus its teaching comments."""
    text = (STEPS / step).read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#")).strip()


def added_of(step: str) -> str:
    """Only the Turtle THIS step adds — no teaching comments, no section header."""
    text = (STEPS / step).read_text(encoding="utf-8")
    n = int(step[4:6])
    # The step's own block starts at the LAST '── 第 N 步' marker. `rfind` on the bare marker text
    # finds it INSIDE the comment line, so the tail then starts mid-comment and the rest of that
    # comment (the trailing ─── rule) leaks into the page. Start from the beginning of the LINE.
    marker = f"── 第 {n} 步"
    idx = text.rfind(marker)
    if idx >= 0:
        line_start = text.rfind("\n", 0, idx) + 1
        text = text[line_start:]
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#")).strip()


def facts() -> dict:
    """MEASURE the ontology with the real reasoner. Nothing here is hand-written."""
    from features.ontology.reasoning.reasoner import load_graph, reason, mutate

    graph = load_graph([STEPS / "step07.ttl"])
    res = reason(graph, watch_classes=[f"{NS}matches_SoftwareEngineer"])

    pruned, removed = mutate(graph, subject="matches_SoftwareEngineer", predicate="equivalentClass",
                             namespace=NS)
    res2 = reason(pruned, watch_classes=[f"{NS}matches_SoftwareEngineer"])

    def local(iri: str) -> str:
        return iri.split("#")[-1]

    return {
        "consistent": res.consistent,
        "ms": round(res.elapsed_ms),
        "unsat": [local(u) for u in res.unsatisfiable_classes],
        "members": sorted(local(m) for m in res.members_of(f"{NS}matches_SoftwareEngineer")),
        "candidates": sorted(local(m) for m in res.members_of(f"{NS}Candidate")),
        "after_falsify": sorted(local(m) for m in res2.members_of(f"{NS}matches_SoftwareEngineer")),
        "removed": removed,
    }


# ── the seven chapters ───────────────────────────────────────────────────────
def chapters(f: dict) -> list[tuple[str, str, str, str]]:
    members = ", ".join(f["members"]) or "(nobody)"
    out: list[tuple[str, str, str, str]] = []

    # ── 1 ────────────────────────────────────────────────────────────────────
    out.append((
        "step01.ttl", "Create the candidate", "step 1 — the thing itself",
        f"""
      <div class="card">
        <h2>What we add</h2>
        <div class="box"><p class="label">One class, and that is all</p>
          <pre>{added_of('step01.ttl')}</pre>
        </div>
        <div class="box"><p class="label">In plain words</p>
          <p>We write down that <strong>candidates exist</strong>. We do not say anything about them
          yet — this is an empty box labelled “candidates”.</p>
        </div>
        <div class="box why"><p class="label">Why this is first</p>
          <p>You cannot describe something you have not named yet. A field with no person to put it
          on is a blank column.</p>
        </div>
        <div class="box"><p class="label">What the reader sees</p>
          <p>One box on the right, and nothing in it.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>A <strong>class</strong> — a category of thing. In Protégé it sits under
          <code>owl:Thing</code>, the “everything” box at the top.</p>
        </div>
        <h2>What Protégé should show</h2>
        <table><thead><tr><th>Panel</th><th>Expected</th></tr></thead><tbody>
          <tr><td>Classes</td><td>1 row: <code>owl:Thing → Candidate</code></td></tr>
          <tr><td>Data properties</td><td>empty</td></tr>
          <tr><td>Object properties</td><td>empty</td></tr>
          <tr><td>Individuals</td><td>empty</td></tr>
        </tbody></table>
        <p class="note">If you see more than that, you have a different file open.</p>
      </div>

      <div class="card">
        <h2>The goal of the whole course</h2>
        <div class="box"><p class="label">One question</p>
          <p>Build, in seven steps, an ontology that answers
          <strong>“does this person qualify for this job?”</strong> — not from a list someone typed,
          but as a conclusion the machine computes. And when it says no, we can show our working.</p>
        </div>
        <h2>Three rules, stated once</h2>
        <div class="box"><p class="label">① The TBox / ABox line</p>
          <table><thead><tr><th></th><th>TBox (rules)</th><th>ABox (facts)</th></tr></thead><tbody>
            <tr><td>Talks about</td><td>what counts as a match</td><td>who has what</td></tr>
            <tr><td>Subject is</td><td>a class / property / axiom</td><td><strong>a concrete individual</strong></td></tr>
            <tr><td>Example</td><td><code>:hasSkill a owl:ObjectProperty</code></td>
                <td><code>:cand_A :hasSkill :Python</code></td></tr>
          </tbody></table>
          <p class="note">The test: <strong>is the subject a named individual? → fact.
          Is it a class or a property? → rule.</strong></p>
        </div>
        <div class="box"><p class="label">② The value's type decides the panel</p>
          <table><thead><tr><th>Property type</th><th>Value type</th><th>Shows up in</th></tr></thead><tbody>
            <tr><td><code>owl:DatatypeProperty</code></td><td>a number / string (a literal)</td><td>Data properties</td></tr>
            <tr><td><code>owl:ObjectProperty</code></td><td>another <strong>entity</strong></td><td>Object properties</td></tr>
          </tbody></table>
          <p class="note">The easiest thing to get wrong: <code>yearsExperience</code> and
          <code>hasSkill</code> are <strong>both properties of a candidate</strong>, yet one lands in
          the Data panel and the other in the Object panel. What decides the panel is the
          <strong>type of the value</strong> — not which class the property is about.</p>
        </div>
        <div class="box"><p class="label">③ Individuals carry the facts; classes fuel the rules</p>
          <pre>the object of a FACT   → an individual (a concrete thing)   :cand_A :hasSkill :Python
the object of a RULE   → a class (a box)                          ( :hasSkill some :SkillTag )</pre>
        </div>
      </div>""",
    ))

    # ── 2 ────────────────────────────────────────────────────────────────────
    out.append((
        "step02.ttl", "Add their years of experience", "step 2 — the first thing we can say",
        f"""
      <div class="card">
        <h2>What we add</h2>
        <div class="box"><p class="label">One slot on the candidate that holds a number</p>
          <pre>{added_of('step02.ttl')}</pre>
        </div>
        <div class="box"><p class="label">In plain words</p>
          <p>Now we can say “this candidate has 5 years of experience”. The slot belongs to
          candidates, and it only accepts a whole number.</p>
        </div>
        <div class="box why"><p class="label">Why this is next</p>
          <p>It is the simplest thing you can say about a person, and it is the one every job ad
          asks for. It is also a <strong>number</strong>, not a thing — which is why it lives in a
          different place in the tool than a skill will (step 4).</p>
        </div>
        <div class="box"><p class="label">What the reader sees</p>
          <p>Still one box, but now it has a slot on it: <code>yearsExperience</code>.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>A <strong>data property</strong>, holding a literal value like <code>5</code>.
          <code>rdfs:domain</code> says who may have it, <code>rdfs:range</code> says what may go in
          it.</p>
        </div>
        <h2>What Protégé should show</h2>
        <table><thead><tr><th>Panel</th><th>Expected</th></tr></thead><tbody>
          <tr><td>Classes</td><td>1 row (unchanged)</td></tr>
          <tr><td><strong>Data properties</strong></td><td><strong>1 row <code>yearsExperience</code></strong> ← new</td></tr>
          <tr><td>Object properties</td><td>still empty</td></tr>
          <tr><td>Individuals</td><td>still empty</td></tr>
        </tbody></table>
        <p class="note">Click <code>yearsExperience</code> → <strong>Domains: Candidate</strong>,
        <strong>Ranges: xsd:integer</strong>.</p>
      </div>

      <div class="card">
        <h2>“About which class” and “which panel” are two different questions</h2>
        <div class="box"><p class="label">The confusion worth avoiding</p>
          <p>“Which class is this property about?” and “which panel does it show up in?” have
          different answers, and both properties below are about a candidate:</p>
          <table><thead><tr><th>Property</th><th>Panel</th><th>Value type</th></tr></thead><tbody>
            <tr><td class="mono">:yearsExperience</td><td>Data properties</td><td>a number <code>5</code></td></tr>
            <tr><td class="mono">:hasSkill</td><td>Object properties</td><td>another entity <code>:Python</code></td></tr>
          </tbody></table>
          <p class="note">The value's type decides the panel. The class the property is about is a
          separate thing, and it is the same for both.</p>
        </div>
        <h2>Why not the skill link yet?</h2>
        <div class="box"><p class="label">One thing per step</p>
          <p>The obvious second property is “has skill”. But a skill link points at a <em>box</em>,
          and that box does not exist until step 3. Adding both at once would leave the reader
          unable to tell what each one did.</p>
        </div>
      </div>""",
    ))

    # ── 3 ────────────────────────────────────────────────────────────────────
    out.append((
        "step03.ttl", "Add skills as their own kind of thing", "step 3 — a second box",
        f"""
      <div class="card">
        <h2>What we add</h2>
        <div class="box"><p class="label">One more empty box</p>
          <pre>{added_of('step03.ttl')}</pre>
        </div>
        <div class="box"><p class="label">In plain words</p>
          <p>A skill is not a person. “Python” is not a candidate. So skills get their own box,
          separate from the candidate box.</p>
        </div>
        <div class="box why"><p class="label">Why we need this box</p>
          <p>Because <strong>this box is where the skills will go</strong>. In the next steps we
          create the skills themselves — Python, Java — and each one is filed inside this box,
          under a category that says what kind of skill it is.</p>
          <p>So this step is creating the <strong>container</strong>, not the contents. The box
          exists first; the skills go in afterwards.</p>
        </div>
        <div class="box why"><p class="label">Why this is next</p>
          <p>Step 2 showed us a candidate has <strong>two kinds</strong> of information about them:
          numbers (years) and things (skills). Numbers go in a slot; things need a box of their own.</p>
        </div>
        <div class="box"><p class="label">What the reader sees</p>
          <p>Two boxes — and <strong>no connection between them yet</strong>. They are two islands.
          The skills box is still empty; that is the point of this step.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>A second <strong>class</strong>. Two classes with no link between them are two separate
          islands — step 4 joins them.</p>
        </div>
        <h2>What Protégé should show</h2>
        <table><thead><tr><th>Panel</th><th>Expected</th></tr></thead><tbody>
          <tr><td><strong>Classes</strong></td><td><strong>2 rows <code>Candidate</code>, <code>SkillTag</code></strong> ← new (side by side, neither contains the other)</td></tr>
          <tr><td>Data properties</td><td>1 row (unchanged)</td></tr>
          <tr><td>Object properties</td><td>still empty</td></tr>
          <tr><td>Individuals</td><td>still empty — the skills box has nothing in it yet</td></tr>
        </tbody></table>
      </div>

      <div class="card">
        <h2>Remember this: “no relationship yet”</h2>
        <div class="box"><p class="label">The state before the bridge</p>
          <pre>owl:Thing
├── :Candidate      (candidates)
└── :SkillTag       (skills)</pre>
          <p><strong>Two islands, no link between them.</strong></p>
          <p class="note">Step 4 builds the bridge. Keeping this “no relationship yet” state visible
          is the point of stopping here.</p>
        </div>
        <div class="box"><p class="label">And one thing they must never do</p>
          <p>These two boxes must stay <strong>separate kinds of thing</strong>. A person is not a
          skill, and a skill is not a person.</p>
          <p>So we never write <code>:SkillTag rdfs:subClassOf :Candidate</code> — that would say
          “every skill is a candidate”, and the machine would then conclude that every candidate is
          a skill too. The whole model collapses into one meaningless box.</p>
          <p class="note">Worth knowing now: the reason the box is called <code>SkillTag</code> and
          not <code>Skill</code> is that a <em>concrete</em> skill (step 5) is an item <em>tagged</em>
          with a category — <code>:Python a :SkillTag , :Programming</code>. If the box were called
          <code>Skill</code>, that line would read as “Python IS a skill”, which is the confusion
          step 5 exists to clear up.</p>
        </div>
      </div>""",
    ))

    # ── 4 ────────────────────────────────────────────────────────────────────
    out.append((
        "step04.ttl", "Join them: a candidate has a skill", "step 4 — the bridge",
        f"""
      <div class="card">
        <h2>What we add</h2>
        <div class="box"><p class="label">The link from the candidate box to the skill box</p>
          <pre>{added_of('step04.ttl')}</pre>
        </div>
        <div class="box"><p class="label">In plain words</p>
          <p>We write down that a candidate can <strong>have</strong> a skill. The link only points
          one way: candidates have skills; skills do not have candidates.</p>
        </div>
        <div class="box why"><p class="label">Why this is next</p>
          <p>We have both boxes; now we connect them.</p>
        </div>
        <div class="box why"><p class="label">The skills box is an open list</p>
          <p>This link points at a <strong>box</strong>, not at a fixed set of items. We never write
          down “the skills are Python, Java, Excel” as the rule. We say: <em>a candidate may have
          any skill that exists</em>, and the skills themselves arrive later — one at a time, from
          whatever the CVs actually say.</p>
          <p>That matters at scale: on this project 277 CVs mention <strong>hundreds</strong> of
          different skills, and nobody could have listed them in advance. The box stays open; the
          contents are data, not schema.</p>
          <p class="note">This is the difference between a <em>list of skills</em> and a
          <em>kind of skill</em>. The box is a kind; the list inside it grows with the data.</p>
        </div>
        <div class="box"><p class="label">What the reader sees</p>
          <p>An arrow from the candidate box to the skill box — <strong>defined but unused</strong>.
          Nowhere yet does it say <em>who</em> has <em>which</em> skill. That is step 6, and this gap
          is deliberate.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>An <strong>object property</strong> — it points at another thing, not at a number.
          <code>rdfs:domain</code> is the candidate box; <code>rdfs:range</code> is the skill box.</p>
        </div>
        <h2>What Protégé should show</h2>
        <table><thead><tr><th>Panel</th><th>Expected</th></tr></thead><tbody>
          <tr><td><strong>Object properties</strong></td><td><strong>1 row <code>hasSkill</code></strong> ← new</td></tr>
          <tr><td>Classes</td><td>2 rows (unchanged)</td></tr>
          <tr><td>Data properties</td><td>1 row (unchanged)</td></tr>
        </tbody></table>
      </div>

      <div class="card">
        <h2>Two properties, one candidate</h2>
        <table><thead><tr><th>Property</th><th>Panel</th><th>Value type</th><th>Domain</th><th>Range</th></tr></thead><tbody>
          <tr><td class="mono">:yearsExperience</td><td>Data properties</td><td>number <code>5</code></td>
              <td class="mono">:Candidate</td><td class="mono">xsd:integer</td></tr>
          <tr><td class="mono">:hasSkill</td><td>Object properties</td><td>entity <code>:Python</code></td>
              <td class="mono">:Candidate</td><td class="mono">:SkillTag</td></tr>
        </tbody></table>
        <p class="note">Both are properties of a candidate; they land in different panels because
        their values are different kinds of thing.</p>
        <h2>A naming rule we will need later</h2>
        <div class="box"><p class="label">Classes and individuals must not share a name</p>
          <p>If a concrete skill were called <code>CAD</code> and we also built a <em>category</em>
          called <code>CAD</code>, the same name would be both a box and something inside a box —
          and the reasoner would read that as “a thing belonging to itself”. So the categories in
          step 5 are named differently (<code>Programming</code>, not <code>Python</code>).</p>
        </div>
      </div>

      <div class="card">
        <h2>Try it: ask the ontology a question</h2>
        <p>The query runs against <em>this step's file</em> — step 4, not the finished ontology —
        so the answer is the honest one for where we are.</p>
        <p>Two of these <strong>work</strong>, and one <strong>cannot be answered yet</strong>. Both
        outcomes matter: a query that returns nothing could mean the ontology is broken, or it could
        mean the ontology has not got that far yet. You only know which by trying one that works.</p>
        <div class="ask">
          <input id="aq" placeholder="SELECT ?c WHERE {{ ?c a owl:Class }}"/>
          <div class="ex">
            <button data-q="SELECT ?c WHERE {{ ?c a owl:Class }}" data-ok="1">which boxes exist?</button>
            <button data-q="SELECT ?p WHERE {{ ?p a owl:ObjectProperty }}" data-ok="1">which links exist?</button>
            <button data-q="SELECT (COUNT(?c) AS ?n) WHERE {{ ?c a :Candidate }}" data-ok="1">how many candidates?</button>
            <button data-q="SELECT ?c WHERE {{ ?c a :matches_SoftwareEngineer }}" data-ok="0">who qualifies? ✗ needs the reasoner</button>
          </div>
          <div class="scope">
            <label><input type="radio" name="scope" value="all" checked/> the whole ontology</label>
            <label><input type="radio" name="scope" value="step"/> this step only</label>
          </div>
          <button id="arun">Run the query</button>
          <div id="ares">
            <div id="ahead">—</div>
            <div id="asrc" class="asrc"></div>
            <table id="arows" style="display:none"><tbody></tbody></table>
            <pre id="asql"></pre>
            <div class="hint" id="ahint"></div>
          </div>
        </div>
        <div class="box"><p class="label">The same questions, against the whole ontology</p>
          <p>Nothing is locked — the query box is live. Switch <strong>“the whole ontology”</strong>
          on and these questions come back with real rows, because by then the ontology is
          complete.</p>
          <table><thead><tr><th>Question</th><th>The whole ontology</th><th>This step only</th></tr></thead><tbody>
            <tr><td>who are the candidates?</td><td class="ok"><strong>cand_A, cand_B</strong></td>
                <td class="warn">no rows</td></tr>
            <tr><td>who has a skill?</td><td class="ok"><strong>cand_A → Python, cand_B → Python</strong></td>
                <td class="warn">no rows</td></tr>
            <tr><td>which skills exist?</td><td class="ok"><strong>Python</strong></td><td class="warn">no rows</td></tr>
          </tbody></table>
          <p class="note">Type any query into the box and press <strong>Run the query</strong> —
          both scopes answer live. What you see in the left column is the point of this step: the
          link exists, and <strong>nothing uses it yet</strong>. Each later step fills it in.</p>
        </div>
        <div class="box"><p class="label">What each working answer means</p>
          <table><thead><tr><th>Question</th><th>Answer at step 4</th><th>Why</th></tr></thead><tbody>
            <tr><td>which boxes exist?</td><td class="ok"><strong>Candidate, SkillTag</strong></td>
                <td>Two <em>kinds</em> of thing exist — one line each.</td></tr>
            <tr><td>which links exist?</td><td class="ok"><strong>hasSkill</strong></td>
                <td>The link was built in this very step.</td></tr>
            <tr><td>how many candidates?</td><td class="ok"><strong>0</strong></td>
                <td>The query works and the answer is <strong>zero</strong>: the box exists, but
                nobody is in it yet.</td></tr>
          </tbody></table>
          <p><strong>“0” and “no rows” are different answers.</strong> The first says “there are
          none”; the second says “I have nothing to tell you”. Both are honest — and which one you
          get tells you how far the ontology has been built.</p>
          <p class="note">Notice what “how many candidates?” is really asking: it counts the
          <strong>people</strong> in the box. The box itself is described by
          <code>:Candidate a owl:Class</code> — one line, one kind of thing. A box is not one of its
          contents.</p>
          <p class="note">This is how you know an ontology is not finished: <strong>the questions
          you most want to ask are the ones it cannot answer</strong>. Each next step unlocks one —
          step 5 makes “who has a skill?” find a skill, step 6 makes it find people.</p>
        </div>
      </div>""",
    ))

    # ── 5 ────────────────────────────────────────────────────────────────────
    out.append((
        "step05.ttl", "Put a real skill in the skill box", "step 5 — the mistake this course exists to prevent",
        f"""
      <div class="card">
        <h2>What we add</h2>
        <div class="box"><p class="label">One concrete skill, filed under a category</p>
          <pre>{added_of('step05.ttl')}</pre>
        </div>
        <div class="box"><p class="label">In plain words</p>
          <p>“Python” is one <strong>specific</strong> skill — a particular thing, like a name on a
          list. It goes in the skills box, and it is filed as a <strong>programming</strong> skill
          (rather than, say, a spreadsheet skill).</p>
          <p>So after this step you can point at one skill and say what <em>kind</em> of skill it is:</p>
          <pre>:Python  →  a specific skill  →  of kind "programming"</pre>
          <p class="note">This is the shape the whole ontology uses: <strong>the specific thing</strong>
          and <strong>the kind of thing</strong>, kept apart on purpose. Step 7 needs both — the rule
          will say “has a <em>programming</em> skill”, and the machine has to recognise Python as one.</p>
        </div>
        <div class="box why"><p class="label">Why this is next</p>
          <p>The box has been empty for two steps. Now we put something in it.</p>
        </div>
        <div class="box"><p class="label">What the reader sees</p>
          <p>One item inside the skills box, and a narrower box it also belongs to.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p><code>:Python</code> is an <strong>individual</strong> (one named thing);
          <code>:Programming</code> is a <strong>class</strong> (a category, <code>⊑ :SkillTag</code>).
          One sentence gives the individual two types — which is why it is written with a comma:</p>
          <pre>:Python  a  :SkillTag , :Programming .
                   ↑            ↑             ↑
        “Python IS …”   the kind    also the kind
                        of skill    it belongs to</pre>
        </div>
        <h2>What Protégé should show</h2>
        <table><thead><tr><th>Panel</th><th>Expected</th></tr></thead><tbody>
          <tr><td><strong>Individuals</strong></td><td><strong>first entry: <code>Python</code></strong> ← new</td></tr>
          <tr><td><strong>Classes</strong></td><td><strong>3 rows</strong> — <code>Programming</code> is a subclass of <code>SkillTag</code> (expand it to see)</td></tr>
        </tbody></table>
        <p class="note">⚠️ Individuals do <strong>not</strong> appear in the Classes panel — that is
        the usual reason a reader thinks a file is empty.</p>
      </div>

      <div class="card">
        <h2>Which side is this on — the rules, or the facts?</h2>
        <p>This step writes <strong>two kinds of sentence at once</strong>, and they belong to
        different halves of the ontology:</p>
        <pre>:Python  a  :SkillTag , :Programming .      ← a FACT
:Programming  a  owl:Class ;                ← a RULE
              rdfs:subClassOf :SkillTag .</pre>
        <table><thead><tr><th></th><th>The facts (ABox)</th><th>The rules (TBox)</th></tr></thead><tbody>
          <tr><td>Talks about</td><td>particular things</td><td>kinds of things</td></tr>
          <tr><td>Subject is</td><td><strong>a named individual</strong></td><td>a class, a property, an axiom</td></tr>
          <tr><td>Here</td><td class="mono">:Python</td><td class="mono">:Programming, :SkillTag</td></tr>
          <tr><td>Changes when</td><td>new data arrives (a new CV)</td><td>the rules change (rarely)</td></tr>
        </tbody></table>
        <p><strong>The left-hand name decides</strong>, not the file it sits in:
        <code>:Python</code> on the left is a fact; <code>:Programming</code> on the left is a
        rule.</p>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>Why the split matters mechanically: the rule in step 7 points at the <strong>class</strong>
          (<code>someValuesFrom :Programming</code>), and the fact points at the
          <strong>individual</strong> (<code>:Python a :Programming</code>). The reasoner needs that
          bridge — the fact is how a person who has Python reaches a rule about Programming. No
          bridge, no conclusion.</p>
        </div>
      </div>

      <div class="card">
        <h2>The mistake this course exists to prevent</h2>
        <div class="box"><p class="label">Wrong</p>
          <pre>:Python  a  owl:Class .     ← WRONG</pre>
          <p class="warn">Written as a category, “Python” becomes an empty box. Then the rule
          “has a programming skill” matches <strong>nobody at all</strong> — there is no
          <em>thing</em> anyone could have.</p>
        </div>
        <div class="box"><p class="label">Right</p>
          <pre>:Python  a  :SkillTag , :Programming .</pre>
          <p><strong>You cannot have a category. You can have a Python.</strong> The category is
          what you reason over; the item is what someone has. This is the rule of thumb for the
          whole course:</p>
          <p class="note">the thing you can <strong>have</strong> is an individual; the thing you
          can <strong>reason over</strong> is a class.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>That one line is the bridge from facts to rules: the reasoner matches an individual
          <em>whose type is</em> the class, so <code>:Python a :Programming .</code> is what lets
          “has some programming skill” ever fire.</p>
        </div>
      </div>

      <div class="card">
        <h2>Try it: the box finally has something in it</h2>
        <p>Type any query and press <strong>Run the query</strong> — it answers live, right now.
        The toggle chooses <em>which</em> ontology answers: the whole one (the default), or this
        step's file alone.</p>
        <p>Switch to <strong>“this step only”</strong> and watch the skill count: it was
        <strong>0</strong> at step 4 and is <strong>1</strong> now. That is the first time a box in
        this ontology gains a member — and it happened because we added one line.</p>
        <div class="ask">
          <input id="aq" placeholder="SELECT ?s WHERE {{ ?s a :SkillTag }}"/>
          <div class="ex">
            <button data-q="SELECT ?s WHERE {{ ?s a :SkillTag }}" data-ok="1">which skills exist?</button>
            <button data-q="SELECT (COUNT(?s) AS ?n) WHERE {{ ?s a :SkillTag }}" data-ok="1">how many skills?</button>
            <button data-q="SELECT ?c WHERE {{ ?c a owl:Class }}" data-ok="1">which boxes exist?</button>
            <button data-q="SELECT (COUNT(?c) AS ?n) WHERE {{ ?c a :Candidate }}" data-ok="1">how many candidates?</button>
            <button data-q="SELECT ?c WHERE {{ ?c a :matches_SoftwareEngineer }}" data-ok="0">who qualifies? ✗ needs the reasoner</button>
          </div>
          <div class="scope">
            <label><input type="radio" name="scope" value="all" checked/> the whole ontology</label>
            <label><input type="radio" name="scope" value="step"/> this step only</label>
          </div>
          <div class="runrow">
            <button id="arun">Run the query</button>
          </div>
          <div class="reasoner">
            <div class="reasoner-head">
              <span class="reasoner-title">Ask the reasoner instead</span>
              <span class="reasoner-why">a query can only find what was written down — the reasoner
                works out what must be true</span>
            </div>
            <div class="reasoner-q">
              <span class="rq-label">question</span>
              <code>who qualifies as a <span id="rqclass">matches_SoftwareEngineer</span>?</code>
            </div>
            <div class="reasoner-q">
              <span class="rq-label">over</span>
              <span id="rqscope">the whole ontology</span>
              <label class="rq-radio"><input type="radio" name="rscope" value="all" checked/> the whole ontology</label>
              <label class="rq-radio"><input type="radio" name="rscope" value="step"/> this step only</label>
            </div>
            <div class="runrow">
              <button id="areason" class="ghost">Ask the reasoner</button>
              <input id="aclass" class="aclass" value="matches_SoftwareEngineer"
                     title="the class to ask the reasoner about"/>
            </div>
          </div>
          <div id="ares">
            <div id="ahead">—</div>
            <div id="asrc" class="asrc"></div>
            <table id="arows" style="display:none"><tbody></tbody></table>
            <pre id="asql"></pre>
            <div class="hint" id="ahint"></div>
          </div>
        </div>
        <div class="box"><p class="label">What each working answer means</p>
          <table><thead><tr><th>Question</th><th>The whole ontology</th><th>This step only</th><th>Why</th></tr></thead><tbody>
            <tr><td>which skills exist?</td><td class="ok"><strong>Python</strong></td><td class="ok"><strong>Python</strong></td>
                <td>The box has its first member — in this step.</td></tr>
            <tr><td>how many skills?</td><td class="ok"><strong>1</strong></td><td class="ok"><strong>1</strong></td>
                <td>Zero became one. One line of Turtle.</td></tr>
            <tr><td>which boxes exist?</td><td class="ok"><strong>3</strong></td><td class="ok"><strong>3</strong></td>
                <td>The new category <code>:Programming</code> is a third kind of thing.</td></tr>
            <tr><td>how many candidates?</td><td class="ok"><strong>2</strong></td><td class="ok">0</td>
                <td>Two in the finished ontology; <strong>0 here</strong> — we added a skill, not a
                person. That gap is what step 6 closes.</td></tr>
          </tbody></table>
          <p class="note">“Which skills exist?” returning <strong>Python</strong> is the moment the
          ontology stops being a set of empty boxes. Note that
          <code>:Python</code> is one <em>item</em> in a box, and a member of a <em>narrower</em> box
          at the same time — the two types are what make step 7's rule work.</p>
        </div>
        <div class="card">
          <h2>One question that needs <em>reasoning</em> — not just querying</h2>
          <p>Everything above was a question the <strong>files can answer</strong>: the answer was
          written down somewhere in the ontology, and a query finds it.</p>
          <p>Here is a question of a different kind:</p>
          <div class="box"><p class="label">The question</p>
            <pre>SELECT ?c WHERE {{ ?c a :matches_SoftwareEngineer }}</pre>
            <p>“Who qualifies as a software engineer?”</p>
            <p class="note">The ontology names this class <code>:matches_SoftwareEngineer</code> — “matches
            software engineer”, in the client's own language. The query above uses the English
            spelling so this page stays in one language; the ontology keeps the Chinese name.</p>
          </div>
          <p>Run it — in the box above, at <strong>any</strong> scope, including the whole
          ontology:</p>
          <div class="box"><p class="label">What comes back</p>
            <pre>no rows — every time</pre>
            <p>Even on the finished ontology, with every fact in place, the query finds
            <strong>nothing</strong>. And that is not a bug in the query.</p>
          </div>
          <div class="box"><p class="label">Try it yourself</p>
            <p>Type that query in the box above and press <strong>Run the query</strong> — it comes
            back empty. Then press <strong>Ask the reasoner</strong> (the class is already filled
            in) and watch the same question get an answer.</p>
            <pre>Run the query      → no rows
Ask the reasoner  → cand_A</pre>
            <p class="note">Both buttons ask the same question of the same ontology. The only
            difference is which tool answers it — and that is the whole point of this step.</p>
          </div>
          <div class="box"><p class="label">WHY it cannot answer it — the three reasons</p>
            <table><thead><tr><th>#</th><th>Reason</th><th>In the ontology</th></tr></thead><tbody>
              <tr><td>1</td>
                  <td><strong>The rule does not exist yet.</strong> A query can only find answers
                      that were written down. Nobody has written down what “qualifies” means.</td>
                  <td>There is no axiom until step 7 — no
                      <code>owl:equivalentClass</code> anywhere in the file.</td></tr>
              <tr><td>2</td>
                  <td><strong>Even with the rule, the answer is not in the file.</strong> The rule
                      says <em>who should qualify</em>; it does not say <em>who does</em>. Nobody
                      ever writes “cand_A qualifies”.</td>
                  <td><code>:cand_A a :matches_SoftwareEngineer</code> appears in
                      <strong>no</strong> file — writing it would be the answer, and the answer is
                      what we want the machine to produce.</td></tr>
              <tr><td>3</td>
                  <td><strong>SPARQL matches; it does not conclude.</strong> A pattern matches
                      triples that already exist. To get an answer that does not exist yet, something
                      has to <em>infer</em> it — and that is the reasoner's job, not the
                      query's.</td>
                  <td>SPARQL asks “is this triple there?”; the reasoner asks “must this triple be
                      true, given what I know?”</td></tr>
            </tbody></table>
            <p class="note">Reasons 1 and 2 are about the ontology. Reason 3 is about the
            <em>tools</em> — and it is the one that matters most, because it stays true even when
            the ontology is perfect.</p>
          </div>
          <div class="box"><p class="label">This is what step 7 is for</p>
            <p>Step 7 writes the <strong>rule</strong>, and the reasoner applies it. After that, the
            same question has an answer:</p>
            <pre>via SPARQL on the files        → no rows
via the REASONER on the same file → cand_A</pre>
            <p>Both looked at the <em>same</em> ontology. One found nothing, the other found the
            answer. The difference is that the reasoner <strong>concludes</strong> and a query only
            <strong>looks</strong>.</p>
            <p class="note">The platform shows this side by side: its SPARQL endpoint runs every
            query twice — once over the asserted graph, once over the graph plus the inferred
            types — so a reader sees the <code>0 → 1</code> transition instead of being told
            about it.</p>
          </div>
          <div class="box"><p class="label">So how do you know which kind of question you are asking?</p>
            <table><thead><tr><th></th><th>“who has Python?”</th><th>“who qualifies?”</th></tr></thead><tbody>
              <tr><td>Answer lives</td><td>in a file, as a fact</td><td>nowhere — it is inferred</td></tr>
              <tr><td>Found by</td><td>querying</td><td><strong>reasoning</strong></td></tr>
              <tr><td>Needs the axiom?</td><td>no</td><td><strong>yes</strong></td></tr>
              <tr><td>SPARQL can answer it?</td><td>yes</td><td><strong>no</strong></td></tr>
            </tbody></table>
            <p class="note">Until step 7 there is no axiom, so there is nothing to reason over.
            That is why this question has no answer yet — and why step 7 exists.</p>
          </div>
        </div>

        <div class="card">
          <h2>The same question, against the whole ontology</h2>
          <p>Nothing is locked — the query box is live. Switch <strong>“the whole ontology”</strong>
          on and the questions this step cannot answer come back with real rows, because by then
          the ontology is complete.</p>
          <table><thead><tr><th>Question</th><th>This step only</th><th>The whole ontology</th></tr></thead><tbody>
            <tr><td>who are the candidates?</td><td class="warn">no rows</td>
                <td class="ok"><strong>cand_A, cand_B</strong> (with their names)</td></tr>
            <tr><td>who has a skill?</td><td class="warn">no rows</td>
                <td class="ok"><strong>cand_A → Python, cand_B → Python</strong></td></tr>
            <tr><td>how many candidates?</td><td class="ok">0</td><td class="ok"><strong>2</strong></td></tr>
          </tbody></table>
          <p class="note">Type any query into the box and press <strong>Run the query</strong> —
          both scopes answer live, with the real answer, right now. The difference between the two
          columns is exactly what steps 6 and 7 add.</p>
        </div>
      </div>""",
    ))

    # ── 6 ────────────────────────────────────────────────────────────────────
    out.append((
        "step06.ttl", "Now add a real candidate", "step 6 — the first person",
        f"""
      <div class="card">
        <h2>What we add</h2>
        <div class="box"><p class="label">Two people, and what we know about them</p>
          <pre>{added_of('step06.ttl')}</pre>
        </div>
        <div class="box"><p class="label">In plain words</p>
          <p>Here are two real candidates from our files.</p>
          <p><strong>A</strong> knows Python and has been working for <strong>5 years</strong>.
          <strong>B</strong> knows Python too — but has only been working for
          <strong>1 year</strong>.</p>
          <p class="note">Both know the same skill. The only thing that separates them is time on
          the job — and that is exactly what the rule in step 7 will use.</p>
        </div>
        <div class="box why"><p class="label">Why two people, and not one</p>
          <p>So there is something to compare. Both know Python; only one clears the experience bar.
          One person would prove nothing — and when the rule arrives in step 7, we need to watch it
          <em>reject</em> somebody.</p>
        </div>
        <div class="box"><p class="label">What the reader sees</p>
          <p>Two items in the candidate box, each with a skill and a number. The link from step 4 now
          carries something — this is the first time it is used.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>These are <strong>facts</strong> — sentences whose subject is a concrete individual.
          The <code>rdfs:label</code> is a person's name; the reasoner ignores it, but it is what a
          recruiter sees, so the ontology keeps it.</p>
        </div>
        <h2>What Protégé should show</h2>
        <table><thead><tr><th>Panel</th><th>Expected</th></tr></thead><tbody>
          <tr><td><strong>Individuals</strong></td><td><strong>3 rows <code>Python</code>, <code>cand_A</code>, <code>cand_B</code></strong> ← two new</td></tr>
          <tr><td>Classes</td><td>3 rows (unchanged)</td></tr>
        </tbody></table>
        <ul>
          <li>Click <code>Candidate</code> → Instances: <strong>2</strong></li>
          <li>Click <code>cand_A</code> → <code>hasSkill → :Python</code>, <code>yearsExperience → 5</code></li>
          <li>Click <code>Python</code> → <strong>Inverse property values</strong>: <code>cand_A</code>, <code>cand_B</code> (who has it)</li>
        </ul>
      </div>

      <div class="card">
        <h2>The rule of the course, in one table</h2>
        <p>To write “candidate A has the skill Python”, three things must exist at the same time:</p>
        <table><thead><tr><th>#</th><th>What</th><th>Turtle</th><th>Layer</th></tr></thead><tbody>
          <tr><td>1</td><td>the skill <strong>exists</strong></td>
              <td class="mono">:Python a :SkillTag , :Programming .</td><td>fact</td></tr>
          <tr><td>2</td><td>the <strong>verb</strong> exists</td>
              <td class="mono">:hasSkill a owl:ObjectProperty ;<br>  domain :Candidate ; range :SkillTag .</td><td>rule</td></tr>
          <tr><td>3</td><td>the <strong>fact</strong> connects them</td>
              <td class="mono">:cand_A a :Candidate ; :hasSkill :Python .</td><td>fact</td></tr>
        </tbody></table>
        <div class="box"><p class="label">The fact's payload must be an individual</p>
          <pre>:cand_A :hasSkill :Python .      ✅ says WHICH skill
:cand_A :hasSkill :SkillTag .     ❌ only says "has some skill"</pre>
          <p class="note">Point a fact at a class and you can never tell them apart — and the rule
          in step 7 cannot fire.</p>
        </div>
      </div>

      <div class="card">
        <h2>Try it: the questions that were empty now have answers</h2>
        <p>In step 4 the query box answered “no rows” to <em>who has a skill?</em> and <em>who are the
        candidates?</em>. The link existed but nothing used it. Now it does — switch to
        <strong>“this step only”</strong> and they answer.</p>
        <div class="ask">
          <input id="aq" placeholder="SELECT ?c ?l WHERE {{ ?c a :Candidate ; rdfs:label ?l }}"/>
          <div class="ex">
            <button data-q="SELECT ?c ?l WHERE {{ ?c a :Candidate ; rdfs:label ?l }}" data-ok="1">who are the candidates? (with names)</button>
            <button data-q="SELECT ?c ?s WHERE {{ ?c :hasSkill ?s }}" data-ok="1">who has a skill?</button>
            <button data-q="SELECT ?c ?y WHERE {{ ?c :yearsExperience ?y }}" data-ok="1">how many years each?</button>
            <button data-q="SELECT ?c WHERE {{ ?c :yearsExperience ?y . FILTER(?y > 3) }}" data-ok="1">who has 3+ years?</button>
            <button data-q="SELECT ?c ?s WHERE {{ ?c :hasSkill ?s . ?s a :Programming }}" data-ok="1">who has a programming skill?</button>
            <button data-q="SELECT (COUNT(?c) AS ?n) WHERE {{ ?c a :Candidate }}" data-ok="1">how many candidates?</button>
            <button data-q="SELECT ?c WHERE {{ ?c a :matches_SoftwareEngineer }}" data-ok="0">who qualifies? ✗ needs the reasoner</button>
          </div>
          <div class="scope">
            <label><input type="radio" name="scope" value="all" checked/> the whole ontology</label>
            <label><input type="radio" name="scope" value="step"/> this step only</label>
          </div>
          <div class="runrow">
            <button id="arun">Run the query</button>
          </div>
          <div class="reasoner">
            <div class="reasoner-head">
              <span class="reasoner-title">Ask the reasoner instead</span>
              <span class="reasoner-why">a query can only find what was written down — the reasoner
                works out what must be true</span>
            </div>
            <div class="reasoner-q">
              <span class="rq-label">question</span>
              <code>who qualifies as a <span id="rqclass">matches_SoftwareEngineer</span>?</code>
            </div>
            <div class="reasoner-q">
              <span class="rq-label">over</span>
              <span id="rqscope">the whole ontology</span>
              <label class="rq-radio"><input type="radio" name="rscope" value="all" checked/> the whole ontology</label>
              <label class="rq-radio"><input type="radio" name="rscope" value="step"/> this step only</label>
            </div>
            <div class="runrow">
              <button id="areason" class="ghost">Ask the reasoner</button>
              <input id="aclass" class="aclass" value="matches_SoftwareEngineer"
                     title="the class to ask the reasoner about"/>
            </div>
          </div>
          <div id="ares">
            <div id="ahead">—</div>
            <div id="asrc" class="asrc"></div>
            <table id="arows" style="display:none"><tbody></tbody></table>
            <pre id="asql"></pre>
            <div class="hint" id="ahint"></div>
          </div>
        </div>
        <div class="box"><p class="label">What each answer means</p>
          <table><thead><tr><th>Question</th><th>This step</th><th>Whole ontology</th><th>Why</th></tr></thead><tbody>
            <tr><td>who are the candidates? (with names)</td>
                <td class="ok"><strong>cand_A — A — Python, 5 years<br>cand_B — B — Python, 1 year</strong></td>
                <td class="ok">the same two</td>
                <td>The candidate box is no longer empty.</td></tr>
            <tr><td>who has a skill?</td><td class="ok"><strong>cand_A → Python<br>cand_B → Python</strong></td>
                <td class="ok">the same two</td>
                <td>The link from step 4 finally carries something.</td></tr>
            <tr><td>how many years each?</td><td class="ok"><strong>cand_A → 5<br>cand_B → 1</strong></td>
                <td class="ok">the same</td>
                <td>The numbers are filled in.</td></tr>
            <tr><td>who has 3+ years?</td><td class="ok"><strong>cand_A</strong></td>
                <td class="ok">cand_A</td>
                <td>The filter picks out A alone — <strong>this is the answer the rule will reach,
                worked out by hand</strong>.</td></tr>
            <tr><td>who has a programming skill?</td><td class="ok"><strong>cand_A, cand_B</strong></td>
                <td class="ok">cand_A, cand_B</td>
                <td>Both — the chain candidate → skill → category works.</td></tr>
            <tr><td>how many candidates?</td><td class="ok"><strong>2</strong></td><td class="ok">2</td>
                <td>Two people. One of them is about to be rejected by a rule.</td></tr>
          </tbody></table>
          <p class="note">Notice what has <em>not</em> changed: “who qualifies as a software engineer?”
          is still empty, even here. Two people with the same skill and different years is still not
          an answer — until step 7 says what “qualifies” means.</p>
        </div>
        <div class="box"><p class="label">The one query that needs the reasoner</p>
          <p>Every query above could be answered by <strong>looking something up</strong>. This one
          cannot:</p>
          <pre>SELECT ?c WHERE {{ ?c a :matches_SoftwareEngineer }}</pre>
          <p>“Which of our candidates <strong>qualify</strong> as a software engineer?” — and at this
          step, <strong>nobody qualifies, and the machine cannot tell us that</strong>.</p>
          <p class="warn">Look at what we already know about A and B:</p>
          <table><thead><tr><th></th><th>A</th><th>B</th></tr></thead><tbody>
            <tr><td>Is a candidate</td><td class="ok">yes</td><td class="ok">yes</td></tr>
            <tr><td>Knows a programming skill</td><td class="ok">yes (Python)</td><td class="ok">yes (Python)</td></tr>
            <tr><td>Years of experience</td><td class="ok">5</td><td class="warn">1</td></tr>
            <tr><td><strong>Qualifies?</strong></td><td class="warn"><strong>unknown</strong></td>
                <td class="warn"><strong>unknown</strong></td></tr>
          </tbody></table>
          <p>Everything a rule would need is right there. But <strong>“qualifies” has not been
          defined yet</strong> — nobody has written down what the bar is. So:</p>
          <table><thead><tr><th></th><th>SPARQL</th><th>The reasoner</th></tr></thead><tbody>
            <tr><td>Question</td><td>who qualifies?</td><td>who qualifies?</td></tr>
            <tr><td>Same ontology</td><td>step 6's file</td><td>step 6's file</td></tr>
            <tr><td>Answer</td><td class="warn"><strong>no rows</strong></td>
                <td class="warn"><strong>no rows</strong> — “NO AXIOM IN THIS FILE”</td></tr>
          </tbody></table>
          <p><strong>Both fail, for different reasons.</strong></p>
          <ul>
            <li><strong>SPARQL fails</strong> because the answer is not <em>written down</em>. A query
                can only find what somebody already wrote — and nobody wrote “A qualifies”.</li>
            <li><strong>The reasoner fails</strong> because there is <strong>no rule to apply</strong>.
                It can work out what must be true, but only if somebody says what “must be true” is.</li>
          </ul>
          <p>Try it: type that query in the box and press <strong>Run the query</strong> (empty), then
          press <strong>Ask the reasoner</strong> (empty, with “NO AXIOM IN THIS FILE”).</p>
          <p class="note">Both buttons follow the scope toggle, so you can watch the whole thing
          happen: leave it on <strong>“this step only”</strong> and both fail; switch to
          <strong>“the whole ontology”</strong> and the reasoner answers <code>cand_A</code> — because
          step 7's rule is there. Same question, same ontology, one step’s difference.</p>
          <p class="note">That is the whole arc of this course in one comparison: <strong>a query
          finds what was written down; a reasoner works out what must be true</strong> — but only
          once there is a rule to work it out from. Step 7 writes the rule, and then <em>A qualifies
          and B does not</em> — without anybody typing A’s name anywhere.</p>
        </div>
      </div>""",
    ))

    # ── 7 ────────────────────────────────────────────────────────────────────
    out.append((
        "step07.ttl", "Write the rule, and let the machine decide", "step 7 — where the reasoning starts",
        f"""
      <div class="card">
        <h2>What we add</h2>
        <div class="box"><p class="label">The definition of “software engineer”</p>
          <pre>{added_of('step07.ttl')}</pre>
        </div>
        <div class="box"><p class="label">In plain words</p>
          <p>A software engineer is <strong>someone who</strong> is a candidate, <strong>and</strong>
          has a programming skill, <strong>and</strong> has 3 years or more of experience.</p>
          <p class="note">That is the bar. From here on, nobody types anyone's name into the answer —
          the machine works it out from the rule and the facts.</p>
        </div>
        <div class="box why"><p class="label">Why this is last</p>
          <p>Every piece of it must already exist: a candidate (step 1), experience (step 2), skills
          and their category (steps 3–5), and the link that ties them together (step 4). A rule cannot
          mention something that is not there yet.</p>
        </div>
        <div class="box"><p class="label">What the reader sees</p>
          <p>Nothing new in the file — and that is the point. The answer is no longer written down;
          it is <strong>worked out</strong>.</p>
        </div>
        <div class="box tech"><p class="label">Optional technical note</p>
          <p>An <strong>equivalent class</strong> — a definition. The class must have a name
          (<code>a owl:Class</code>); without it the reasoner answers “this class is not in the
          ontology”. And <code>someValuesFrom</code> points at the <strong>category</strong>
          <code>:Programming</code>, not at the bare <code>:SkillTag</code> — otherwise every skill
          would match.</p>
        </div>
        <h2>Run it in Protégé</h2>
        <ol>
          <li>Menu <strong>Reasoner ▸ HermiT</strong> (not the default ELK — see below)</li>
          <li>Menu <strong>Reasoner ▸ Start reasoner</strong></li>
          <li>Switch the Classes dropdown to <strong>Inferred</strong></li>
          <li>Click <code>cand_A</code> → its Types now include <code>matches_SoftwareEngineer</code>,
              shown in <strong>yellow/italic</strong> — Protégé's way of saying “inferred, not
              written”</li>
          <li>Click <code>cand_B</code> → <strong>no</strong> such type</li>
        </ol>
        <div class="box"><p class="label">Measured on this machine</p>
          <table><thead><tr><th>Person</th><th>Qualifies?</th><th>Why</th></tr></thead><tbody>
            <tr><td class="mono">:cand_A</td><td class="ok">yes</td><td>5 years ≥ 3, knows Python</td></tr>
            <tr><td class="mono">:cand_B</td><td class="warn">no</td><td>1 year &lt; 3</td></tr>
          </tbody></table>
          <p class="note">HermiT {f['ms']} ms · consistent: {str(f['consistent']).lower()} ·
          unsatisfiable classes: {f['unsat'] or 'none'} · concluded: {members}</p>
        </div>
      </div>

      <div class="card">
        <h2>Try it: the question that was empty for six steps</h2>
        <p>In step 6 the query box answered <strong>“no rows”</strong> to <em>who qualifies?</em> —
        and told you it could not be answered yet. Now it can. Press
        <strong>Ask the reasoner</strong> and watch it say <code>cand_A</code>.</p>
        <p>But notice what <strong>Run the query</strong> still says: <strong>empty</strong>. That is
        not an oversight — it is the last lesson of the course. The answer was never written down, so
        a query cannot find it. Only the reasoner can work it out.</p>
        <div class="ask">
          <input id="aq" placeholder="SELECT ?c WHERE {{ ?c a :matches_SoftwareEngineer }}"/>
          <div class="ex">
            <button data-q="SELECT ?c WHERE {{ ?c a :matches_SoftwareEngineer }}" data-ok="0">who qualifies? ✗ empty — use the reasoner</button>
            <button data-q="SELECT ?c ?l WHERE {{ ?c a :matches_SoftwareEngineer ; rdfs:label ?l }}" data-ok="0">who qualifies, with names? ✗ empty</button>
            <button data-q="SELECT ?c ?y WHERE {{ ?c a :matches_SoftwareEngineer ; :yearsExperience ?y }}" data-ok="0">who qualifies, and for how long? ✗ empty</button>
            <button data-q="SELECT (COUNT(?c) AS ?n) WHERE {{ ?c a :matches_SoftwareEngineer }}" data-ok="0">how many qualify? ✗ says 0 — and that zero is misleading</button>
            <button data-q="SELECT ?c ?l WHERE {{ ?c a :Candidate ; rdfs:label ?l }}" data-ok="1">who are the candidates? ✓ works</button>
          </div>
          <div class="scope">
            <label><input type="radio" name="scope" value="all" checked/> the whole ontology</label>
            <label><input type="radio" name="scope" value="step"/> this step only</label>
          </div>
          <div class="runrow">
            <button id="arun">Run the query</button>
          </div>
          <div class="reasoner">
            <div class="reasoner-head">
              <span class="reasoner-title">Ask the reasoner instead</span>
              <span class="reasoner-why">a query can only find what was written down — the reasoner
                works out what must be true</span>
            </div>
            <div class="reasoner-q">
              <span class="rq-label">question</span>
              <code>who qualifies as a <span id="rqclass">matches_SoftwareEngineer</span>?</code>
            </div>
            <div class="reasoner-q">
              <span class="rq-label">over</span>
              <span id="rqscope">the whole ontology</span>
              <label class="rq-radio"><input type="radio" name="rscope" value="all" checked/> the whole ontology</label>
              <label class="rq-radio"><input type="radio" name="rscope" value="step"/> this step only</label>
            </div>
            <div class="runrow">
              <button id="areason" class="ghost">Ask the reasoner</button>
              <input id="aclass" class="aclass" value="matches_SoftwareEngineer"
                     title="the class to ask the reasoner about"/>
            </div>
          </div>
          <div id="ares">
            <div id="ahead">—</div>
            <div id="asrc" class="asrc"></div>
            <table id="arows" style="display:none"><tbody></tbody></table>
            <pre id="asql"></pre>
            <div class="hint" id="ahint"></div>
          </div>
        </div>
        <div class="box"><p class="label">The answer, and the one thing that is still empty</p>
          <table><thead><tr><th>Question</th><th>SPARQL</th><th>The reasoner</th></tr></thead><tbody>
            <tr><td>who qualifies?</td><td class="warn"><strong>no rows</strong></td>
                <td class="ok"><strong>cand_A</strong></td></tr>
            <tr><td>how many qualify?</td><td class="warn"><strong>0</strong> — and that zero is
                <em>misleading</em>: it says “none of the triples I can see match”, not “nobody
                qualifies”</td><td class="ok"><strong>1</strong></td></tr>
          </tbody></table>
          <p class="warn">That row is worth pausing on. A count of <strong>0</strong> from a query
          looks like an answer — “nobody qualifies”. It is not: it is the count of rows the query
          could <em>see</em>. Only the reasoner's number (1) means what a recruiter means by
          “how many qualify”.</p>
          <p class="note">The query still finds nothing — and now that is not a failure but a
          <strong>fact</strong>: the answer was never written down. The reasoner says
          <code>cand_A</code> because it worked the answer out from the rule.</p>
        </div>
      </div>

      <div class="card">
        <h2>The payoff — and how we prove it</h2>
        <div class="box"><p class="label">Nobody wrote this down</p>
          <pre>:cand_A a :matches_SoftwareEngineer .     ← NEVER write this</pre>
          <p>The rule says it and the machine works it out. To prove the machine worked it out —
          rather than us having typed it — <strong>delete the rule</strong> and run it again:</p>
          <pre>before deleting the axiom : matches_SoftwareEngineer → {members}
after  deleting the axiom : matches_SoftwareEngineer → {f['after_falsify'] or '[]'}</pre>
          <p class="ok">The answer disappears with the rule. That test is the difference between a
          system that <em>describes</em> and one that <em>decides</em>.</p>
        </div>
        <h2>How is this different from a plain SQL query?</h2>
        <p>Same question, two ways of asking it. A SQL query states the <em>question</em>:</p>
        <pre class="sql">SELECT c.name
FROM candidate c
JOIN candidate_skill cs ON cs.candidate_id = c.id
WHERE cs.skill_id IN (SELECT skill FROM skill WHERE category = 'Programming')
  AND c.years_experience >= 3;</pre>
        <p>The ontology states the <em>rule</em>, and gives the answer a name:</p>
        <pre class="sql">:matches_SoftwareEngineer  ≡
      :Candidate
   ⊓  ( :hasSkill       some :Programming )
   ⊓  ( :yearsExperience some xsd:integer[>=3] )</pre>
        <p>Both answer “who qualifies”. Three differences matter in daily work:</p>
        <table><thead><tr><th></th><th>A SQL query</th><th>The ontology</th></tr></thead><tbody>
          <tr><td><strong>Where the rule lives</strong></td>
              <td>copied into <em>every</em> query that needs it</td>
              <td>written <strong>once</strong>, as the definition of a named class</td></tr>
          <tr><td><strong>The bar changes from 3 years to 5</strong></td>
              <td>hunt down every saved search, dashboard, report and job that hardcoded
                  <code>&gt;= 3</code> — and they drift apart</td>
              <td>change <strong>one line</strong>; every consumer of
                  <code>matches_SoftwareEngineer</code> changes with it</td></tr>
          <tr><td><strong>Where the answer is</strong></td>
              <td>a row in a table — something to refresh, and to go stale</td>
              <td><strong>nowhere</strong>: it is computed on demand, so it cannot be stale</td></tr>
        </tbody></table>
        <div class="box"><p class="label">The one that bites: “filed by years of experience”</p>
          <p>Your question was exactly right. In SQL, <code>years_experience &gt;= 3</code> is
          <em>copied</em> into every query that filters on experience. Five queries, five copies, and
          when the bar moves you have to find all five — the ones somebody forgot are now quietly
          wrong.</p>
          <p>In the ontology the bar is <strong>one fact about the role</strong>. It is not written
          into the queries at all: a query asks for <code>matches_SoftwareEngineer</code>, and the
          rule brings the years condition with it.</p>
        </div>
        <div class="box"><p class="label">Where the ontology stops</p>
          <p>It is not a replacement for SQL — it is a different layer. The ontology decides
          <em>who qualifies</em> and gives that answer a name; SQL does what you do with those
          people (totals, rankings, exports). Questions that need an aggregate are SQL's job.</p>
          <p class="note">On this project the two are literally joined: the ontology's classes are
          compiled into SQL (a definition becomes a <code>WHERE</code> clause), and the metrics are
          computed over that. The definition is written once.</p>
        </div>
        <h2>Why the reasoner choice matters</h2>
        <div class="box"><p class="label">HermiT vs ELK / OWL 2 RL</p>
          <table><thead><tr><th>Reasoner</th><th>This axiom</th><th>Why</th></tr></thead><tbody>
            <tr><td><strong>HermiT</strong></td><td class="ok">concludes {members}</td>
                <td>it can decide the “3 years or more” threshold</td></tr>
            <tr><td>ELK / OWL 2 RL</td><td class="warn">concludes nobody</td>
                <td>OWL 2 RL does not decide numeric limits</td></tr>
          </tbody></table>
          <p class="warn">The weaker reasoner gives an <strong>empty answer</strong> — which reads as
          “nobody qualifies”, not “the tool cannot judge this”. Recruiting decisions are mostly
          thresholds, so this course must use HermiT.</p>
        </div>
        <h2>The whole story on one line</h2>
        <div class="box"><p class="label">Seven steps</p>
          <pre>1  a candidate
2  their years
3  skills exist
4  candidates have skills
5  Python is a real skill
6  A has Python and 5 years · B has Python and 1 year
7  software engineer = candidate + programming skill + 3+ years</pre>
        </div>
        <div class="box"><p class="label">What the machine says, and what nobody wrote</p>
          <p>A qualifies. B does not. And in no file — not in <code>abox.ttl</code>, not in
          <code>reasoning.ttl</code>, not in any of the seven step files — does it say so. That
          single line was <strong>computed</strong>.</p>
        </div>
      </div>""",
    ))

    return out


def nav(active: int, all_chapters: list) -> str:
    links = []
    for n, (_, title, _, _) in enumerate(all_chapters, 1):
        cls = ' class="on"' if n == active else ""
        links.append(f'<a href="/api/ontology/{KEY}/tutorial/chapter/{n}"{cls}>{n}. {title}</a>')
    return "".join(links)


#: the steps this build draws. Steps 1–4 are done; step 5 is being done now; 6–7 are written
#: but not yet drawn — the shell says so rather than pretending.
DRAWN = [1, 2, 3, 4, 5, 6, 7]

#: the steps that carry a query box
QUERY_STEPS = [4, 5, 6, 7]

#: A stamp that changes whenever the chapters are rebuilt. It is printed on every page, so a
#: browser showing an OLD page is visible at a glance instead of being quietly wrong.
BUILD_STAMP = "2026-11-15-a" 

#: The query box's behaviour. It runs against THAT STEP's file — so a question the reader asks
#: early gets the honest "not yet" answer, and the chapter can say which step unlocks it.
QUERY_JS = """
<script>
(function () {
  const STEP = __STEP__;
  const F = (id) => document.getElementById(id);
  // WHICH ONTOLOGY ANSWERS: this step's file, or the complete one. Resolved ONCE, here, so both
  // buttons use the same answer — it used to be computed inside `run()` only, and `askReasoner()`
  // then read an undefined `step` and died with "Can't find variable: step".
  function scopeOf() {
    const picked = document.querySelector('input[name=scope]:checked');
    return (picked && picked.value) || 'all';
  }
  function stepOf() {
    return scopeOf() === 'all' ? 'all' : STEP;
  }
  function scopeLabel() {
    return scopeOf() === 'all' ? 'the whole ontology' : 'step ' + STEP;
  }
  // The reasoner panel carries its OWN radios: asking the reasoner is a different act from running
  // a query, and the reader should be able to say "reason over the whole ontology" while still
  // querying this step. Both sets of radios stay in sync with what they describe.
  function reasonerScope() {
    const picked = document.querySelector('input[name=rscope]:checked');
    return (picked && picked.value) || 'all';
  }
  function reasonerStep() {
    return reasonerScope() === 'all' ? 'all' : STEP;
  }
  function paintReasonerQuestion() {
    const cls = (F('aclass') || {}).value || 'matches_SoftwareEngineer';
    const c = F('rqclass'); if (c) c.textContent = cls;
    const s = F('rqscope');
    if (s) s.textContent = reasonerScope() === 'all' ? 'the whole ontology' : 'step ' + STEP;
  }
  // WHICH BUTTON DID THE READER PRESS? The answer panel says so, and the button stays lit — so a
  // reader who pressed "Ask the reasoner" can see at a glance WHICH tool produced the number.
  function markSource(which) {
    const q = F('arun'), r = F('areason');
    if (q) q.classList.toggle('active', which === 'query');
    if (r) r.classList.toggle('active', which === 'reasoner');
    const badge = F('asrc');
    if (badge) {
      badge.textContent = which === 'reasoner'
        ? 'answered by the REASONER (worked out from the rule)'
        : 'answered by a QUERY (found in the file)';
      badge.className = 'asrc ' + which;
    }
  }

  const ex = document.querySelectorAll('.ex button');
  ex.forEach(b => b.addEventListener('click', () => {
    F('aq').value = b.dataset.q;
    // the button says whether this query is expected to work at this step
    run(b.dataset.ok === '1');
  }));
  F('arun').addEventListener('click', () => { markSource('query'); run(); });
  F('areason').addEventListener('click', () => { markSource('reasoner'); askReasoner(); });
  F('aq').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { markSource('query'); run(); } });
  document.querySelectorAll('input[name=rscope]').forEach(r =>
    r.addEventListener('change', paintReasonerQuestion));
  const aclass = F('aclass');
  if (aclass) aclass.addEventListener('input', paintReasonerQuestion);
  paintReasonerQuestion();

  async function run(expectOk) {
    const q = F('aq').value.trim();
    if (!q) return;
    // WHICH ONTOLOGY ANSWERS: this step's file, or the complete one. The reader picks — the box
    // is live either way, and both answers are real.
    const scope = scopeOf();
    const step = stepOf();
    F('ares').style.display = 'block';
    F('ahead').textContent = 'asking ' + scopeLabel() + '…';
    F('asql').textContent = '';
    F('ahint').textContent = '';
    const rows = F('arows');
    rows.style.display = 'none';
    rows.querySelector('tbody').innerHTML = '';
    let j;
    try {
      j = await (await fetch('/api/ontology/__KEY__/wb/stepquery?step=' + step +
                             '&query=' + encodeURIComponent(q))).json();
    } catch (e) {
      F('ahead').textContent = 'request failed: ' + e;
      return;
    }
    // SHOW WHAT CAME BACK. A tutorial that swallows the raw answer is a tutorial nobody can debug:
    // if the answer is wrong, the reader must be able to see what the server actually said.
    F('asql').textContent = 'query → ' + j.file + '  (' + j.triples + ' triples)\\n' + q +
                            '\\nserver said: ' + JSON.stringify(j).slice(0, 400);
    const body = rows.querySelector('tbody');
    const isError = (j.rows && j.rows.length === 1 && String(j.rows[0][0] || '').startsWith('QUERY ERROR'));
    if (isError) {
      F('ahead').textContent = 'QUERY ERROR';
      F('ahint').textContent = String(j.rows[0][0]);
      return;
    }
    if (!j.rows || !j.rows.length) {
      F('ahead').textContent = 'no rows';
      F('ahint').textContent = expectOk === false
        ? 'As expected at step ' + STEP + ': the ontology cannot answer this yet. The next steps are what unlock it — or switch to “the whole ontology” to see the finished answer.'
        : (scope === 'all'
            ? 'The whole ontology has nothing to say about this yet either.'
            : 'The ontology at step ' + STEP + ' has nothing to say about this yet. Switch to “the whole ontology” to see the finished answer.');
      return;
    }
    F('ahead').textContent = (expectOk === false ? 'rows (not expected to work yet) — ' : '') +
                             j.rows.length + ' row' + (j.rows.length === 1 ? '' : 's');
    (j.columns || []).forEach(c => {
      const tr = document.createElement('tr');
      const th = document.createElement('td');
      th.textContent = c;
      th.style.fontWeight = '600';
      tr.appendChild(th);
      body.appendChild(tr);
    });
    j.rows.forEach(r => {
      const tr = document.createElement('tr');
      r.forEach(v => {
        const td = document.createElement('td');
        td.textContent = v;
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    rows.style.display = 'table';
  }

  // ASK THE REASONER. SPARQL can only FIND what is in the files; the reasoner CONCLUDES what must
  // be true. This button runs the real reasoner over the ontology and shows both numbers — what was
  // asserted, and what was entailed — because the difference between them IS the lesson.
  async function askReasoner() {
    const cls = (F('aclass') || {}).value || 'matches_SoftwareEngineer';
    const step = reasonerStep();
    F('ares').style.display = 'block';
    F('ahead').textContent = 'asking: who qualifies as a ' + cls + '?  ·  over ' +
      (reasonerScope() === 'all' ? 'the whole ontology' : 'step ' + STEP) + '…';
    F('asql').textContent = '';
    F('ahint').textContent = '';
    const rows = F('arows');
    rows.style.display = 'none';
    rows.querySelector('tbody').innerHTML = '';
    let j;
    try {
      // the STEP-SCOPED reasoner: it reasons over the same file the query box reads, so at
      // step 6 it honestly says "nothing yet" — the platform's own /reason always answers from
      // the finished ontology, which would show step 7's answer while the reader is at step 6.
      j = await (await fetch('/api/ontology/__KEY__/wb/stepreason?step=' + step +
                             '&class=' + encodeURIComponent(cls))).json();
    } catch (e) {
      F('ahead').textContent = 'request failed: ' + e;
      return;
    }
    if (!j.ok) {
      F('ahead').textContent = 'the reasoner could not answer';
      F('ahint').textContent = j.error || j.detail || '(no detail)';
      return;
    }
    F('asql').textContent = 'reasoner → ' + j.engine + ' · ' + j.elapsed_ms + ' ms\\n' +
      'file ' + j.file + ' · asserted ' + j.asserted + ' · entailed ' + j.entailed +
      (j.has_axiom === false ? ' · NO AXIOM IN THIS FILE' : '');
    const body = rows.querySelector('tbody');
    const head = document.createElement('tr');
    ['candidate', 'how it got there'].forEach(c => {
      const td = document.createElement('td');
      td.textContent = c;
      td.style.fontWeight = '600';
      head.appendChild(td);
    });
    body.appendChild(head);
    (j.rows || []).forEach(r => {
      const tr = document.createElement('tr');
      const a = document.createElement('td');
      a.textContent = r;
      tr.appendChild(a);
      const b = document.createElement('td');
      b.textContent = 'asserted ' + j.asserted + ' → entailed ' + j.entailed +
                      ' (the reasoner worked it out)';
      tr.appendChild(b);
      body.appendChild(tr);
    });
    rows.style.display = 'table';
    if (j.rows && j.rows.length) {
      F('ahint').textContent = 'The file says NOTHING about this candidate. The reasoner concluded '
                             + 'it from the axiom — that is why it is not written down anywhere.';
    } else if (j.has_axiom === false) {
      F('ahint').textContent = 'Nothing entailed, and this file has no axiom yet: '
                             + 'the reasoner has no rule to apply. Step 7 writes it.';
    } else {
      F('ahint').textContent = 'Nothing entailed.';
    }
  }
})();
</script>
"""


def main() -> int:
    f = facts()
    OUT.mkdir(parents=True, exist_ok=True)
    all_chapters = chapters(f)[:len(DRAWN)]
    for n, (ttl_file, title, subtitle, body) in enumerate(all_chapters, 1):
        # the query box's JavaScript — only where there IS a query box
        query_js = ""
        if n in QUERY_STEPS:
            query_js = QUERY_JS.replace("__STEP__", str(n)).replace("__KEY__", KEY)
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Cache-Control" content="no-store">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Step {n} — {title}</title>
<style>{CSS}</style></head>
<body data-key="{KEY}">
<header><h1>Step {n} — {title}</h1>
  <span class="rev">{subtitle} · {n}/{len(all_chapters)} · {KEY} · build {BUILD_STAMP}</span></header>
<nav>{nav(n, all_chapters)}</nav>
<main><div class="cols">
{body}
</div></main>
{query_js}
</body></html>
"""
        (OUT / f"step{n}.html").write_text(html, encoding="utf-8")
        print(f"wrote {OUT / f'step{n}.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

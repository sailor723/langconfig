#!/usr/bin/env python3
"""Generate this repository's skills from the vendored upstream sets.

Two upstream collections are vendored under `vendor/upstream-skills/` (both MIT, licences beside them):

  mattpocock/skills        engineering process skills (grilling, to-spec, to-tickets, tdd, code-review…)
  langchain-ai/langchain-skills   the ecosystem layer (LangChain / LangGraph / Deep Agents)

This script turns each upstream `SKILL.md` into one of ours: our frontmatter fields, our paths, our tool
names, our verification floor — plus a provenance block naming the upstream commit-agnostic path and what
was changed. It is deterministic, so regenerating is a diff a reviewer can read, and
`backend/tests/test_imported_skills.py` pins the properties that must hold for every generated file.

    ./scripts/import_upstream_skills.py --dry-run        # what would be written
    ./scripts/import_upstream_skills.py                  # write them
    ./scripts/import_upstream_skills.py --only grilling  # one skill

What the transform does, and why each part exists:

1. **Frontmatter.** Upstream uses `name` + `description` (and Claude-specific `disable-model-invocation`).
   Ours needs `name`, `description`, `tags`, `triggers`, `allowed_tools`, `author`, `version` — the app's
   loader reads exactly these, and the UI groups by `source_type`. `disable-model-invocation` has no
   equivalent here (our `skill` tool is on-demand and every skill is discoverable), so it is dropped and the
   fact is recorded in the provenance block instead of being silently lost.
2. **Paths.** Matt's skills assume `.agents/plans/`, an issue tracker and `/setup-matt-pocock-skills`. This
   repository keeps specs in `docs/specs/`, tickets in `docs/tickets/` and per-scope notes in
   `work/<scope>/`. A skill that points at a directory nobody has is worse than no skill.
3. **Tools.** Upstream names Claude Code tools (`Read`, `Edit`, `Bash`, `Task`). Ours are
   `read_file`, `edit_file`, `bash`, `task`, `grep`, `glob`, `python_execute`, `skill` … A skill that tells
   the agent to call a tool it does not have burns a turn discovering that.
4. **The verification floor.** This repository has a real one, and the skills must use it rather than
   invent a generic "run the tests": `./scripts/housekeeping_verify.sh`, `tsc` + `vite build` for the
   frontend, and a backend suite that already has 20 failures — so "not worse than the baseline" is the
   honest criterion, not "green".
5. **Ecosystem layer.** Skills that touch agent code carry a line naming which layer the change belongs to
   (LangChain `create_agent` / LangGraph graph / Deep Agents harness). That rule comes from the official
   `ecosystem-primer` skill vendored beside this script, and it is the one thing our own skills never said.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "upstream-skills"
OUT = REPO / "backend" / "skills" / "builtin"

#: Upstream id → our id, only where the two must differ.
#: `music` style collisions (a skill we already wrote from the same upstream) are SKIPPED, because our
#: version is the adapted one; the script reports them rather than duplicating.
RENAME: dict[str, str] = {}
#: Skills whose upstream id already exists here, written BY US from the same source. Regenerating them
#: would replace a tested, repo-specific skill with the upstream text.
OURS_FROM_SAME_SOURCE = {"grilling", "to-spec", "to-tickets"}

#: Ids where the upstream version REPLACES ours, and our old body is preserved as a support file.
REPLACE_KEEPING_OURS_AS = {"code-review": "STANDARDS-CHECKLIST.md"}

#: Upstream path conventions → ours (applied to the body, longest first).
PATH_REWRITES: list[tuple[str, str]] = [
    (".agents/plans/", "docs/specs/"),
    (".agents/plans", "docs/specs"),
    ("acceptance_criteria.md", "docs/specs/<slug>.md"),
    (".agents/acceptance_criteria.md", "docs/specs/<slug>.md"),
    (".agents/execution-reports/", "docs/tickets/"),
    ("docs/adr/", "docs/adr/"),
    ("/setup-matt-pocock-skills", "`Skills` activity (or this file's Setup section)"),
    ("the issue tracker", "`docs/tickets/`"),
    ("issue tracker", "`docs/tickets/`"),
    ("your issue tracker", "`docs/tickets/`"),
]

#: Claude Code tool names → ours.
#:
#: Measured: a plain word-boundary rewrite turned the imperative *verb* into a tool name — "Read the spec
#: and tickets" became "read_file the spec and tickets" in 26 places, which is not a sentence. A tool is
#: named only when the text is talking ABOUT it: inside backticks, after "the", or before "tool".
TOOL_REFERENCE = [
    (re.compile(r"`Read`"), "`read_file`"),
    (re.compile(r"`Write`"), "`write_file`"),
    (re.compile(r"`Edit`"), "`edit_file`"),
    (re.compile(r"`Bash`"), "`bash`"),
    (re.compile(r"`Grep`"), "`grep`"),
    (re.compile(r"`Glob`"), "`glob`"),
    (re.compile(r"`Task`"), "`task`"),
    (re.compile(r"\bthe (Read|Write|Edit|Bash|Grep|Glob|Task) tool\b"),
     lambda m: "the `" + {"Read": "read_file", "Write": "write_file", "Edit": "edit_file", "Bash": "bash",
                          "Grep": "grep", "Glob": "glob", "Task": "task"}[m.group(1)] + "` tool"),
    (re.compile(r"\bWebFetch\b"), "web_fetch"),
    (re.compile(r"\bWebSearch\b"), "web_search"),
]

#: Which of our tool ids a skill may be expected to use, by keyword. Only a hint for `allowed_tools`.
TOOL_HINTS: dict[str, list[str]] = {
    "read": ["read_file", "grep", "glob"], "write": ["write_file", "edit_file"],
    "test": ["bash", "python_execute"], "git": ["bash"], "commit": ["bash"],
}

#: The floor every skill in this repo is held to (used by the generated `## This repository` section).
FLOOR = """\
## This repository's floor

- **Verify with the real commands**, not by eye: `./scripts/housekeeping_verify.sh` (guards + `tsc` +
  `vite build` + a document-store report). Add `--full-suite` for the backend suite.
- **The backend suite has 20 pre-existing failures.** "Not worse than that baseline" is the honest
  criterion; "the tests are green" is not a claim you can make here. Compare with
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  and diff the `FAILED` lines against the recorded baseline.
- **Specs, tickets and notes live in files**: `docs/specs/<slug>.md`, `docs/tickets/NNN-<slug>.md`,
  `work/<scope>/`. A verdict in a chat message is lost by the next turn.
- **Ecosystem layer**: agent code is LangChain (`create_agent`) inside a LangGraph runtime, usually wrapped
  by a Deep Agents harness (`deepagents`). Decide which layer the change belongs to before writing it — the
  `ecosystem-primer` rule — and prefer the highest layer that does the job.
"""

SKILL_SLASH = re.compile(
    r'(?<![`\w])/(to-spec|to-tickets|to-validation|grill-me|grilling|tdd|code-review|implement|implement-spec|triage|pr|retro|teach|handoff|wizard|ask-matt|prototype|wayfinder|setup-matt-pocock-skills)(?![\w`])')

PROVENANCE_TEMPLATE = """\
> **Provenance.** Adapted from `{upstream}` (MIT, vendored at `{vendor_path}`).
> Changed for this repository: frontmatter fields (`tags` / `triggers` / `allowed_tools` / `author` /
> `version`), path conventions (`docs/specs`, `docs/tickets`, `work/<scope>`), tool names
> (`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`), and a verification floor
> section. Upstream's `disable-model-invocation` has no equivalent here — every skill is discoverable
> through the `skill` tool, so it is dropped rather than emulated.
"""



def _yaml_scalar(value: str) -> str:
    """Always-quote a YAML scalar.

    Measured: writing descriptions unquoted broke five skills — a description containing `: ` or a
    backtick is not valid plain YAML, so the loader reported "Invalid YAML in frontmatter" and the skill
    vanished from the library. Quoting unconditionally costs nothing in readability and cannot break.
    """
    text = " ".join(str(value).split())
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal frontmatter reader: the upstream files use flat `key: value` pairs."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    block, body = text[3:end], text[end + 4:]
    fields: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            fields[key] = m.group(2).strip().strip('"')
        elif key and line.strip():
            fields[key] += " " + line.strip().strip('"')
    return fields, body.lstrip("\n")


def _title(skill_id: str) -> str:
    words = re.split(r"[-_]", skill_id)
    small = {"a", "an", "the", "of", "to", "and", "for", "in", "on", "with"}
    out = []
    for i, w in enumerate(words):
        out.append(w.capitalize() if (i == 0 or w not in small) else w)
    return " ".join(out)


def _triggers(skill_id: str, desc: str, body: str) -> list[str]:
    """Derive the trigger list from the description's 'Use when …' branches, else from the first H2s."""
    found: list[str] = []
    for m in re.finditer(r"[Uu]se (?:this skill )?(?:when|for|before|after|any time)\s+([^.;]+)", desc):
        found.append(m.group(1).strip().rstrip(".,").capitalize())
    if not found:
        # a router-style skill (upstream: "Call the Skill tool with X") says what it is in one line
        first_line = next((ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")), "")
        if first_line:
            found.append("When asked to " + first_line[0].lower() + first_line[1:].rstrip(".")[:100])
    seen, out = set(), []
    for f in found:
        k = f.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(f[:110])
    if not out:
        words = " ".join(re.split(r"[-_]", skill_id))
        first = desc.split(".")[0].strip()[:80]
        out = [f'When the user asks to "{words}"', f"When the task is: {first}"] if first else [f'When the user asks to "{words}"']
    return out[:5]


def _tags(skill_id: str, desc: str, collection: str) -> list[str]:
    base = [w for w in re.split(r"[-_]", skill_id) if w]
    extra = [collection]
    for kw, tag in (("review", "review"), ("test", "testing"), ("spec", "requirements"),
                    ("ticket", "planning"), ("bug", "debugging"), ("skill", "skills"),
                    ("design", "design"), ("research", "research"), ("langgraph", "langgraph"),
                    ("langchain", "langchain"), ("deep agents", "deepagents")):
        if kw in desc.lower() or kw in skill_id:
            extra.append(tag)
    return list(dict.fromkeys(base + extra))[:6]


def _allowed_tools(body: str) -> list[str]:
    low = body.lower()
    tools = ["read_file", "grep", "glob"]
    if any(w in low for w in ("write", "create a file", "edit", "spec file", "ticket")):
        tools += ["write_file", "edit_file"]
    if any(w in low for w in ("run ", "command", "test", "git ", "typecheck", "build")):
        tools.append("bash")
    if "subagent" in low or "sub-agent" in low or "background agent" in low:
        tools.append("task")
    if "skill" in low:
        tools.append("skill")
    return list(dict.fromkeys(tools))[:8]


SETUP_SENTENCE = re.compile(
    r"[Tt]he (?:issue tracker|`?docs/tickets/`?) should have been provided to you\.?\s*"
    r"If not, tell the user to run `*/?setup-matt-pocock-skills`*\.?",
)


def _rewrite_body(body: str, skill_id: str) -> str:
    # One sentence, handled before anything else touches it (see the note in SETUP_SENTENCE's spellings).
    body = re.sub(r"\*\*`?`?/?setup-matt-pocock-skills`?`?\*\*",
                  "**Skills activity → setup notes**", body)
    body = re.sub(r"tell the user to run `?`?/?setup-matt-pocock-skills`?`?",
                  "say that the tracker, label and doc-layout vocabulary must be configured first "
                  "(Skills activity \u2192 setup notes)", body)
    # "The issue tracker should have been provided to you. If not, tell the user to run …" — the whole
    # sentence, because patching only its tail left an awkward lead-in behind ("The `docs/tickets/`
    # should have been provided to you. If not, say that …").
    body = re.sub(
        r"[Tt]he (?:issue tracker|`?docs/tickets/`?)[^.]{0,60}should have been provided to you\.?[^.]*\.",
        "The tickets for this work live in `docs/tickets/`; if there are none, say so and ask for the spec "
        "rather than inventing one.", body)
    body = re.sub(
        r"The mapping should have been provided to you\.\s*If not,[^.]*\.",
        "The label mapping lives in `docs/tickets/`; if the tickets carry no labels, ask for the mapping "
        "before triaging anything.", body)
    body = SETUP_SENTENCE.sub(
        "The tickets for this work live in `docs/tickets/`; if there are none, say so and ask for the spec "
        "rather than inventing one.", body)
    for old, new in PATH_REWRITES:
        body = body.replace(old, new)
    for pattern, new in TOOL_REFERENCE:
        body = pattern.sub(new, body)
    # Upstream's own skill invocation, in every form it appears in the vendored files. A plain string
    # replace left `id `tdd"` behind (measured on the first generation), so this is a regex per shape.
    body = re.sub(r'[Cc]all the Skill tool with\s*[\"\']([^\"\']+)[\"\']',
                  r"Read the skill with the `skill` tool (id: `\1`)", body)
    body = re.sub(r'the Skill tool', "the `skill` tool", body)
    # slash commands name upstream skills; ours are read by id
    body = re.sub(r'`/([a-z][a-z0-9-]+)`', r"the `\1` skill", body)
    body = SKILL_SLASH.sub(r"the `\1` skill", body)
    # `.agents/skills/<name>/SKILL.md` is upstream's skill location; ours is backend/skills/builtin/<id>/
    body = body.replace(".agents/skills/", "backend/skills/builtin/")
    # upstream tells the agent to run its own setup skill; that skill does not exist here
    body = re.sub(r"tell the user to run `*(the )?`*setup-matt-pocock-skills`*( skill)?`*",
                  "say that the tracker vocabulary and triage labels must be configured first "
                  "(Skills activity \u2192 this skill's setup notes)", body)
    body = body.replace("setup-matt-pocock-skills skill", "Skills activity's setup notes")
    # NOTE: do NOT normalise doubled backticks with a regex here. A first attempt did, and it rewrote
    # every fenced code block (```lang → ``lang) in 311 places — the fences are part of the content.
    # MCP tool naming: upstream writes Claude's `mcp__server__tool`; our bridge prefixes `server_tool`
    body = re.sub(r"`mcp__([a-zA-Z0-9-]+)__\*` tools", r"the `\1_*` tools added by the MCP server", body)
    body = re.sub(r"mcp__([a-zA-Z0-9-]+)__", r"\1_", body)
    return body


def transform(skill_md: pathlib.Path, collection: str) -> tuple[str, dict]:
    fields, body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    skill_id = skill_md.parent.name
    desc = fields.get("description", "").strip()
    # descriptions carry upstream references as well (`/to-spec`, `.agents/…`); the frontmatter must not
    # point at a location or command that does not exist here.
    desc = SKILL_SLASH.sub(r"the `\1` skill", desc)
    desc = desc.replace(".agents/skills/", "backend/skills/builtin/").replace(".agents/plans", "docs/specs")
    body = _rewrite_body(body, skill_id)
    vendor_path = str(skill_md.relative_to(REPO))
    # Computed one branch at a time: a dict literal would evaluate both f-strings and the mattpocock
    # one raises for a langchain path (relative_to fails outside its tree).
    if collection == "mattpocock":
        rel = skill_md.parent.relative_to(VENDOR / "mattpocock" / "skills").as_posix()
        upstream = f"mattpocock/skills → skills/{rel}"
    else:
        upstream = f"langchain-ai/langchain-skills → config/skills/{skill_id}"
    fm = {
        "name": _title(skill_id),
        "description": " ".join(desc.split()),
        "tags": _tags(skill_id, desc, collection),
        "triggers": _triggers(skill_id, desc, body),
        "allowed_tools": _allowed_tools(body),
        "author": f"{collection} (MIT), adapted for LangConfig",
        "version": 1.0,
    }
    head = ["---"]
    for key, value in fm.items():
        if isinstance(value, list):
            head.append(f"{key}:")
            head += [f"  - {_yaml_scalar(v)}" for v in value]
        else:
            head.append(f"{key}: {_yaml_scalar(value)}")
    head.append("---")
    provenance = PROVENANCE_TEMPLATE.format(upstream=upstream, vendor_path=vendor_path)
    out = "\n".join(head) + "\n\n" + provenance + "\n" + (
        body if body.lstrip().startswith("## Instructions") else "## Instructions\n\n" + body
    )
    out = out.rstrip("\n") + "\n\n" + FLOOR
    if skill_id == "code-review":
        # this repository already had a review checklist; it is now the Standards axis' reference
        out = out.replace(
            FLOOR,
            "## Standards reference\n\n"
            "This repository's own review checklist lives beside this file as `STANDARDS-CHECKLIST.md`\n"
            "(what we consider clean, safe and maintainable). Read it as the **Standards** axis below —\n"
            "the axis that asks *does this meet what we decided*, not *does this match a general ideal*.\n\n"
            + FLOOR)
    return out, {"id": skill_id, "collection": collection, "upstream": upstream}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Regenerate our skills from the vendored upstream sets.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    args = ap.parse_args(argv)

    written, skipped, collisions = [], [], []
    for collection, root in (("mattpocock", VENDOR / "mattpocock" / "skills"),
                             ("langchain-skills", VENDOR / "langchain-skills")):
        for skill_md in sorted(root.rglob("SKILL.md")):
            skill_id = skill_md.parent.name
            if args.only and skill_id != args.only:
                continue
            # LangChain's ecosystem skills are prefixed so their provenance is visible in the list and
            # they cannot collide with ours; Matt's keep their names.
            target_id = RENAME.get(skill_id) or (f"lc-{skill_id}" if collection == "langchain-skills" else skill_id)
            if skill_id in OURS_FROM_SAME_SOURCE:
                skipped.append((target_id, "we already wrote the adapted version of this upstream"))
                continue
            dest_dir = OUT / target_id
            generated_before = (dest_dir / "SKILL.md").exists() and "**Provenance.** Adapted from" in (
                dest_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            if dest_dir.exists() and not generated_before and target_id not in REPLACE_KEEPING_OURS_AS:
                # Not ours and not generated: leave a hand-written skill alone and say so.
                collisions.append((target_id, "hand-written here — not overwritten"))
            if dest_dir.exists() and target_id in REPLACE_KEEPING_OURS_AS and not args.dry_run:
                old = (dest_dir / "SKILL.md").read_text(encoding="utf-8")
                (dest_dir / REPLACE_KEEPING_OURS_AS[target_id]).write_text(
                    "# Review standards (this repository's checklist)\n\n"
                    "Our own review guidance, kept as the **Standards** axis reference for the two-axis\n"
                    "review in `SKILL.md`: what this repository considers clean, safe and maintainable.\n\n"
                    + old, encoding="utf-8")
                print(f"  preserved ours as {target_id}/{REPLACE_KEEPING_OURS_AS[target_id]}")
            text, meta = transform(skill_md, collection)
            if not args.dry_run:
                dest_dir.mkdir(parents=True, exist_ok=True)
                (dest_dir / "SKILL.md").write_text(text, encoding="utf-8")
                # Copy support files verbatim: they are reference material, not instructions. Non-markdown
                # ones matter too — `scripts/hitl-loop.template.sh`, `wizard/template.sh` and the
                # dependency-cruiser config are referenced by their skills, so a skill without them sends
                # the agent looking for a file it was told exists. `agents/*.yaml` is Claude-client
                # configuration and is skipped on purpose.
                for extra in skill_md.parent.rglob("*"):
                    if not extra.is_file() or extra.name == "SKILL.md":
                        continue
                    if "agents" in extra.relative_to(skill_md.parent).parts:
                        continue
                    rel = extra.relative_to(skill_md.parent)
                    dst = dest_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        dst.write_text(extra.read_text(encoding="utf-8"), encoding="utf-8")
                    except UnicodeDecodeError:                      # a real binary asset: copy the bytes
                        dst.write_bytes(extra.read_bytes())
            written.append(target_id)

    print(f"{'would write' if args.dry_run else 'wrote'} {len(written)} skill(s)")
    for s in skipped:
        print(f"  skip      {s[0]:34} {s[1]}")
    for c in collisions:
        print(f"  collision {c[0]:34} {c[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

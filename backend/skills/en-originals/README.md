# English originals — a backup, not a library

Each folder here holds the English `SKILL.md` that the Chinese skill in `backend/skills/builtin/<id>/`
was translated from.

**Nothing here is loaded.** The loader scans `backend/skills/builtin/` and `backend/skills/personal/`;
this tree is outside both, so an agent never sees these files. `skill(id, lang="en")` can read one on
request — that is the only way they enter a context, and it is opt-in.

Why keep them at all: a translation is a copy, and a copy that has no original is unmaintainable. When the
Chinese text reads wrong, the original is where to check what it was supposed to say; when upstream skill
text changes (see `vendor/upstream-skills/`), the diff is taken here.

Rule that keeps this honest: if a skill has a folder here, its `SKILL.md` in `builtin/` MUST be Chinese and
structurally identical (same `##` headings, same code fences). `backend/tests/test_skill_translations.py`
enforces exactly that, and lists the skills that have no Chinese text yet.

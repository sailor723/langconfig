# KV ingest core — spec

Status: **proposed, not implemented.** Scope agreed 2026-10-15.

## Scope

**KV is the system of record.** Files plus `.kvmeta/<kb>.json`. No Postgres, no Neo4j.

The legacy RAG stack (`/api/rag/*`, `cmd_ingest`, `learning/phase9`) and GraphIndex chat are
**out of scope** — parked for a future exploration. The ingest core must not call them, and
nothing here changes them.

### Non-goals

- No object storage / COS. Filesystem for now.
- No graph index, no embeddings, no vector store.
- No renames of existing knowledge bases (see Decision 2).
- No UI work in this pass. CLI first; HTTP adapters reuse the same core afterwards.

## The problem being solved

"Put these files into a knowledge base" is implemented **five times**, differently:

| Path | Record build | `created_at` | "what is a document" |
|---|---|---|---|
| `POST /api/kv/upload` | `save_file` + `put_doc` | now | anything |
| `POST /api/kv/upload-bulk` | same, looped | now | anything |
| `POST /api/kv/ingest-folder` | walk + derive hierarchy | mtime | 25 text extensions — **no PDF** |
| `POST /api/kv/index-missing` | walk + derive hierarchy | mtime | its own rule |
| `scripts/migrate_legacy_kb.py` | its own catalog builder | mtime | anything but dotfiles |

Plus a sixth notion on the read side (`doc_chat.TEXT_EXTENSIONS | PDF_EXTENSIONS`).

Consequence: moving data between front doors changes the outcome, and no two doors agree on what
a document is. `ingest-folder` skipping PDFs silently is the sharpest example — the most likely
thing a teammate has is a PDF, and it reports `skipped: N, ingested: 0` with exit 0.

**One core, several thin adapters.** That is the whole point of this spec.

## The two verbs

| Verb | Semantics | Source | Used for |
|---|---|---|---|
| `ingest` | **copy** | a directory outside the knowledge root (legacy tree, a zip, an incoming transfer) | batch upload from legacy KB → new KB(s) |
| `recategorize` | **move** | files already inside the knowledge root | re-grouping loose files / moving between KBs |

`ingest` copies, so the source is never modified — there is nothing to reverse, no journal of
moves, no hash ledger. Reversal is "delete the target KB". Every bug found in
`migrate_legacy_kb.py` on 2026-10-14 (journal filename collision, inverse hierarchy shift writing
`industry=None`, manifest carried back into the parent) lived in the *move* machinery and simply
does not exist here.

`recategorize` moves, because that is what re-categorising means. It is a move **within one root**,
so it is the same class as `promote_subfolder_to_kb.py` — but moving individual files needs no
hierarchy *shift*, only a recompute from the new path.

## The shared core

Every front door calls one function. Sketch, not final signature:

```
ingest(sources, target, *, naming, on_collision, apply=False)
    sources : Iterable[(relative_path: str, data: bytes, mtime: float | None)]
    target  : either a KB name, or a directory whose subfolders each name a KB
```

Per file, the core does exactly one thing, once:

1. decide whether it is a document (Decision 1)
2. canonicalise the target KB name (Decision 2)
3. hash the content; skip if that hash is already present in the target (Decision 3)
4. write the file with the 8-hex collision prefix, under the directories implied by its relative path
5. append a record to `.kvmeta/<kb>.json`

The `sources` shape is `(relative_path, bytes)`, which makes every adapter trivial:

| Front door | How it produces `sources` |
|---|---|
| CLI directory | walk a directory |
| browser online upload | already sends this; `file_metadata` carries the relative path |
| zip import | `zipfile` yields exactly this (mine `rag/uploads.py::_safe_extract_zip_member` for the traversal guard) |
| machine-to-machine copy | CLI, pointed at the incoming directory |

## Decision 1 — what is a document

One predicate, defined once:

```
DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | PDF_EXTENSIONS | OFFICE_EXTENSIONS
```

- `TEXT_EXTENSIONS` / `PDF_EXTENSIONS` — reuse `doc_chat.py`'s sets verbatim.
- `OFFICE_EXTENSIONS` — `.docx .xlsx .pptx .doc .xls .ppt` (currently in neither list).
- **Unknown types are accepted, not skipped.** An unrecognised extension is ingested and
  *reported*; it is never silently dropped. Silent skipping is what makes `ingest-folder`
  dangerous.
- Dotfiles are refused (existing behaviour in `file_storage.save_file`) and reported.

Open sub-decision: office formats are stored and listed but doc chat can only inline text/PDF.
Ingest should record the type so chat can say "cannot read this" instead of ignoring it.

## Decision 2 — naming

**Canonical form for newly created KBs: `snake_case`, lowercase ASCII.**

| Rule | Behaviour | Example |
|---|---|---|
| Provable equivalence | **auto-merge** — reuse the existing KB, never create a near-twin | `business_model` ≡ `business-model` ≡ `Business Model` |
| Judgment call | **warn only**, require explicit confirmation, never auto-merge | `semiconduct_industry` vs `semiconductor_industry` |
| Existing 13 KBs | **grandfathered — no renames** | `langconfig-test`, `project-15`, `AM_HK_industries`, `惠州华阳医疗器械有限公司` all stay |

Equivalence key = the name lowercased with `[^a-z0-9]` removed. Merging on a fuzzy guess is how
the mess being cleaned up was created; only provable equivalence merges.

Existing names today, of 13: 5 snake (`business_model`, `market_reports`, `semiconduct_industry`,
`deepagent_installation`, `AM_HK_industries`), 6 kebab (`langconfig-test`, `knowledge-4242`, and the
4 `project-<id>`), 1 plain (`organization`), 1 non-ASCII (`惠州华阳医疗器械有限公司`). The four
`project-<id>` names violate the no-project-id rule and are out of scope here.

No collisions exist today — 13 KBs, 13 distinct even lowercased — so this is preventive, and this
is the right moment: nothing normalises names anywhere in the codebase today, and `knowledge` is
used raw as a folder name by `documents_dir()`.

## Decision 3 — collisions merge, never refuse

The root-level KB **is** the one consistent knowledge base. Two folders with the same name is the
bug, not a conflict to referee.

- **Same KB name** → merge into it.
- **Same content** (sha256) → skip, and report. This is not optional: `eyewear_industry` exists in
  three legacy projects (900 / 450 / 321 files, union 905), and `langconfig-test`'s 85 loose files
  are only **23 distinct contents**.
- **Re-running is safe.** `ingest` is idempotent; a second run adds nothing.

This replaces `promote_subfolder_to_kb.py`'s refusal (`!! target already exists — skipped, nothing
moved`), which is why three folders were left behind on 2026-10-14.

Add a `sha256` field to the record. Today there is no content hash anywhere, which is why 63
identical-looking `*_report.md` files and 4 copies of one PDF went unnoticed.

## Decision 4 — `created_at`

- Source provides an mtime (CLI directory, zip) → **use the mtime**: "when this was collected"
  survives the copy.
- No mtime (browser upload — `File.lastModified` is unreliable across browsers) → **ingest time**.

Today it silently differs by front door; that must be a stated rule, not an accident.

## Decision 5 — catalog keys become relative

The record's `storage_path` is **absolute**, which makes a catalog machine-bound and a KB
non-portable. Demonstrated: a byte-identical copy of the knowledge root at a different path
reported *"no records point into 'archive'"* until 1535 paths were rewritten by hand.

Proposal:

- Store a **KB-relative `key`** (e.g. `reports/2026/b37a8720_summary.md`) as the source of truth.
- Keep `storage_path` in the API response, **derived** at read time, so existing consumers
  (`/api/kv/documents`, `/tree`, `/file`) are unchanged.

This is the prerequisite for download/reload, for the team sharing KBs between the Mac and WSL,
and for `recategorize` not corrupting paths when files move.

## Decision 6 — loose files

Two different situations, only one of which is a problem:

| Where | Verdict |
|---|---|
| Files at a **KB's own root** (`business_model/prioritization.pdf`) | **Normal.** A KB contains documents; some are in subfolders. Nothing to do. |
| Files at the **knowledge root** (`data/knowledge/x.pdf`) | **Broken** — belongs to no KB, invisible to discovery. Currently 0 files. |
| Files at a **legacy project root** (`project_1/x.pdf`) | **Broken** — no folder name to inherit. This is the real case. |

For the legacy case: the operator must supply a name (`--loose-name`) or a grouping mapping.
**The tool refuses to invent `ungrouped`.** That name is not neutral — history says so
(`rag/uploads.py`): `(ungrouped)` was a synthetic UI bucket for a NULL `industry` column, and
*"once there, the user can't filter the chat by industry, the agent can't route by hierarchy, and
the visual UI is cluttered."* A name meaning "I didn't decide" is the opposite of a consistent
naming policy.

Worth noting before building grouping: langconfig-test's 85 loose files are ~90% debris — 63
`*_report.md` with 4 distinct contents, **59 of them are 5 bytes: `hello`**; `project-16`'s four are
all `tmp*.docx/.pptx/.html`. The tool should report that, not organise it.

## Verification

`ingest` copies, so verification is a re-scan, not a hash ledger:

1. every file in `sources` is present in the target (by hash)
2. every record's `key` resolves to an existing file
3. no record points outside its own KB
4. the count of distinct hashes in the target increased by exactly the number of non-duplicate files

`scripts/verify_copied_knowledge_base.py` already does a version of this for a copied KB.

## What this replaces

| Today | After |
|---|---|
| `migrate_legacy_kb.py` | `ingest --from <legacy dir>` |
| `promote_subfolder_to_kb.py` | `recategorize` (folder form) |
| `promote_all_subfolders.py` | dropped — one level per run was a workaround, not a rule |
| `migrate_kb.sh` + `docs/KB_MIGRATION.md` | obsolete (they drive removed project-row scripts) |

Four entry points become one core with two verbs. This also answers the standing request for
"one script, not three".

## Open questions

1. Office formats: ingest-and-flag, or refuse? (decides whether `OFFICE_EXTENSIONS` is in scope now)
2. `recategorize` reversal: journal, or "move it back by hand"? A move needs *some* record.
3. Oversize documents: `Week1_slides.pdf` is 38.7 MB and doc chat inlines whole files up to
   `MAX_CONTEXT_CHARS`. Record a size flag, or cap at ingest?
4. Filename sanitiser: one real document's name is ~300 zero-width characters
   (`…workshop - feishu docs.pdf`) — unsearchable and unclickable. Normalise on ingest?
5. Double prefix: re-ingested files become `b37a8720_3d136714_name.pdf`, and the display-name
   stripper removes only the outer prefix. Strip repeatedly, or leave it cosmetic?

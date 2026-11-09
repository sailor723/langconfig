# History rewrite — 2026-11-09

**团队速读（一分钟）**

| 你的机器 | 要不要做事 |
|---|---|
| 今天用 **team zip** 装的（`langconfig.zip` → `python backend/scripts/setup.py`） | **什么都不用做。不要重装。** zip 里没有 `.git`，这次改写碰不到你 |
| 今天用 **git clone** 装的（在 2026-11-09 22:00 之前） | 需要刷新一次：`./scripts/refresh_clone_after_rewrite.sh --apply` |
| 今天用 **git clone** 装的（22:00 之后） | 不用做事（`git cat-file -e b27dc24f` 有输出就是在新的历史上） |

一句话：**这次改的只有 git 历史，没有改任何工作文件。** 装了就不必再装。

---

## What changed

`backend/data/**` had been committed before it was gitignored, so the repository carried **414 MB of
PDFs that no working tree contains any more**. That history was rewritten with `git-filter-repo`:

| | before | after |
|---|---|---|
| `.git` object store | 460 MB | **39.6 MiB** |
| commits on `main` | 1 625 | 1 585 (40 became empty and were pruned) |
| **HEAD tree hash** | `cc5005d2…` | **`cc5005d2…` — identical** |
| working-tree files | — | unchanged |

The identical tree hash is the proof: **no file changed, only the history**. What is different is that
**every commit hash from before 2026-11-09 is new** — which matters to a git checkout and to nothing
else.

## If you installed today from the team zip: nothing to do

`scripts/make_team_zip.sh` excludes `.git/*` on purpose ("the recipient unzips, runs
`python backend/scripts/setup.py` … and is up (no git needed)"). An install from the zip therefore has
**no git history to rewrite**, and the code it contains is the same content as the repository at the
moment the zip was cut.

Confirm it in one command — if this prints "not a git repository", you are in the zip install and you
are done:

```bash
git rev-parse --is-inside-work-tree 2>/dev/null || echo "zip install — not affected, nothing to do"
```

**Do not re-install to "fix" this.** There is nothing on that machine to fix.

## If you have a git clone from before the rewrite

`git pull` refuses (unrelated histories) and a plain `git fetch` changes nothing, because the old
objects are gone from the remote. Use the script, which is written for this case:

```bash
cd /path/to/langconfig
git status                                          # look at what is uncommitted — it is saved anyway
./scripts/refresh_clone_after_rewrite.sh            # dry run: says exactly what it will do
./scripts/refresh_clone_after_rewrite.sh --apply    # do it
```

It (1) saves your uncommitted work as a patch and lists untracked files — a hard reset does not touch
untracked files, (2) `git fetch --force --prune`, (3) `git reset --hard origin/main`, (4) re-applies
your patch (and reports a conflict instead of guessing), (5) deletes the stale local tag
`main-history-backup` — the one thing that keeps the old bytes alive — and **reports, never deletes**,
branches of yours that are outside the new history, (6) expires the reflog and gc's.

Measured on a clone of the pre-rewrite history: **465 MB → 40 MB**, working tree on the new history,
the uncommitted edit back in place.

By hand, if you prefer:

```bash
git diff > /tmp/my-work.patch
git fetch --force --prune origin
git reset --hard origin/main
git tag -d main-history-backup 2>/dev/null
git reflog expire --expire=now --all && git gc --prune=now
git apply /tmp/my-work.patch
```

## After you take new code — any path, zip or clone

The history changed nothing in the files; **the code that landed today did**. Once you have today's
code, two commands make the machine serve it:

```bash
# backend
cd backend && uv sync && .venv/bin/python main.py      # or: bash start.sh
# frontend (dist/ is not tracked, so it must be rebuilt)
npm install && npm run build
```

No database reseed is needed: `scripts/seeds/in/seed_all.py` was not changed by any of this.

## What was NOT lost

- **`new_coldchain_v5` is committed.** It had been published on the deployment but never committed (its
  publish-time `git commit` failed with "Author identity unknown"), so it existed in exactly one
  checkout — and the hard reset used to move that machine onto the rewritten history deleted it. It was
  rebuilt byte-for-byte from the publish ledger and is now commit `ontology(new_coldchain_v5): publish
  1794212541-6afcb2`, 10 files, 84 metrics compiled, 0 refused.
- **The ledger can rebuild any published ontology**: `scripts/ontology_restore.py --key <key>` reports
  what a publish contained, `--apply` writes it, `--verify` compiles and gates it. That path has tests
  (`backend/tests/test_ontology_restore.py`).
- **The pre-rewrite history is still recoverable** from
  `.git/backups/pre-rewrite-20261109.bundle` on the maintainer's machine (a full `--all` bundle:
  `git clone <bundle>` restores everything). Nobody needs it unless we decide to undo the rewrite.

## If something looks wrong

| Symptom | What it is | Do |
|---|---|---|
| `git pull` says "refusing to merge unrelated histories" | the clone predates the rewrite | run the refresh script above |
| `git fetch` reports nothing new, `.git` is still ~460 MB | a local tag still points at the old history | `git tag -d main-history-backup`, then `git reflog expire --expire=now --all && git gc --prune=now` |
| the UI still shows the old screens after updating | `dist/` is gitignored and was not rebuilt | `npm run build`, then hard-refresh the browser (Cmd/Ctrl+Shift+R) |
| endpoints that used to work now 404 | they were removed on purpose (33 endpoints had zero callers — see `HOUSEKEEPING.md` §7.5) | nothing to fix; check that list before assuming a regression |
| an ontology is missing from the list | its profile directory is absent — a publish that was never committed lives in one checkout only | `scripts/ontology_restore.py --key <key> --apply --verify` |

## For whoever cuts the next team zip

`langconfig.zip` in the repository root predates today's changes. Regenerate it before handing out new
installs (`scripts/make_team_zip.sh`), so a new machine starts on today's code. Existing zip installs do
not need it.

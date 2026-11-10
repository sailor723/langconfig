---
name: "Setup Pre Commit"
description: "Set up Husky pre-commit hooks with lint-staged (Prettier), type checking, and tests in the current repo. Use when user wants to add pre-commit hooks, set up Husky, configure lint-staged, or add commit-time formatting/typechecking/testing."
tags:
  - "setup"
  - "pre"
  - "commit"
  - "mattpocock"
  - "testing"
triggers:
  - "User wants to add pre-commit hooks, set up husky, configure lint-staged, or add commit-time formatting/typeche"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

> **Provenance.** Adapted from `mattpocock/skills → skills/misc/setup-pre-commit` (MIT, vendored at `vendor/upstream-skills/mattpocock/skills/misc/setup-pre-commit/SKILL.md`).
> Changed for this repository: frontmatter fields (`tags` / `triggers` / `allowed_tools` / `author` /
> `version`), path conventions (`docs/specs`, `docs/tickets`, `work/<scope>`), tool names
> (`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`), and a verification floor
> section. Upstream's `disable-model-invocation` has no equivalent here — every skill is discoverable
> through the `skill` tool, so it is dropped rather than emulated.

## Instructions

# Setup Pre-Commit Hooks

## What This Sets Up

- **Husky** pre-commit hook
- **lint-staged** running Prettier on all staged files
- **Prettier** config (if missing)
- **typecheck** and **test** scripts in the pre-commit hook

## Steps

### 1. Detect package manager

Check for `package-lock.json` (npm), `pnpm-lock.yaml` (pnpm), `yarn.lock` (yarn), `bun.lockb` (bun). Use whichever is present. Default to npm if unclear.

### 2. Install dependencies

Install as devDependencies:

```
husky lint-staged prettier
```

### 3. Initialize Husky

```bash
npx husky init
```

This creates `.husky/` dir and adds `prepare: "husky"` to package.json.

### 4. Create `.husky/pre-commit`

Write this file (no shebang needed for Husky v9+):

```
npx lint-staged
npm run typecheck
npm run test
```

**Adapt**: Replace `npm` with detected package manager. If repo has no `typecheck` or `test` script in package.json, omit those lines and tell the user.

### 5. Create `.lintstagedrc`

```json
{
  "*": "prettier --ignore-unknown --write"
}
```

### 6. Create `.prettierrc` (if missing)

Only create if no Prettier config exists. Use these defaults:

```json
{
  "useTabs": false,
  "tabWidth": 2,
  "printWidth": 80,
  "singleQuote": false,
  "trailingComma": "es5",
  "semi": true,
  "arrowParens": "always"
}
```

### 7. Verify

- [ ] `.husky/pre-commit` exists and is executable
- [ ] `.lintstagedrc` exists
- [ ] `prepare` script in package.json is `"husky"`
- [ ] `prettier` config exists
- [ ] Run `npx lint-staged` to verify it works

### 8. Commit

Stage all changed/created files and commit with message: `Add pre-commit hooks (husky + lint-staged + prettier)`

This will run through the new pre-commit hooks: a good smoke test that everything works.

## Notes

- Husky v9+ doesn't need shebangs in hook files
- `prettier --ignore-unknown` skips files Prettier can't parse (images, etc.)
- The pre-commit runs lint-staged first (fast, staged-only), then full typecheck and tests

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

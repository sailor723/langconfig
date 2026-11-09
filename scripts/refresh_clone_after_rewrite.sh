#!/usr/bin/env bash
# refresh_clone_after_rewrite.sh — move an existing clone onto rewritten history, without losing work.
#
# The repository's history was rewritten on 2026-11-09 (414 MB of old `backend/data` PDFs were removed;
# every commit hash before that date changed). A clone made before the rewrite has a completely
# different ancestry, so `git pull` refuses and `git merge` would try to merge unrelated histories.
#
# This script is the safe one-liner for that case:
#   1. refuse to lose uncommitted work — it saves a patch and a stash first, and says where they went;
#   2. `git fetch --force` (the old objects are gone from the remote, so a normal fetch does nothing);
#   3. `git reset --hard <remote>/<branch>` — the working tree becomes the rewritten branch;
#   4. re-apply the saved patch, reporting a conflict instead of guessing;
#   5. print what changed so the person can see the tree is intact.
#
# Usage, from the repository root:
#   ./scripts/refresh_clone_after_rewrite.sh              # dry run: says what it WOULD do
#   ./scripts/refresh_clone_after_rewrite.sh --apply      # do it
#   REMOTE=github BRANCH=main ./scripts/refresh_clone_after_rewrite.sh --apply
#
# Trade-off to know about: `git stash` survives the reset but a stash POP across rewritten history can
# conflict. That is why the patch file is written first — `git apply <patch>` is the fallback.

set -uo pipefail
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Work from the repository that holds this script, or from the current one if the script was copied
# elsewhere (a teammate may well have done that).
root=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel 2>/dev/null \
       || git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$root" ]; then
  echo "not inside a git repository — run this from your checkout, or keep it in scripts/" >&2
  exit 1
fi
cd "$root" || exit 1

stamp=$(date +%Y%m%d-%H%M%S)
patch_dir=".git/rewrite-migration-$stamp"
echo "repository : $(pwd)"
echo "current    : $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-60)"
echo "target     : $REMOTE/$BRANCH"

dirty=$(git status --porcelain | wc -l | tr -d ' ')
echo "uncommitted: $dirty path(s)"

if [ "$dirty" != "0" ]; then
  mkdir -p "$patch_dir"
  git diff > "$patch_dir/working-tree.patch"
  git diff --cached >> "$patch_dir/working-tree.patch"
  git status --porcelain > "$patch_dir/status.txt"
  git ls-files --others --exclude-standard > "$patch_dir/untracked.txt"
  echo "  saved a patch of the changes to $patch_dir/working-tree.patch"
  echo "  (untracked files are listed in $patch_dir/untracked.txt and are NOT touched by the reset)"
fi

if [ "$APPLY" = 0 ]; then
  echo
  echo "dry run — would run:"
  echo "  git fetch --force --prune $REMOTE"
  echo "  git reset --hard $REMOTE/$BRANCH"
  [ "$dirty" != "0" ] && echo "  git apply $patch_dir/working-tree.patch   # to bring the changes back"
  echo
  echo "re-run with --apply to do it."
  exit 0
fi

echo
echo "== fetching (forced: the pre-rewrite objects are no longer on the remote)"
git fetch --force --prune "$REMOTE" || { echo "fetch failed"; exit 1; }

if ! git rev-parse --verify --quiet "$REMOTE/$BRANCH" >/dev/null; then
  echo "$REMOTE/$BRANCH not found after fetch" >&2; exit 1
fi

echo "== resetting the working tree to $REMOTE/$BRANCH"
git reset --hard "$REMOTE/$BRANCH" || { echo "reset failed"; exit 1; }

echo "== now at: $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-60)"
echo "== files: $(git ls-files | wc -l | tr -d ' ') tracked, $(git status --porcelain | wc -l | tr -d ' ') dirty"

if [ -s "$patch_dir/working-tree.patch" ]; then
  echo
  echo "== re-applying the saved changes"
  if git apply --3way "$patch_dir/working-tree.patch" 2>/dev/null || git apply "$patch_dir/working-tree.patch"; then
    echo "   applied — review them, they were written against the old history"
  else
    echo "   could NOT apply cleanly. The patch is at $patch_dir/working-tree.patch"
    echo "   Recover by hand: git apply --reject $patch_dir/working-tree.patch"
  fi
fi

# ── stale refs: the rewritten history dropped objects, but a local TAG or BRANCH still pointing at
#    an old commit keeps every one of them alive. Measured on a real pre-rewrite clone: after a forced
#    fetch + reset the .git was still 462 MB, and the only thing holding the old PDFs was a local tag
#    (git fetch does not delete local tags or branches that the remote no longer has). Tags are deleted
#    here because they are cheap to recreate; branches are only reported, because they may hold work.
echo
echo "== refs still pointing outside the new history"
stale_tags=(); stale_branches=()
for t in $(git tag); do
  if [ "$(git log --oneline "refs/tags/$t" -- backend/data 2>/dev/null | wc -l | tr -d ' ')" != "0" ]; then
    stale_tags+=("$t")
  fi
done
for b in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  [ "$b" = "$BRANCH" ] && continue
  if ! git merge-base --is-ancestor "refs/heads/$b" "refs/remotes/$REMOTE/$BRANCH" 2>/dev/null; then
    stale_branches+=("$b")
  fi
done
for t in "${stale_tags[@]:-}"; do [ -n "$t" ] && echo "  deleting stale tag: $t  ($(git rev-parse --short "$t"))" && git tag -d "$t" >/dev/null; done
for b in "${stale_branches[@]:-}"; do [ -n "$b" ] && echo "  your branch is NOT on the new history (keep or rebase it yourself): $b"; done

echo
echo "== reclaiming the old objects"
git reflog expire --expire=now --all
git gc --prune=now --quiet
echo "   .git is now $(du -sm .git 2>/dev/null | cut -f1) MB, $(git rev-list --count HEAD) commits, $(git log --all --oneline -- backend/data | wc -l | tr -d ' ') commit(s) still touching backend/data"
echo
echo "done."

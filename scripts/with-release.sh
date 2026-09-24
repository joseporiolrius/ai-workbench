#!/usr/bin/env bash
# Run a workbench release command from a clean, detached exact-SHA worktree
# (WB-08). A tagged release stays reproducible after student `main` advances: the
# chart/values/helpers are read at the requested SHA, never from the moving
# checkout. Generated outputs are kept OUTSIDE tracked source.
#
# Usage:  scripts/with-release.sh <full-40-char-sha> <command> [args...]
#
# Contract:
#   - <sha> must be a full 40-hex commit available from origin.
#   - checkout lives at  ~/releases/workbench/<sha>        (detached, reused if clean)
#   - generated state at  ~/releases/workbench-state/<sha>/ (exported as RELEASE_STATE_DIR)
#   - a dirty/mismatched existing worktree is REJECTED (never discarded).
#   - the student's interactive checkout, branch and uncommitted work are untouched.
#   - the command's exit status is returned unchanged.
set -eu

REL_ROOT="${WB_RELEASE_ROOT:-$HOME/releases/workbench}"
STATE_ROOT="${WB_RELEASE_STATE_ROOT:-$HOME/releases/workbench-state}"

sha="${1:-}"; shift || true
case "$sha" in
  *[!0-9a-f]* | "") echo "with-release: first arg must be a full 40-hex commit SHA" >&2; exit 2 ;;
esac
[ "${#sha}" -eq 40 ] || { echo "with-release: SHA must be 40 hex chars" >&2; exit 2; }
[ "$#" -ge 1 ] || { echo "with-release: a command is required" >&2; exit 2; }

# the SHA must be reachable from origin (a real published release commit)
git cat-file -e "${sha}^{commit}" 2>/dev/null || { echo "with-release: unknown commit ${sha}" >&2; exit 2; }
if ! git branch -r --contains "$sha" 2>/dev/null | grep -q .; then
  echo "with-release: ${sha} is not available from origin (push it first)" >&2; exit 2
fi

wt="${REL_ROOT}/${sha}"
state="${STATE_ROOT}/${sha}"
mkdir -p "$state"

if [ -d "$wt/.git" ] || git -C "$wt" rev-parse --git-dir >/dev/null 2>&1; then
  # reuse only if clean AND at the exact SHA
  cur="$(git -C "$wt" rev-parse HEAD 2>/dev/null || echo none)"
  if [ "$cur" != "$sha" ]; then
    echo "with-release: existing worktree ${wt} is at ${cur}, not ${sha} — refusing (content preserved)" >&2; exit 2
  fi
  if [ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ]; then
    echo "with-release: existing worktree ${wt} is dirty — refusing (content preserved)" >&2; exit 2
  fi
else
  git worktree add --detach "$wt" "$sha" >/dev/null 2>&1 \
    || { echo "with-release: could not create worktree for ${sha}" >&2; exit 2; }
fi

# run the command at the release root; state dir is outside tracked source
( cd "$wt" && RELEASE_STATE_DIR="$state" RELEASE_SHA="$sha" exec "$@" )

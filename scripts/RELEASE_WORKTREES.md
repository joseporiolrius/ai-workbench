# Reproducible release worktrees — `with-release.sh` (WB-08)

A tagged workbench release must stay reproducible after your `main` advances, and
CI must not reset your interactive checkout. `with-release.sh` runs a command from
a **clean, detached, exact-SHA** worktree.

```bash
scripts/with-release.sh <full-40-char-sha> <command> [args...]
```

## Contract
- `<sha>` must be a **full 40-hex** commit **available from origin** (push it first).
- Checkout: `~/releases/workbench/<sha>` (detached). A matching **clean** worktree
  is **reused**; a **dirty or mismatched** one is **rejected** — never discarded.
- Generated outputs go to `~/releases/workbench-state/<sha>/` (exported as
  `RELEASE_STATE_DIR`) so the release checkout stays clean.
- The command runs at the release root; its **exit status is returned unchanged**.
- Your interactive checkout, branch and uncommitted work are **untouched**.

## Rerun behavior
Re-running a prior tag reads the **original** chart/values/helpers at that SHA even
after `main` moved on (both release `HEAD` and input files match the SHA).

## Shared S9/S12 interface
S9 (chart deploy) and S12 (retrieval release) both drive their release commands
through this helper, so every release is reproducible from its exact SHA.

## Errors
Invalid/short SHA, a commit not on origin, or a dirty/mismatched existing worktree
all exit non-zero **without** modifying tracked source.

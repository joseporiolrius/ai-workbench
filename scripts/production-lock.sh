#!/usr/bin/env bash
# Serialize every PRODUCTION mutation of the workbench (Helm release + live study_guides alias)
# across GitHub Actions (SSH) and classroom shells (RAG-08). Source it, then call:
#
#   . scripts/production-lock.sh
#   production_lock "deploy <SHA>"        # blocks (bounded) until this process owns production
#
# One kernel flock on <state root>/production.lock — outside every worktree, so all release checkouts
# and your editing checkout share it. The lock fd is inherited by child processes and released by the
# kernel only when the holder AND its children exit (normally, killed, or SSH dropped): the whole
# transition — including helm --atomic rollback and alias restore — runs under it, and a crash can
# never leave a permanent block. A waiter prints who holds it; after WB_LOCK_WAIT_SECONDS (900) it
# gives up with exit 75 ("production busy") instead of becoming a second writer.

production_lock() {
  local label="$1"
  # Re-entrant: a child of the holder (deploy.sh -> promote-corpus.sh) inherited the locked fd 9.
  # Re-locking through a NEW open of the file would deadlock on our own parent, so just proceed.
  if [ -n "${PRODUCTION_LOCK_HELD:-}" ]; then
    echo "[production-lock] held by parent (${PRODUCTION_LOCK_HELD}); continuing as: $label" >&2
    return 0
  fi
  local root="${WB_RELEASE_STATE_ROOT:-$HOME/releases/workbench-state}"
  local wait="${WB_LOCK_WAIT_SECONDS:-900}"
  PRODUCTION_LOCK="${WB_PRODUCTION_LOCK:-$root/production.lock}"
  mkdir -p "$(dirname "$PRODUCTION_LOCK")"
  exec 9>>"$PRODUCTION_LOCK"
  if ! flock -n 9; then
    echo "[production-lock] BUSY — waiting up to ${wait}s. Current holder: $(cat "$PRODUCTION_LOCK.holder" 2>/dev/null || echo unknown)" >&2
    if ! flock -w "$wait" 9; then
      echo "[production-lock] GAVE UP after ${wait}s: production is still busy; nothing was changed. Re-run this release when the holder finishes." >&2
      exit 75
    fi
  fi
  printf '%s | pid %s | host %s | since %s\n' "$label" "$$" "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$PRODUCTION_LOCK.holder"
  export PRODUCTION_LOCK_HELD="$label"
  echo "[production-lock] acquired by: $label" >&2
}

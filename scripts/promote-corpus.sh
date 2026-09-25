#!/usr/bin/env bash
# Promote an EVALUATED candidate to the live alias study_guides, atomically (RAG-06).
#   release:  scripts/with-release.sh <SHA> scripts/promote-corpus.sh <SHA>    (normally called by deploy.sh)
#   manual:   scripts/promote-corpus.sh --manual study_guides_manual           (classroom, editing checkout)
#   restore:  scripts/promote-corpus.sh --restore study_guides_<old-SHA>       (back to a previously live one)
# Under the production lock: verifies the receipt (and the stored candidate) BEFORE any change, then
# repoints the alias in one atomic request, verifies it, and restores the previous target on failure.
# Physical collections are never deleted here; cleanup is an explicit, separate step (runbook §7).
set -uo pipefail
if [ -z "${KUBECONFIG:-}" ] && [ -r /etc/rancher/k3s/k3s.yaml ]; then export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; fi
here="$(dirname "$0")"
ROOT="${WB_RELEASE_STATE_ROOT:-$HOME/releases/workbench-state}"
log() { echo "[promote] $*" >&2; }
PY=(uv run -q --project ingestion --locked python)

case "${1:-}" in
  --manual)  mode=manual;  candidate="${2:-}"; STATE="$ROOT/manual"; verify=(--manual "$candidate")
             [[ "$candidate" =~ ^study_guides_[A-Za-z0-9_-]+$ ]] || { echo "usage: $0 --manual study_guides_<name>" >&2; exit 2; } ;;
  --restore) mode=restore; candidate="${2:-}"; STATE="$ROOT/restore"
             [[ "$candidate" =~ ^study_guides_[A-Za-z0-9_-]+$ ]] || { echo "usage: $0 --restore study_guides_<name>" >&2; exit 2; } ;;
  *)         mode=release; sha="${1:-${RELEASE_SHA:-}}"
             [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <full-SHA> | --manual <candidate> | --restore <collection>" >&2; exit 2; }
             [ "$(git rev-parse HEAD 2>/dev/null)" = "$sha" ] || { log "FAILED: checkout is not at $sha (use scripts/with-release.sh)"; exit 1; }
             candidate="study_guides_$sha"; STATE="${RELEASE_STATE_DIR:-$ROOT/$sha}"; verify=(--sha "$sha") ;;
esac
[ -f ingestion/pyproject.toml ] || { log "FAILED: run from the ai-workbench repository root"; exit 1; }

. "$here/production-lock.sh"
production_lock "promote-corpus $mode $candidate"
. "$here/qdrant-forward.sh"
qdrant_forward "$STATE.forward.log" || { log "FAILED: no Qdrant forward; nothing changed"; exit 1; }

if [ "$mode" = restore ]; then
  "${PY[@]}" scripts/corpus_alias.py restore --to "$candidate" --state "$STATE"; exit $?
fi
# the receipt gate: no passing, matching receipt -> no alias change at all
if ! "${PY[@]}" scripts/receipt.py verify --state "$STATE" "${verify[@]}" --qdrant-url "$QDRANT_URL"; then
  log "FAILED: receipt rejected — the live alias was not touched"; exit 1
fi
"${PY[@]}" scripts/corpus_alias.py promote --candidate "$candidate" --state "$STATE" \
  --receipt-sha256 "$(sha256sum "$STATE/receipt.json" | cut -d' ' -f1)"

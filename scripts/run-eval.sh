#!/usr/bin/env bash
# Evaluate a retrieval candidate from ANY shell, including a fresh non-interactive SSH session (RAG-04).
#
#   release:  scripts/with-release.sh <SHA> scripts/run-eval.sh <SHA>     # scores study_guides_<SHA>
#   manual:   scripts/run-eval.sh --manual study_guides_manual           # from your editing checkout root
#
# It reads the course key from the existing Kubernetes Secret (never printed), opens ITS OWN Qdrant
# port-forward on a free localhost port, waits until Qdrant answers, runs
#   uv run --project ingestion --locked pytest evals/ -v
# from the repository root, then closes only that forward. Exit = pytest's status (0 pass, 1 gate
# failed, 5 no tests collected) or 1 for a missing Secret / failed forward / wrong checkout, 124 on
# timeout, 130 when interrupted. Results + receipt.json: $RELEASE_STATE_DIR (release) or ~/releases/workbench-state/manual.
set -uo pipefail

if [ -z "${KUBECONFIG:-}" ] && [ -r /etc/rancher/k3s/k3s.yaml ]; then   # non-login SSH (see deploy.sh)
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi
NS=workbench
log() { echo "[run-eval] $*" >&2; }
fail() { log "FAILED: $*"; exit 1; }

if [ "${1:-}" = "--manual" ]; then
  mode=manual; collection="${2:-}"
  [[ "$collection" =~ ^study_guides_[A-Za-z0-9_-]+$ ]] || { echo "usage: $0 --manual study_guides_<name>" >&2; exit 2; }
  STATE="${RELEASE_STATE_DIR:-${WB_RELEASE_STATE_ROOT:-$HOME/releases/workbench-state}/manual}"
else
  mode=release; sha="${1:-${RELEASE_SHA:-}}"
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <full-40-hex-SHA> | --manual <candidate>" >&2; exit 2; }
  head="$(git rev-parse HEAD 2>/dev/null)"
  [ "$head" = "$sha" ] || fail "this checkout is at ${head:-no git}, not $sha — run it through scripts/with-release.sh $sha"
  collection="study_guides_$sha"
  STATE="${RELEASE_STATE_DIR:-${WB_RELEASE_STATE_ROOT:-$HOME/releases/workbench-state}/$sha}"
fi
[ -f evals/golden_set.yaml ] && [ -f ingestion/pyproject.toml ] || fail "run from the ai-workbench repository root"
mkdir -p "$STATE"
# a new evaluation always starts without evidence: a failed/aborted rerun can never leave an old pass behind
rm -f "$STATE/receipt.json" "$STATE/eval-results.json"
if [ "$mode" = release ]; then target=(--sha "$sha"); else target=(--manual "$collection"); fi

# 1. course key from the Secret -> environment only (no xtrace, never echoed)
set +x
key_b64="$(kubectl -n "$NS" get secret "${WB_KEYS_SECRET:-workbench-keys}" -o jsonpath='{.data.COURSE_VIRTUAL_KEY}' 2>/dev/null)" \
  || fail "cannot read Secret $NS/workbench-keys (does it exist? is KUBECONFIG set?)"
[ -n "$key_b64" ] || fail "Secret $NS/workbench-keys has no COURSE_VIRTUAL_KEY"
COURSE_VIRTUAL_KEY="$(printf '%s' "$key_b64" | base64 -d)"; export COURSE_VIRTUAL_KEY; unset key_b64

# 2. our own forward on a free port; clean up only that process
port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
kubectl -n "$NS" port-forward "svc/${EVAL_QDRANT_SERVICE:-workbench-qdrant}" "${port}:6333" >"$STATE/eval-port-forward.log" 2>&1 &
pf=$!
cleanup() { kill "$pf" 2>/dev/null; wait "$pf" 2>/dev/null; }
trap 'cleanup' EXIT
trap 'log "interrupted"; cleanup; exit 130' INT TERM
for _ in $(seq 1 40); do
  kill -0 "$pf" 2>/dev/null || fail "port-forward exited: $(tail -1 "$STATE/eval-port-forward.log")"
  curl -fsS -o /dev/null "http://127.0.0.1:${port}/healthz" 2>/dev/null && break
  sleep 0.5
done
curl -fsS -o /dev/null "http://127.0.0.1:${port}/healthz" 2>/dev/null || fail "Qdrant not ready on 127.0.0.1:${port} after 20 s"
log "$mode evaluation of $collection via its own forward 127.0.0.1:${port} (pid $pf)"

# 3. the locked evaluator from the repository root; its status is our status
QDRANT_URL="http://127.0.0.1:${port}" QDRANT_COLLECTION="$collection" EVAL_RESULTS="$STATE/eval-results.json" \
  timeout "${EVAL_TIMEOUT_SECONDS:-600}" uv run --project ingestion --locked pytest evals/ -v -p no:cacheprovider \
  2>&1 | tee "$STATE/eval.log"
status=${PIPESTATUS[0]}
# 4. the receipt (pass or fail) — the only evidence promotion accepts (scripts/receipt.py, RAG-05)
if [ -f "$STATE/eval-results.json" ]; then
  uv run -q --project ingestion --locked python scripts/receipt.py make --state "$STATE" "${target[@]}" >&2 \
    || { log "FAILED: could not write the receipt"; [ "$status" -eq 0 ] && status=1; }
else
  log "no eval-results.json: no receipt written (nothing can be promoted)"
fi
case "$status" in
  0)   log "PASS ($collection)";;
  124) log "FAILED: evaluation timed out";;
  5)   log "FAILED: pytest collected no tests";;
  *)   log "FAILED: evaluation exit $status";;
esac
exit "$status"

#!/usr/bin/env bash
# Run the S12 candidate ingestion Job for one release SHA and wait for it (RAG-02).
# Run FROM the clean exact-SHA release checkout (never your editing checkout):
#   scripts/with-release.sh <SHA> scripts/run-ingestion.sh <SHA>
#
# 1. builds the revision bundle + Job (scripts/ingest_bundle.py; refuses dirty/oversized/secret input)
# 2. creates/recreates ConfigMap ingest-bundle-<SHA> and Job ingest-docs-<SHA12> (never `kubectl apply`)
# 3. waits for the Job to really finish; prints and saves its (nonsecret) logs
# Exit: 0 = Job Complete and candidate COMPLETE or REUSED; 1 = bundle/Job failure or timeout; 2 = usage.
# Outputs in $RELEASE_STATE_DIR (default ~/releases/workbench-state/<SHA>): bundle-*.json, ingest-job.*.
set -uo pipefail

# Non-login SSH (CD) does not source the profile kubeconfig; use the k3s one (as scripts/deploy.sh).
if [ -z "${KUBECONFIG:-}" ] && [ -r /etc/rancher/k3s/k3s.yaml ]; then
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi

sha="${1:-${RELEASE_SHA:-}}"
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <full-40-hex-SHA>" >&2; exit 2; }
NS=workbench
STATE="${RELEASE_STATE_DIR:-${WB_RELEASE_STATE_ROOT:-$HOME/releases/workbench-state}/$sha}"
TIMEOUT="${INGEST_TIMEOUT_SECONDS:-600}"
mkdir -p "$STATE"
log() { echo "[run-ingestion] $*"; }

log "release $sha: building bundle"
if ! uv run -q --project ingestion --locked python scripts/ingest_bundle.py \
      --sha "$sha" --out-dir "$STATE" --deadline "$TIMEOUT" > "$STATE/bundle-build.log"; then
  log "FAILED: bundle refused (nothing created in the cluster)"; exit 1
fi
job="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["job"])' "$STATE/bundle-identity.json")"
cm="ingest-bundle-$sha"
log "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("collection", d["collection"], "corpus", d["corpus_hash"][:12], "bundle", d["bundle_hash"][:12], str(d["configmap_bytes"]) + " B", "image", d["image"])' "$STATE/bundle-identity.json")"

# recreate: an old Job/ConfigMap for this SHA (e.g. a failed attempt) is replaced, never patched
kubectl -n "$NS" delete job "$job" --ignore-not-found --wait=true >/dev/null
kubectl -n "$NS" delete configmap "$cm" --ignore-not-found >/dev/null
kubectl create -f "$STATE/bundle-configmap.json" >/dev/null || { log "FAILED: could not create ConfigMap $cm"; exit 1; }
kubectl create -f "$STATE/ingest-job.json" >/dev/null || { log "FAILED: could not create Job $job"; exit 1; }
log "job/$job created; waiting up to ${TIMEOUT}s"

deadline=$(( $(date +%s) + TIMEOUT + 30 ))
status=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  status="$(kubectl -n "$NS" get job "$job" -o jsonpath='{range .status.conditions[?(@.status=="True")]}{.type}{" "}{end}' 2>/dev/null)"
  case "$status" in *Complete*|*Failed*) break ;; esac
  sleep 5
done

kubectl -n "$NS" logs "job/$job" --tail=-1 > "$STATE/ingest-job.log" 2>&1 || true
sed 's/^/  | /' "$STATE/ingest-job.log"
kubectl -n "$NS" get job "$job" -o json > "$STATE/ingest-job.status.json" 2>/dev/null || true

case "$status" in
  *Complete*)
    if grep -qE '^(COMPLETE candidate|REUSED live candidate)' "$STATE/ingest-job.log"; then
      log "OK: job/$job Complete"; exit 0
    fi
    log "FAILED: job/$job Complete but the log has no COMPLETE/REUSED line"; exit 1 ;;
  *Failed*)
    reason="$(kubectl -n "$NS" get job "$job" -o jsonpath='{.status.conditions[?(@.type=="Failed")].reason}')"
    log "FAILED: job/$job failed ($reason) — see the log above and: kubectl -n $NS describe job $job"; exit 1 ;;
  *)
    log "FAILED: job/$job did not finish within ${TIMEOUT}s (pending image pull? no node capacity?) —"
    kubectl -n "$NS" get pods -l "job-name=$job" -o wide 2>&1 | sed 's/^/  | /'
    kubectl -n "$NS" get events --field-selector "involvedObject.kind=Pod" --sort-by=.lastTimestamp 2>/dev/null | tail -5 | sed 's/^/  | /'
    exit 1 ;;
esac

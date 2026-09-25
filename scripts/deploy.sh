#!/usr/bin/env bash
# Gated workbench release: Helm rollout + corpus promotion as ONE recoverable release (S9 WB-09, S12 RAG-07).
# Run FROM the clean exact-SHA release checkout:
#   scripts/with-release.sh <SHA> scripts/deploy.sh
#
#   1. receipt gate     — no passing, matching evaluation receipt -> exit 1, nothing changed
#   2. helm rollout     — helm upgrade --install --atomic --wait --timeout 3m (failure -> exit 1, alias untouched)
#   3. alias promotion  — scripts/promote-corpus.sh <SHA> (atomic; failure -> Helm rolled back)
#   4. smoke check      — authenticated ingress health (if enabled) + the deployed agent answers a course
#                         question via search_docs from THIS revision's corpus
#   any failure after 2 -> previous alias AND previous Helm revision restored (first release: uninstalled,
#   no alias left). Everything runs under the production lock. Record: $RELEASE_STATE_DIR/release-record.json.
set -uo pipefail

# CD runs arrive over a NON-login SSH session; fall back to the k3s kubeconfig (operations profile).
if [ -z "${KUBECONFIG:-}" ] && [ -r /etc/rancher/k3s/k3s.yaml ]; then
  export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
fi
here="$(dirname "$0")"
REL_SHA="${RELEASE_SHA:-$(git rev-parse HEAD)}"
STATE="${RELEASE_STATE_DIR:-.}"
NS="${WB_NAMESPACE:-workbench}"
REL="${WB_RELEASE:-workbench}"
VALUES="${WB_VALUES:-my-values.yaml}"
TIMEOUT="${WB_TIMEOUT:-3m}"
PY=(uv run -q --project ingestion --locked python)
log() { echo "[deploy] $*" >&2; }
[ "$(git rev-parse HEAD)" = "$REL_SHA" ] || { log "FAILED: checkout is not at $REL_SHA (use scripts/with-release.sh)"; exit 1; }

. "$here/production-lock.sh"
production_lock "deploy ${REL_SHA} (${GITHUB_RUN_ID:+actions run $GITHUB_RUN_ID}${GITHUB_RUN_ID:-shell})"

chart_ver="$(awk '/^version:/{print $2}' charts/ai-workbench/Chart.yaml)"
values_args=(); values_sha=none
if [ -f "$VALUES" ]; then values_args=(-f "$VALUES"); values_sha="$(sha256sum "$VALUES" | cut -c1-12)"; fi
prev_rev="$(helm -n "$NS" history "$REL" -o json 2>/dev/null | python3 -c 'import json,sys; d=[r["revision"] for r in json.load(sys.stdin) if r["status"]=="deployed"]; print(d[-1] if d else "")' 2>/dev/null)"

record() {  # status [detail...] -> release-record.json (nonsecret)
  local status="$1"; shift
  local new_rev alias imgs
  new_rev="$(helm -n "$NS" history "$REL" --max 1 -o json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["revision"])' 2>/dev/null || echo none)"
  imgs="$(kubectl -n "$NS" get deploy -o jsonpath='{range .items[*]}{.metadata.name}={.spec.template.spec.containers[0].image};{end}' 2>/dev/null)"
  alias="$(curl -fsS "${QDRANT_URL:-http://127.0.0.1:0}/aliases" 2>/dev/null | python3 -c 'import json,sys; print({a["alias_name"]:a["collection_name"] for a in json.load(sys.stdin)["result"]["aliases"]}.get("study_guides",""))' 2>/dev/null)"
  python3 - "$STATE/release-record.json" <<PY
import json, sys
json.dump({"sha": "$REL_SHA", "status": "$status", "detail": "$*", "chart_version": "$chart_ver",
           "values_sha256_12": "$values_sha", "helm_previous_revision": "${prev_rev:-none}",
           "helm_revision_now": "$new_rev", "alias_previous": "${prev_alias:-}" or None,
           "alias_now": "$alias" or None, "images_running": "$imgs"}, open(sys.argv[1], "w"), indent=2)
PY
  cat "$STATE/release-record.json" >&2
}

undo_helm() {  # restore the previous Helm revision, or uninstall a failed first release
  if [ -n "$prev_rev" ]; then
    log "restoring Helm revision $prev_rev"
    helm -n "$NS" rollback "$REL" "$prev_rev" --wait --timeout "$TIMEOUT" >&2
  else
    log "first release failed: uninstalling it"
    helm -n "$NS" uninstall "$REL" --wait >&2
  fi
}

compensate() {  # after helm succeeded: put alias AND Helm back; say so loudly if that fails
  local ok=0
  if [ "${promoted:-0}" = 1 ]; then
    if [ -n "${prev_alias:-}" ]; then
      "${PY[@]}" scripts/corpus_alias.py restore --to "$prev_alias" --state "$STATE" >&2 || ok=1
    else
      "${PY[@]}" scripts/corpus_alias.py remove --expect "study_guides_$REL_SHA" --state "$STATE" >&2 || ok=1
    fi
  fi
  undo_helm || ok=1
  if [ "$ok" -ne 0 ]; then
    log "COMPENSATION FAILED — production may be mixed. Run: scripts/recover-production.sh, then" \
        "scripts/promote-corpus.sh --restore ${prev_alias:-<previous collection>} (runbook §8)."
  fi
  return "$ok"
}

log "release ${REL_SHA} chart ${chart_ver} values ${values_sha} -> ns/${NS} (previous helm revision ${prev_rev:-none})"

# 1. receipt gate — before ANY mutation
. "$here/qdrant-forward.sh"
qdrant_forward "$STATE/deploy-forward.log" || { log "FAILED: no Qdrant forward; nothing changed"; exit 1; }
prev_alias="$(curl -fsS "$QDRANT_URL/aliases" | python3 -c 'import json,sys; print({a["alias_name"]:a["collection_name"] for a in json.load(sys.stdin)["result"]["aliases"]}.get("study_guides",""))')"
if ! "${PY[@]}" scripts/receipt.py verify --state "$STATE" --sha "$REL_SHA" --qdrant-url "$QDRANT_URL"; then
  log "FAILED: receipt rejected — no Helm rollout, no alias change"; record rejected "receipt rejected"; exit 1
fi

# 2. Helm rollout (--atomic restores the previous revision itself on failure)
if ! helm upgrade --install "$REL" charts/ai-workbench -n "$NS" --create-namespace "${values_args[@]}" \
      --atomic --wait --timeout "$TIMEOUT" >&2; then
  log "FAILED: Helm rollout failed — --atomic kept/restored the previous release; alias NOT promoted"
  record helm-failed "rollout failed; alias untouched"; exit 1
fi

# 3. alias promotion (inside our lock: promote-corpus.sh sees PRODUCTION_LOCK_HELD)
promoted=0
if ! "$here/promote-corpus.sh" "$REL_SHA"; then
  log "FAILED: alias promotion failed (promote-corpus restored the alias) — restoring Helm"
  compensate; record promote-failed "alias promotion failed; compensated=$?"; exit 1
fi
promoted=1

# 4. smoke: authenticated front door (when enabled) + the real retrieval path of THIS release
smoke_ok=1
ingress_host="$(kubectl -n "$NS" get ingress "$REL" -o jsonpath='{.spec.rules[0].host}' 2>/dev/null)"
if [ -n "$ingress_host" ]; then
  user="${WB_SMOKE_USER:-$(kubectl -n monitoring get secret workbench-probe-auth -o jsonpath='{.data.username}' 2>/dev/null | base64 -d)}"
  pass="${WB_SMOKE_PASS:-$(kubectl -n monitoring get secret workbench-probe-auth -o jsonpath='{.data.password}' 2>/dev/null | base64 -d)}"
  # Reach Traefik on THIS node (--resolve): the smoke runs on the VM, whose public address may be
  # firewalled for itself (security group opened only to your laptop); the path is still ingress + auth.
  code="$(curl -s --max-time 20 --resolve "$ingress_host:80:127.0.0.1" -o /dev/null -w '%{http_code}' \
          -u "$user:$pass" "http://$ingress_host/api/health")"; unset pass
  if [ "$code" = 200 ]; then log "smoke: authenticated ingress http://$ingress_host/api/health -> 200"
  else log "smoke: authenticated ingress http://$ingress_host/api/health -> $code"; smoke_ok=0; fi
fi
if [ "$smoke_ok" = 1 ] && ! "${PY[@]}" scripts/smoke_release.py --sha "$REL_SHA" --namespace "$NS" --deployment "$REL-pi-web-ui"; then
  smoke_ok=0
fi
if [ "$smoke_ok" != 1 ]; then
  log "FAILED: smoke check — restoring the previous alias and Helm revision"
  compensate; record smoke-failed "smoke failed; compensated=$?"; exit 1
fi

record deployed "helm rollout + alias promotion + smoke OK"
log "OK — release ${REL_SHA} is live (record: ${STATE}/release-record.json)"

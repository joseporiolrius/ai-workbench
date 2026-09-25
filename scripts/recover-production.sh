#!/usr/bin/env bash
# Recover production after an INTERRUPTED release (SSH dropped, run canceled, process killed) (RAG-08).
#   scripts/recover-production.sh            # from the ai-workbench root, on the VM
#
# Takes the same production lock as deploy/promotion (so it never races a live release), then:
#   - if the Helm release is stuck in pending-install/upgrade/rollback, rolls it back to the last
#     'deployed' revision (or uninstalls a first install that never completed);
#   - prints the resulting Helm revision/status, the images running and the live study_guides alias,
#     so you can compare them with the last GOOD release receipt before releasing again.
# It never promotes anything and never touches Qdrant collections. Exit 0 = production is in a
# settled state (verify it), 1 = could not settle it (read the output).
set -uo pipefail
if [ -z "${KUBECONFIG:-}" ] && [ -r /etc/rancher/k3s/k3s.yaml ]; then export KUBECONFIG=/etc/rancher/k3s/k3s.yaml; fi
NS="${WB_NAMESPACE:-workbench}"; REL="${WB_RELEASE:-workbench}"
. "$(dirname "$0")/production-lock.sh"
production_lock "recover-production"

status="$(helm -n "$NS" status "$REL" -o json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["status"])' 2>/dev/null)"
echo "[recover] helm release $REL status: ${status:-absent}"
case "$status" in
  pending-install|pending-upgrade|pending-rollback)
    last="$(helm -n "$NS" history "$REL" -o json | python3 -c 'import json,sys; d=[r["revision"] for r in json.load(sys.stdin) if r["status"] in ("deployed","superseded")]; print(d[-1] if d else "")')"
    if [ -n "$last" ]; then
      echo "[recover] rolling back the interrupted operation to revision $last"
      helm -n "$NS" rollback "$REL" "$last" --wait --timeout 3m || { echo "[recover] FAILED: rollback did not complete" >&2; exit 1; }
    else
      echo "[recover] first install never completed: uninstalling it"
      helm -n "$NS" uninstall "$REL" --wait || { echo "[recover] FAILED: uninstall did not complete" >&2; exit 1; }
    fi ;;
  failed) echo "[recover] last operation FAILED (not pending); --atomic already restored the previous revision if it could" ;;
  ""|deployed) ;;
esac

echo "[recover] now:"
helm -n "$NS" history "$REL" --max 3 2>/dev/null | sed 's/^/  /'
kubectl -n "$NS" get deploy -o jsonpath='{range .items[*]}  {.metadata.name} {.spec.template.spec.containers[0].image} ready={.status.readyReplicas}/{.status.replicas}{"\n"}{end}' 2>/dev/null
port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
kubectl -n "$NS" port-forward svc/workbench-qdrant "$port:6333" >/dev/null 2>&1 & pf=$!
trap 'kill $pf 2>/dev/null' EXIT
for _ in $(seq 1 20); do curl -fsS -o /dev/null "http://127.0.0.1:$port/healthz" 2>/dev/null && break; sleep 0.5; done
echo "  live alias: $(curl -fsS "http://127.0.0.1:$port/aliases" 2>/dev/null | python3 -c 'import json,sys; a={x["alias_name"]:x["collection_name"] for x in json.load(sys.stdin)["result"]["aliases"]}; print("study_guides ->", a.get("study_guides","(none)"))' 2>/dev/null || echo unknown)"
echo "[recover] compare with the last good receipt (~/releases/workbench-state/<SHA>/receipt.json), then re-run the release"

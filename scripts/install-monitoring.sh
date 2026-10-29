#!/usr/bin/env bash
# S10 monitoring installer (MON-02): three INDEPENDENT Helm releases in namespace
# `monitoring` — prometheus, blackbox, grafana — from the pinned charts and
# mirrored images recorded in course-artifacts.yaml. Idempotent: re-running
# converges to the same three healthy releases.
#
#   ./scripts/install-monitoring.sh --dry-run   # print the exact Helm commands, change nothing
#   ./scripts/install-monitoring.sh             # preflight, install/upgrade, wait for readiness
#
# Env (optional): WORKBENCH_NS (workbench), WORKBENCH_RELEASE (workbench),
#                 WORKBENCH_URL (default: https://<assigned workbench hostname>/),
#                 MONITORING_TIMEOUT (5m), MONITORING_EXTRA_VALUES_<RELEASE> (file[:file])
#
# It never reads, prints or passes a credential: the probe credentials live only
# in Secret monitoring/workbench-probe-auth (see monitoring/README.md); this
# script checks that the Secret has non-empty username/password keys and FAILS
# preflight otherwise, instead of installing an exporter that can only report 0.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INV=(python3 "$ROOT/scripts/monitoring-inventory.py")
NS=monitoring
WORKBENCH_NS="${WORKBENCH_NS:-workbench}"
WORKBENCH_RELEASE="${WORKBENCH_RELEASE:-workbench}"
PROBE_SECRET=workbench-probe-auth
RELEASES=(prometheus blackbox grafana)
TIMEOUT="${MONITORING_TIMEOUT:-5m}"   # per-release helm --wait budget
DRY_RUN=0

case "${1:-}" in
  --dry-run) DRY_RUN=1 ;;
  "") ;;
  -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 64 ;;
esac

say()  { printf '==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

for bin in helm python3; do command -v "$bin" >/dev/null || fail "$bin not found"; done
python3 -c 'import yaml' 2>/dev/null || fail "python3 PyYAML missing (sudo apt-get install -y python3-yaml)"
[[ $DRY_RUN -eq 1 ]] || command -v kubectl >/dev/null || fail "kubectl not found"

# 1. Inventory gate: pins complete + every rendered image an approved mirror.
say "inventory check (course-artifacts.yaml)"
"${INV[@]}" check >/dev/null || fail "inventory check failed — run: ${INV[*]} check"

# 2. Probe target = the authenticated workbench URL (not a secret).
if [[ -z "${WORKBENCH_URL:-}" ]]; then
  host="$(kubectl -n "$WORKBENCH_NS" get ingress "$WORKBENCH_RELEASE" \
            -o jsonpath='{.spec.rules[0].host}' 2>/dev/null || true)"
  if [[ -n "$host" ]]; then
    WORKBENCH_URL="https://$host/"
  elif [[ $DRY_RUN -eq 1 ]]; then
    WORKBENCH_URL="https://wb.a000.dbai24.i40sys.com/"
  else
    fail "cannot find Ingress $WORKBENCH_NS/$WORKBENCH_RELEASE host; set WORKBENCH_URL"
  fi
fi

# Never send the probe credential over plaintext or to an arbitrary host.
[[ "$WORKBENCH_URL" =~ ^https://wb\.a[0-9]{3}\.dbai24\.i40sys\.com/?$ ]] ||
  fail "WORKBENCH_URL must be the assigned https://wb.aNNN.dbai24.i40sys.com/"

helm_cmd() {  # prints one release's full command, one arg per line
  local rel="$1" args
  mapfile -t args < <("${INV[@]}" helm-args "$rel")
  printf '%s\n' helm upgrade --install "$rel" "${args[@]}"
  [[ "$rel" == prometheus ]] && printf '%s\n' --set "workbenchProbe.url=$WORKBENCH_URL"
  printf '%s\n' --wait --timeout "$TIMEOUT"
}

if [[ $DRY_RUN -eq 1 ]]; then
  say "dry run — commands that would run (charts verified against chart_digest):"
  for rel in "${RELEASES[@]}"; do
    mapfile -t cmd < <(helm_cmd "$rel")
    printf ' %q' "${cmd[@]}"; printf '\n'
  done
  exit 0
fi

# 3. Preflight against the live cluster.
say "preflight"
kubectl get nodes >/dev/null || fail "cluster unreachable (kubectl get nodes)"
kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS" >/dev/null
for key in username password; do
  # (|| true: a missing Secret must reach the explicit error below, not a silent set -e exit)
  len="$( { kubectl -n "$NS" get secret "$PROBE_SECRET" -o jsonpath="{.data.$key}" 2>/dev/null || true; } | wc -c)"
  [[ "$len" -gt 0 ]] || fail "preflight: Secret $NS/$PROBE_SECRET has no '$key' — create it first
       (monitoring/README.md › Probe credentials). Refusing to install a probe that can only fail."
done
say "probe target: $WORKBENCH_URL"

# 4. Install/upgrade each independent release; --wait makes Helm fail on unready pods.
for rel in "${RELEASES[@]}"; do
  mapfile -t cmd < <(helm_cmd "$rel")
  say "helm upgrade --install $rel"
  "${cmd[@]}" >/dev/null || fail "helm upgrade --install $rel failed"
done

# 5. Readiness: every release deployed and every workload rolled out.
say "readiness"
for rel in "${RELEASES[@]}"; do
  st="$(helm -n "$NS" status "$rel" -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["status"])')"
  [[ "$st" == deployed ]] || fail "release $rel is $st"
done
for w in $(kubectl -n "$NS" get deploy,daemonset,statefulset -o name); do
  kubectl -n "$NS" rollout status "$w" --timeout=120s >/dev/null || fail "$w not ready"
done
helm -n "$NS" list
kubectl -n "$NS" get pods
say "monitoring ready — next: monitoring/README.md › Verify"

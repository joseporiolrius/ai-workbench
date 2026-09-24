#!/usr/bin/env bash
# S9 workbench chart deploy with a verifiable release receipt (WB-09).
# Run FROM a clean exact-SHA release checkout (via scripts/with-release.sh):
#   scripts/with-release.sh <sha> scripts/deploy.sh
# It deploys the chart + my-values.yaml atomically and writes a receipt that
# identifies the triggering SHA, chart/values identity and the images actually
# running. A failed/timed-out rollout fails the command; --atomic preserves or
# restores the prior working release.
set -eu

REL_SHA="${RELEASE_SHA:-$(git rev-parse HEAD)}"
STATE="${RELEASE_STATE_DIR:-.}"
NS="${WB_NAMESPACE:-workbench}"
REL="${WB_RELEASE:-workbench}"
VALUES="${WB_VALUES:-my-values.yaml}"
TIMEOUT="${WB_TIMEOUT:-180s}"

chart_ver="$(awk '/^version:/{print $2}' charts/ai-workbench/Chart.yaml)"
values_sha="$( [ -f "$VALUES" ] && sha256sum "$VALUES" | cut -c1-12 || echo none )"

echo "[deploy] release ${REL_SHA} chart ${chart_ver} values ${values_sha} -> ns/${NS}"
# --atomic: a failed upgrade rolls back to the prior working release (WB-09 AC#4)
if ! helm upgrade --install "$REL" charts/ai-workbench -n "$NS" --create-namespace \
      ${VALUES:+$( [ -f "$VALUES" ] && echo -f "$VALUES" )} \
      --atomic --wait --timeout "$TIMEOUT"; then
  echo "[deploy] FAILED — prior release preserved/restored by --atomic" >&2
  printf '{"sha":"%s","status":"failed","chart":"%s"}\n' "$REL_SHA" "$chart_ver" > "${STATE}/receipt.json"
  exit 1
fi

# images actually running + readiness (WB-09 AC#2/#3)
imgs="$(kubectl -n "$NS" get deploy -o jsonpath='{range .items[*]}{.metadata.name}={.spec.template.spec.containers[0].image}{"\n"}{end}')"
ready="$(kubectl -n "$NS" get deploy -o jsonpath='{range .items[*]}{.metadata.name}={.status.readyReplicas}/{.status.replicas}{" "}{end}')"

{ printf '{\n  "sha": "%s",\n  "chart_version": "%s",\n  "values_sha256_12": "%s",\n' "$REL_SHA" "$chart_ver" "$values_sha"
  printf '  "images_running": "%s",\n  "ready": "%s",\n  "status": "deployed"\n}\n' "$(echo "$imgs" | tr '\n' ';')" "$ready"
} > "${STATE}/receipt.json"
echo "[deploy] OK — receipt at ${STATE}/receipt.json"
cat "${STATE}/receipt.json"

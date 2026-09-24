#!/usr/bin/env bash
# Bounded, authenticated UI HTTP load through the S9 Traefik route (MON-06).
#
#   ./scripts/loadgen.sh [-n REQUESTS] [-c CONCURRENCY]      # defaults: -n 300 -c 4
#
# What it exercises: Traefik basic-auth -> pi-web-ui HTTP (GET / and /health).
# What it does NOT do: no chat, no model tokens, no gateway spend, no Qdrant
# query — use scripts/qdrant-load.py for vector-store traffic.
#
# Credentials come from Secret monitoring/workbench-probe-auth (the same user the
# probe uses) into a 0600 curl config in a temp dir that is shredded on exit;
# they never appear on a command line, in output, or in the repository.
# Every non-2xx (401 wrong credential, 404/502/503 backend gone, 000 no answer)
# is counted as FAILED, and any failure makes the exit status nonzero.
# Env: WORKBENCH_URL (default: http://<workbench Ingress host>/), WORKBENCH_NS,
#      WORKBENCH_AUTH_SECRET (default monitoring/workbench-probe-auth; keys username/password).
set -euo pipefail

N=300; C=4
while getopts "n:c:h" o; do
  case "$o" in
    n) N="$OPTARG" ;; c) C="$OPTARG" ;;
    *) sed -n '2,16p' "$0"; exit 64 ;;
  esac
done
[[ "$N" =~ ^[0-9]+$ && "$N" -ge 1 && "$N" -le 5000 ]] || { echo "ERROR: -n must be 1..5000" >&2; exit 64; }
[[ "$C" =~ ^[0-9]+$ && "$C" -ge 1 && "$C" -le 16 ]]   || { echo "ERROR: -c must be 1..16" >&2; exit 64; }

WORKBENCH_NS="${WORKBENCH_NS:-workbench}"
if [[ -z "${WORKBENCH_URL:-}" ]]; then
  host="$(kubectl -n "$WORKBENCH_NS" get ingress workbench -o jsonpath='{.spec.rules[0].host}')"
  WORKBENCH_URL="http://$host/"
fi
URL="${WORKBENCH_URL%/}"

umask 077
TMP="$(mktemp -d)"
trap 'find "$TMP" -type f -exec shred -u {} + 2>/dev/null; rm -rf "$TMP"' EXIT INT TERM
AUTH_SECRET="${WORKBENCH_AUTH_SECRET:-monitoring/workbench-probe-auth}"   # namespace/name
get() { kubectl -n "${AUTH_SECRET%%/*}" get secret "${AUTH_SECRET#*/}" -o jsonpath="{.data.$1}" | base64 -d; }
esc() { sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
{ printf 'user = "'; { get username; printf ':'; get password; } | esc; printf '"\n'; } > "$TMP/curl.cfg"

# `|| true`: a refused/timed-out request still prints its code (000) and is COUNTED
# as a failure below, instead of aborting the run before the report.
one() { curl -s -o /dev/null -m 10 -K "$TMP/curl.cfg" -w '%{http_code} %{time_total}\n' "$1" || true; }
export -f one; export TMP

# Preflight: one authenticated request must succeed before we call anything "load".
code="$(one "$URL/" | cut -d' ' -f1)"
if [[ "$code" != 2* ]]; then
  echo "ERROR: preflight GET $URL/ -> HTTP $code (401 = wrong/rotated credential; 404/502/503/000 = backend or route down). No load sent." >&2
  exit 1
fi

echo "load: $N authenticated GETs (alternating / and /health) at concurrency $C -> $URL"
start=$(date +%s)
for i in $(seq 1 "$N"); do (( i % 2 )) && echo "$URL/" || echo "$URL/health"; done \
  | xargs -P "$C" -I{} bash -c 'one "$1"' _ {} > "$TMP/results"
secs=$(( $(date +%s) - start ))
ok=$(awk '$1 ~ /^2/' "$TMP/results" | wc -l)
bad=$(( N - ok ))
echo "status codes:"; cut -d' ' -f1 "$TMP/results" | sort | uniq -c | sed 's/^/  /'
awk '{s+=$2} END {printf "mean latency: %.3fs\n", s/NR}' "$TMP/results"
echo "result: $ok ok, $bad FAILED in ${secs}s (UI HTTP only — 0 chat requests, 0 tokens, 0 Qdrant calls)"
[[ "$bad" -eq 0 ]]

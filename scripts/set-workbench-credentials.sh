#!/usr/bin/env bash
# Secret entry / rotation for the workbench basic-auth user (MON-03).
#
# ONE credential, TWO consumers, updated TOGETHER:
#   workbench/workbench-basic-auth   key `users`      bcrypt htpasswd line  -> Traefik (S9 ingress)
#   monitoring/workbench-probe-auth  keys username, password  (plain files) -> blackbox probe
#   monitoring/grafana-basic-auth    key `users`      same htpasswd       -> S10 homework Grafana route
#
#   ./scripts/set-workbench-credentials.sh            # prompts: username, password (hidden, twice)
#
# The values only ever exist in a 0700 temp dir (umask 077) that is shredded on
# exit, and are handed to kubectl as --from-file. Nothing is echoed, logged,
# passed on a command line, or written inside the repository.
set -euo pipefail

WORKBENCH_NS="${WORKBENCH_NS:-workbench}"
NS=monitoring
command -v htpasswd >/dev/null || { echo "ERROR: htpasswd missing (sudo apt-get install -y apache2-utils)" >&2; exit 1; }
command -v kubectl  >/dev/null || { echo "ERROR: kubectl missing" >&2; exit 1; }

umask 077
TMP="$(mktemp -d)"
cleanup() { find "$TMP" -type f -exec shred -u {} + 2>/dev/null || true; rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

read -r -p "workbench username: " user
[[ "$user" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "ERROR: username must be [A-Za-z0-9._-]+" >&2; exit 1; }
read -r -s -p "new password: " pw1; echo
read -r -s -p "repeat password: " pw2; echo
[[ "$pw1" == "$pw2" ]] || { echo "ERROR: passwords differ" >&2; exit 1; }
[[ ${#pw1} -ge 12 ]]   || { echo "ERROR: use at least 12 characters" >&2; exit 1; }

printf '%s' "$user" > "$TMP/username"
printf '%s' "$pw1"  > "$TMP/password"
unset pw1 pw2
# htpasswd -i reads the password from stdin (never argv); -B = bcrypt, as in S9.
htpasswd -niB "$user" < "$TMP/password" > "$TMP/users"

apply_secret() {  # ns name --from-file args...
  local ns="$1" name="$2"; shift 2
  kubectl -n "$ns" create secret generic "$name" "$@" --dry-run=client -o yaml \
    | kubectl apply -f - >/dev/null
  echo "updated $ns/$name"
}
kubectl get ns "$NS" >/dev/null 2>&1 || kubectl create namespace "$NS" >/dev/null
apply_secret "$WORKBENCH_NS" workbench-basic-auth --from-file=users="$TMP/users"
apply_secret "$NS" workbench-probe-auth --from-file=username="$TMP/username" --from-file=password="$TMP/password"
# Copy for the S10 homework Grafana route (a Traefik Middleware can only read a
# Secret in its own namespace). Harmless until that route exists.
apply_secret "$NS" grafana-basic-auth --from-file=users="$TMP/users"
echo "done — Traefik picks up the new htpasswd immediately; the probe reads its"
echo "files on every probe once the kubelet refreshes the Secret volume (<= ~1-2 min)."

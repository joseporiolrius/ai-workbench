#!/usr/bin/env bash
# Open THIS script's own Qdrant port-forward on a free localhost port and wait until it answers.
#   . scripts/qdrant-forward.sh; qdrant_forward <logfile>   -> exports QDRANT_URL, QDRANT_FORWARD_PID
# Cleanup (kills only this forward) is registered on EXIT; callers keep their own INT/TERM handling.
qdrant_forward() {
  local log="${1:-/dev/null}" port
  port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
  kubectl -n "${WB_NAMESPACE:-workbench}" port-forward "svc/${EVAL_QDRANT_SERVICE:-workbench-qdrant}" "${port}:6333" >"$log" 2>&1 &
  QDRANT_FORWARD_PID=$!
  trap 'kill "$QDRANT_FORWARD_PID" 2>/dev/null; wait "$QDRANT_FORWARD_PID" 2>/dev/null' EXIT
  for _ in $(seq 1 40); do
    kill -0 "$QDRANT_FORWARD_PID" 2>/dev/null || { echo "port-forward exited: $(tail -1 "$log")" >&2; return 1; }
    curl -fsS -o /dev/null "http://127.0.0.1:${port}/healthz" 2>/dev/null && { export QDRANT_URL="http://127.0.0.1:${port}" QDRANT_FORWARD_PID; return 0; }
    sleep 0.5
  done
  echo "Qdrant not ready on 127.0.0.1:${port} after 20 s" >&2; return 1
}

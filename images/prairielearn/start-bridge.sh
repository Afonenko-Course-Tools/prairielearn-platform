#!/bin/bash
set -euo pipefail
/PrairieLearn/scripts/init.sh &
pl_pid=$!
trap 'kill "$pl_pid" "${bridge_pid:-$pl_pid}" 2>/dev/null || true' EXIT TERM INT
for attempt in $(seq 1 180); do
  if curl -fsS http://127.0.0.1:3000/pl/webhooks/ping >/dev/null; then break; fi
  kill -0 "$pl_pid"
  sleep 1
done
curl -fsS http://127.0.0.1:3000/pl/webhooks/ping >/dev/null
cd /PrairieLearn
NODE_ENV=production node apps/prairielearn/bridge/server.mjs &
bridge_pid=$!
wait -n "$pl_pid" "$bridge_pid"
exit 1

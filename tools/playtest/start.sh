#!/usr/bin/env bash
# Start one isolated playtest seat: backend on 8800+N, driver on 9300+N, files under $PT_ROOT/seatN.
#   tools/playtest/start.sh N fresh|setup        (stop: tools/playtest/stop.sh N)
set -euo pipefail
"$(dirname "$0")/stop.sh" "${1:?seat number}" >/dev/null
N=${1:?seat number}; PROFILE=${2:-fresh}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PT_ROOT=${PT_ROOT:-/tmp/monkey-playtest}
SEAT="$PT_ROOT/seat$N"; rm -rf "$SEAT"; mkdir -p "$SEAT"
BP=$((8800 + N)); DP=$((9300 + N))
cd "$ROOT"
TZ=America/Chicago nohup "$ROOT/.venv/bin/python" -m tools.playtest.backend --port $BP --data "$SEAT/data" --profile "$PROFILE" > "$SEAT/backend.log" 2>&1 &
echo $! > "$SEAT/backend.pid"
for i in $(seq 1 60); do curl -s -o /dev/null "http://127.0.0.1:$BP/" && break; sleep 0.5; done
nohup node "$ROOT/tools/playtest/driver.js" $DP $BP "$SEAT/shots" > "$SEAT/driver.log" 2>&1 &
echo $! > "$SEAT/driver.pid"
for i in $(seq 1 60); do curl -s -o /dev/null "http://127.0.0.1:$DP/log" && break; sleep 0.5; done
echo "seat $N ready: driver http://127.0.0.1:$DP  (backend $BP, profile $PROFILE, files $SEAT)"

#!/usr/bin/env bash
N=${1:?seat number}; SEAT=${PT_ROOT:-/tmp/monkey-playtest}/seat$N
for f in "$SEAT"/*.pid; do [ -f "$f" ] && kill -9 "$(cat "$f")" 2>/dev/null || true; done
pkill -9 -f "driver.js $((9300 + N)) " 2>/dev/null || true
pkill -9 -f "tools.playtest.backend --port $((8800 + N)) " 2>/dev/null || true
sleep 0.5
echo "seat $N stopped"

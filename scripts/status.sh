#!/usr/bin/env bash
# Print status (PID + listening port) for the dev stack.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/scripts/.run"

report() {
  local name="$1"
  local pidfile="$RUN_DIR/$2.pid"
  local port="$3"
  local pid=""
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile" 2>/dev/null || true)"
  fi
  local listening="down"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      listening="up"
    fi
    printf "%-12s pid=%-6s port=%-5s %s\n" "$name" "$pid" "$port" "$listening"
  else
    printf "%-12s pid=%-6s port=%-5s %s\n" "$name" "-" "$port" "$listening"
  fi
}

report "gunicorn"  gunicorn  5000
report "next dev"  next-dev  3000
report "tv-bridge" tv-bridge 5002
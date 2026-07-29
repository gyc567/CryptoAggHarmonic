#!/usr/bin/env bash
# Stop both backend and frontend dev servers started via the scripts/ helpers.
# Safe to run multiple times; unknown PIDs are ignored.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/scripts/.run"

stop_from_pidfile() {
  local name="$1"
  local pidfile="$RUN_DIR/$2.pid"
  if [[ ! -f "$pidfile" ]]; then
    echo "$name: no pidfile ($pidfile), skipping"
    return 0
  fi
  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    echo "$name: not running (stale pidfile $pidfile)"
    rm -f "$pidfile"
    return 0
  fi
  echo "$name: stopping pid=$pid..."
  kill "$pid" || true
  for _ in 1 2 3 4 5; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name: still alive after 5s, sending SIGKILL"
    kill -9 "$pid" || true
  fi
  rm -f "$pidfile"
}

# Stop frontend first so it doesn't error on backend going away mid-request.
stop_from_pidfile "next dev"  "next-dev"
stop_from_pidfile "tv-bridge" "tv-bridge"
stop_from_pidfile "gunicorn"   "gunicorn"

echo "Done."
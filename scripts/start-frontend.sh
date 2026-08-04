#!/usr/bin/env bash
# Start the Next.js dev server fully detached.
#
# See scripts/start-backend.sh for the why-detached rationale.
#
# Usage:
#   scripts/start-frontend.sh
#   scripts/start-frontend.sh restart
#
# State files live under scripts/.run/ (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FRONTEND="$ROOT/frontend"
RUN_DIR="$ROOT/scripts/.run"
mkdir -p "$RUN_DIR"
PIDFILE="$RUN_DIR/next-dev.pid"
LOG="$RUN_DIR/next-dev.log"

# Backend URL is consumed by the Next.js dev server via process env when
# proxied routes resolve. Both the global var (production / Vercel) and
# BACKEND_API_BASE (used by next.config rewrites) point at local Flask.
export BACKEND_API_BASE="${BACKEND_API_BASE:-http://127.0.0.1:5001}"

cd "$FRONTEND"

if [[ "${1:-}" == "restart" ]]; then
  # Stop the tracked npm wrapper (if still alive) and anything holding port 3000.
  if [[ -f "$PIDFILE" ]]; then
    OLDPID="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [[ -n "$OLDPID" ]] && kill -0 "$OLDPID" 2>/dev/null; then
      echo "Stopping existing next dev (pid=$OLDPID)..."
      kill "$OLDPID" 2>/dev/null || true
      for _ in 1 2 3 4 5; do
        kill -0 "$OLDPID" 2>/dev/null || break
        sleep 1
      done
    fi
  fi
  PORT_PID="$(lsof -ti:3000 2>/dev/null || true)"
  if [[ -n "$PORT_PID" ]]; then
    echo "Killing process holding port 3000 (pid=$PORT_PID)..."
    kill -9 "$PORT_PID" 2>/dev/null || true
    sleep 1
  fi
fi

PORT_PID="$(lsof -ti:3000 2>/dev/null || true)"
if [[ -n "$PORT_PID" ]]; then
  echo "next dev already running on port 3000 (pid=$PORT_PID). Use 'restart' or stop it first."
  exit 0
fi

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "ERROR: $FRONTEND/node_modules missing. Run 'cd frontend && npm install' first." >&2
  exit 1
fi

nohup npm run dev >"$LOG" 2>&1 </dev/null &
WRAPPER_PID=$!
disown "$WRAPPER_PID" 2>/dev/null || true

# Wait for the actual next-server process to bind port 3000.
SERVER_PID=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  SERVER_PID="$(lsof -ti:3000 2>/dev/null || true)"
  if [[ -n "$SERVER_PID" ]]; then
    break
  fi
  sleep 1
done

if [[ -z "$SERVER_PID" ]]; then
  echo "ERROR: Next.js dev server did not start on port 3000 (wrapper pid=$WRAPPER_PID)." >&2
  exit 1
fi

echo "$SERVER_PID" >"$PIDFILE"

echo "next dev started: server pid=$SERVER_PID (BACKEND_API_BASE=$BACKEND_API_BASE)"
echo "  log:  $LOG"
echo "  stop: kill \$(cat $PIDFILE)"
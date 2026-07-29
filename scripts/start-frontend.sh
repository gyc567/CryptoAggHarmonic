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
export BACKEND_API_BASE="${BACKEND_API_BASE:-http://127.0.0.1:5000}"

cd "$FRONTEND"

if [[ "${1:-}" == "restart" ]] && [[ -f "$PIDFILE" ]]; then
  OLDPID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLDPID" ]] && kill -0 "$OLDPID" 2>/dev/null; then
    echo "Stopping existing next dev (pid=$OLDPID)..."
    kill "$OLDPID" || true
    # next-server child may take a moment to exit
    for _ in 1 2 3 4 5; do
      kill -0 "$OLDPID" 2>/dev/null || break
      sleep 1
    done
  fi
fi

if [[ -f "$PIDFILE" ]]; then
  CUR="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$CUR" ]] && kill -0 "$CUR" 2>/dev/null; then
    echo "next dev already running (pid=$CUR). Use 'restart' or stop it first."
    exit 0
  fi
fi

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "ERROR: $FRONTEND/node_modules missing. Run 'cd frontend && npm install' first." >&2
  exit 1
fi

nohup npm run dev >"$LOG" 2>&1 </dev/null &
PID=$!
echo "$PID" >"$PIDFILE"
disown "$PID" 2>/dev/null || true

echo "next dev started: pid=$PID (BACKEND_API_BASE=$BACKEND_API_BASE)"
echo "  log:  $LOG"
echo "  stop: kill \$(cat $PIDFILE)"
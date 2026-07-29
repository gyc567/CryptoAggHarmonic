#!/usr/bin/env bash
# Start the Flask backend (gunicorn) fully detached.
#
# Why detached: when run inside `jcode`'s `run_in_background: true` wrapper, a
# child process gets killed after the wrapper hits its 10-minute timeout.
# `nohup ... &` + `disown` + closed stdin reparents the process to PID 1 so
# it survives jcode session changes, terminal hangups, and the wrapper exit.
#
# Usage:
#   scripts/start-backend.sh
#   scripts/start-backend.sh restart
#
# State files live under scripts/.run/ (gitignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/scripts/.run"
mkdir -p "$RUN_DIR"
PIDFILE="$RUN_DIR/gunicorn.pid"
LOG="$RUN_DIR/gunicorn.log"

cd "$ROOT"

if [[ "${1:-}" == "restart" ]] && [[ -f "$PIDFILE" ]]; then
  OLDPID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLDPID" ]] && kill -0 "$OLDPID" 2>/dev/null; then
    echo "Stopping existing gunicorn (pid=$OLDPID)..."
    kill "$OLDPID" || true
    # Wait for graceful shutdown (workers + master)
    for _ in 1 2 3 4 5; do
      kill -0 "$OLDPID" 2>/dev/null || break
      sleep 1
    done
  fi
fi

if [[ -f "$PIDFILE" ]]; then
  CUR="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$CUR" ]] && kill -0 "$CUR" 2>/dev/null; then
    echo "gunicorn already running (pid=$CUR). Use 'restart' or stop it first."
    exit 0
  fi
fi

# Sanity: make sure venv exists
if [[ ! -x "$ROOT/.venv/bin/gunicorn" ]]; then
  echo "ERROR: $ROOT/.venv/bin/gunicorn not found. Create venv and install deps first." >&2
  exit 1
fi

nohup "$ROOT/.venv/bin/gunicorn" --config gunicorn.conf.py app.main:app \
  >"$LOG" 2>&1 </dev/null &
PID=$!
echo "$PID" >"$PIDFILE"
disown "$PID" 2>/dev/null || true

echo "gunicorn started: pid=$PID"
echo "  log:  $LOG"
echo "  stop: kill \$(cat $PIDFILE)"
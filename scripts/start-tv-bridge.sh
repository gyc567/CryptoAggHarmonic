#!/usr/bin/env bash
# Start the TradingView Node.js bridge (port 5002) detached.
# Required when USE_TRADINGVIEW=true in .env.
#
# Usage:
#   scripts/start-tv-bridge.sh
#   scripts/start-tv-bridge.sh restart
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE="$ROOT/tradingview-bridge"
RUN_DIR="$ROOT/scripts/.run"
mkdir -p "$RUN_DIR"
PIDFILE="$RUN_DIR/tv-bridge.pid"
LOG="$RUN_DIR/tv-bridge.log"

if [[ ! -d "$BRIDGE/node_modules" ]]; then
  echo "Installing TradingView bridge deps (first run only)..."
  (cd "$BRIDGE" && npm install --no-audit --no-fund --loglevel=error >/dev/null 2>&1)
fi

cd "$BRIDGE"

if [[ "${1:-}" == "restart" ]] && [[ -f "$PIDFILE" ]]; then
  OLDPID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLDPID" ]] && kill -0 "$OLDPID" 2>/dev/null; then
    echo "Stopping existing tv-bridge (pid=$OLDPID)..."
    kill "$OLDPID" || true
    for _ in 1 2 3 4 5; do
      kill -0 "$OLDPID" 2>/dev/null || break
      sleep 1
    done
  fi
fi

if [[ -f "$PIDFILE" ]]; then
  CUR="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$CUR" ]] && kill -0 "$CUR" 2>/dev/null; then
    echo "tv-bridge already running (pid=$CUR). Use 'restart' or stop it first."
    exit 0
  fi
fi

nohup npm start >"$LOG" 2>&1 </dev/null &
PID=$!
echo "$PID" >"$PIDFILE"
disown "$PID" 2>/dev/null || true

echo "tv-bridge started: pid=$PID"
echo "  log:  $LOG"
echo "  stop: kill \$(cat $PIDFILE)"
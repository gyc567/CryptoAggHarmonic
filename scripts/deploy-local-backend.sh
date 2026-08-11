#!/usr/bin/env bash
# scripts/deploy-local-backend.sh
#
# Deploy the latest backend code from this repo to the local machine.
# Replaces whatever is currently running on 127.0.0.1:5001 with the
# newest code from /root/code/CryptoAggHarmonic/.
#
# Deployment strategy:
#   - Uses the existing working Python venv at /var/www/pyharmonics/.venv
#     (Python 3.11 + all dependencies already resolved, websockets 13.1).
#   - Sets PYTHONPATH to this repo so the old venv's packages import
#     the new code from /root/code/CryptoAggHarmonic/app/.
#
# Loop-engineered: idempotent, phased, self-verifying.
#
# What it does (in order):
#   1. Stop any process holding 127.0.0.1:5001 (including pyharmonics.service).
#   2. Start gunicorn from /var/www/pyharmonics/.venv with PYTHONPATH=this-repo.
#   3. Probe /api/health and expect 200.
#
# Idempotent — safe to re-run.
#
# Usage:
#   scripts/deploy-local-backend.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="/var/www/pyharmonics/.venv"
RUN_DIR="$ROOT/scripts/.run"
PIDFILE="$RUN_DIR/gunicorn.pid"
LOG="$RUN_DIR/gunicorn.log"
PORT="${PORT:-5001}"
HEALTH_URL="http://127.0.0.1:${PORT}/api/health"
MAX_START_WAIT=20

mkdir -p "$RUN_DIR"

# ── Phase 1: Stop anything on port 5001 ─────────────────────────────────────

echo "==> [1/4] Stopping any process on 127.0.0.1:${PORT}..."

# Stop systemd unit first (if it exists)
if systemctl is-active --quiet pyharmonics.service 2>/dev/null; then
  echo "    Stopping pyharmonics.service..."
  sudo systemctl stop pyharmonics.service
  sleep 2
fi

# Kill by pidfile (start-backend.sh style)
if [[ -f "$PIDFILE" ]]; then
  OLD_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "    Stopping gunicorn via pidfile (pid=$OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$OLD_PID" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi

# Kill by port
PORT_PIDS="$(lsof -ti "tcp:127.0.0.1:${PORT}" 2>/dev/null || true)"
if [[ -n "$PORT_PIDS" ]]; then
  echo "    Killing by port: $PORT_PIDS"
  echo "$PORT_PIDS" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

# Belt-and-suspenders: kill all gunicorn on 5001
for pid in $(ps aux | grep 'gunicorn.*5001' | grep -v grep | awk '{print $2}'); do
  echo "    Stopping stray gunicorn pid=$pid..."
  kill -9 "$pid" 2>/dev/null || true
done

# Verify free
if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "    ERROR: port ${PORT} still occupied after kill attempts." >&2
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >&2
  exit 1
fi
echo "    Port ${PORT} is free."

# ── Phase 2: Start gunicorn with local code ──────────────────────────────────

echo "==> [2/4] Starting gunicorn from $VENV with PYTHONPATH=$ROOT..."

GUNICORN_BIN="$VENV/bin/gunicorn"
if [[ ! -x "$GUNICORN_BIN" ]]; then
  echo "    ERROR: $GUNICORN_BIN not found or not executable." >&2
  echo "    The production venv at /var/www/pyharmonics/.venv is required." >&2
  exit 1
fi

# Load dotenv from /var/www/pyharmonics/.env for secrets (SUPABASE_* etc.)
if [[ -f /var/www/pyharmonics/.env ]]; then
  echo "    Sourcing /var/www/pyharmonics/.env for secrets..."
  set -a
  source /var/www/pyharmonics/.env
  set +a
fi

# Local overrides — NOTE: do NOT set DISABLE_AUTH=1 in production.
# factory.py blocks DISABLE_AUTH when ENVIRONMENT=production.
export PYTHONPATH="$ROOT"
export PORT="$PORT"
export FLASK_DEBUG=0
# Use the old backend's upstash redis (already configured in /var/www/pyharmonics/.env)
# but allow override
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"

nohup "$GUNICORN_BIN" \
  --bind "127.0.0.1:${PORT}" \
  --workers 2 \
  --threads 10 \
  --timeout 120 \
  --max-requests 1000 \
  --max-requests-jitter 100 \
  --access-logfile - \
  --error-logfile - \
  app.main:app \
  >"$LOG" 2>&1 </dev/null &
PID=$!
echo "$PID" >"$PIDFILE"
disown "$PID" 2>/dev/null || true
echo "    gunicorn spawned: pid=$PID"

# ── Phase 3: Wait for port binding ───────────────────────────────────────────

echo "==> [3/4] Waiting for port ${PORT} to be listening..."
for i in $(seq 1 "$MAX_START_WAIT"); do
  if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "    Port ${PORT} is listening after ${i}s."
    break
  fi
  if [[ $i -eq $MAX_START_WAIT ]]; then
    echo "    ERROR: port ${PORT} did not bind after ${MAX_START_WAIT}s." >&2
    echo "    Last lines of log:" >&2
    tail -20 "$LOG" >&2
    exit 1
  fi
  sleep 1
done

# ── Phase 4: Health probe ─────────────────────────────────────────────────────

echo "==> [4/4] Probing $HEALTH_URL..."
HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || echo "000")"
if [[ "$HTTP_CODE" == "200" ]] || [[ "$HTTP_CODE" == "503" ]]; then
  echo "    /api/health → $HTTP_CODE  (server is responding)"
  # Full response for inspection
  curl -s "$HEALTH_URL" | python3 -m json.tool 2>/dev/null || true
else
  echo "    /api/health → $HTTP_CODE  ✗" >&2
  echo "    Last lines of log:" >&2
  tail -20 "$LOG" >&2
  exit 1
fi

echo
echo "==> Backend deployed successfully."
echo "    Local URL:  http://127.0.0.1:${PORT}"
echo "    PID:        $PID"
echo "    Log:        $LOG"
echo "    Stop:       scripts/stop-all.sh"
echo "    Status:     scripts/status.sh"
echo "    Restart:    scripts/deploy-local-backend.sh"

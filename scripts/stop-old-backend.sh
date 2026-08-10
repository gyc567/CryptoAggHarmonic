#!/usr/bin/env bash
# scripts/stop-old-backend.sh
#
# Kill the old backend processes binding 127.0.0.1:5001.
# Handles both:
#   - The systemd-managed pyharmonics.service (www-data, /var/www/pyharmonics/)
#   - Any stray gunicorn processes holding the port
#
# Idempotent — safe to re-run even if everything is already dead.
#
# Usage:
#   scripts/stop-old-backend.sh
set -euo pipefail

PORT="${PORT:-5001}"

echo "==> Stopping old backend on 127.0.0.1:${PORT}..."

# 1. Stop systemd unit first (prevents auto-restart loop)
if systemctl is-active --quiet pyharmonics.service 2>/dev/null; then
  echo "    Stopping pyharmonics.service..."
  sudo systemctl stop pyharmonics.service
  sleep 2
else
  echo "    pyharmonics.service not active."
fi

# 2. Kill by port
PORT_PIDS="$(lsof -ti "tcp:127.0.0.1:${PORT}" 2>/dev/null || true)"
if [[ -n "$PORT_PIDS" ]]; then
  echo "    Killing by port: $PORT_PIDS"
  echo "$PORT_PIDS" | xargs kill -TERM 2>/dev/null || true
  sleep 2
  PORT_PIDS="$(lsof -ti "tcp:127.0.0.1:${PORT}" 2>/dev/null || true)"
  if [[ -n "$PORT_PIDS" ]]; then
    echo "    Force-killing: $PORT_PIDS"
    echo "$PORT_PIDS" | xargs kill -9 2>/dev/null || true
  fi
else
  echo "    No process found on port ${PORT}."
fi

# 3. Belt-and-suspenders: kill all gunicorn on 5001
for pid in $(ps aux | grep 'gunicorn.*5001' | grep -v grep | awk '{print $2}'); do
  echo "    Stopping stray gunicorn pid=$pid..."
  kill -9 "$pid" 2>/dev/null || true
done

# 4. Verify port is free
sleep 1
if lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "    WARNING: port ${PORT} still in use after kill attempts." >&2
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >&2
  exit 1
else
  echo "    Port ${PORT} is free. ✓"
fi

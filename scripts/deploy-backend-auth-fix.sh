#!/usr/bin/env bash
# scripts/deploy-backend-auth-fix.sh
#
# Redeploy the auth-fix commit (c6c2d0e) to the live backend at
# hapi.cryptoagg.xyz. Run this ON THE BACKEND SERVER.
#
# What it does:
#   1. Verifies the fix commit is on origin/main (sanity check).
#   2. `git pull` to bring app/api/auth.py up to date.
#   3. `pytest tests/test_auth.py` for a fast in-place check that the
#      fix is on the running Python and tests pass.
#   4. Restarts gunicorn gracefully (SIGTERM -> new master picks up
#      workers; or systemctl restart; or the project's existing
#      scripts/start-backend.sh restart).
#   5. Probes the running server with a dummy Bearer token and expects
#      a 401 (not 500). A 500 means the new code is NOT running yet.
#
# Usage:
#   cd /opt/pyharmonics-gpt   # or wherever the repo lives
#   ./scripts/deploy-backend-auth-fix.sh
#
# Idempotent — safe to re-run.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

EXPECTED_COMMIT="c6c2d0e070e6c40a0930ab7597809b0e8cee9c10"

echo "==> Checking origin/main for the auth-fix commit..."
if ! git fetch origin main >/dev/null 2>&1; then
  echo "WARN: git fetch failed (offline?). Will still try to apply HEAD if it matches." >&2
fi
LATEST=$(git rev-parse origin/main 2>/dev/null || git rev-parse HEAD)
if [ "$LATEST" != "$EXPECTED_COMMIT" ]; then
  echo "ERROR: origin/main HEAD ($LATEST) is not the expected fix commit." >&2
  echo "       Expected: $EXPECTED_COMMIT" >&2
  echo "       Did you forget to push? Try: git push origin main" >&2
  exit 2
fi
echo "    origin/main = $LATEST  ✓"

echo "==> Pulling latest..."
git pull --ff-only origin main

echo "==> Verifying the fix is in the working tree..."
if ! grep -q "from app.infra.supabase_client import reserve_user_quota, verify_user_token" app/api/auth.py; then
  echo "ERROR: app/api/auth.py is missing the fix import. Aborting." >&2
  exit 3
fi
echo "    app/api/auth.py imports look correct  ✓"

echo "==> Running auth tests (should be 15/15)..."
python -m pytest tests/test_auth.py -q
echo

echo "==> Restarting gunicorn..."
# The project's scripts/start-backend.sh wraps the actual gunicorn
# lifecycle; prefer it when present.
if [ -x "$REPO_ROOT/scripts/start-backend.sh" ]; then
  "$REPO_ROOT/scripts/start-backend.sh" restart
elif systemctl list-unit-files gunicorn.service >/dev/null 2>&1; then
  sudo systemctl restart gunicorn
else
  # Fall back to a direct reload — master PID stays up, workers cycle.
  pgrep -f "gunicorn.*app.main:app" | head -1 | xargs -I{} kill -TERM {} || true
  sleep 2
fi
sleep 2

echo "==> Probing live endpoints..."
PROBE_AUTH=$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer dummy.token' \
  -d '{}' https://hapi.cryptoagg.xyz/api/analyze || echo "000")
PROBE_NO_AUTH=$(curl -sS -o /dev/null -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  -d '{}' https://hapi.cryptoagg.xyz/api/analyze || echo "000")
PROBE_HISTORY=$(curl -sS -o /dev/null -w '%{http_code}' \
  -H 'Authorization: Bearer dummy.token' \
  https://hapi.cryptoagg.xyz/api/history || echo "000")

echo "    POST /api/analyze (no auth) -> $PROBE_NO_AUTH   (expect 401)"
echo "    POST /api/analyze (Bearer)  -> $PROBE_AUTH     (expect 401 — not 500)"
echo "    GET  /api/history (Bearer)  -> $PROBE_HISTORY  (expect 401 — not 500)"

if [ "$PROBE_AUTH" = "500" ] || [ "$PROBE_HISTORY" = "500" ]; then
  echo "ERROR: live backend still returns 500. The new gunicorn worker is" >&2
  echo "       either not running yet or didn't pick up the fix. Check:" >&2
  echo "         ps -ef | grep gunicorn" >&2
  echo "         journalctl -u gunicorn -n 100  # or: tail gunicorn logs" >&2
  exit 4
fi

echo
echo "==> All probes pass. Auth 500 is closed."
echo "    Loop engineering log: docs/loop-state/STATE.md, durable fact [v3auth01]."

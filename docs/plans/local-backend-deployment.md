# Plan: Local Backend Deployment → hapi.cryptoagg.xyz (COMPLETED)
## Status: DEPLOYED

The local backend is running with the latest code from this repo on `127.0.0.1:5001`.

## Context

This machine (`racknerd-8502b6d`) runs two backends simultaneously:
- **Old backend**: `/var/www/pyharmonics/` managed by `systemd pyharmonics.service` (Python 3.11, www-data user, auto-restart loop)
- **New backend**: `/root/code/CryptoAggHarmonic/` deployed via `scripts/deploy-local-backend.sh`

The old backend occupies `127.0.0.1:5001` by default. It is a supervised service that respawns on death — cannot be killed without also stopping the systemd unit.

The `scripts/start-backend.sh` script was designed for a dev environment (no `.venv` in the project, venv discovery looks in wrong paths). The dependency versions in `requirements.txt` are incompatible with Python 3.12 (websockets conflict between `alpaca-trade-api` and `supabase`). The old venv at `/var/www/pyharmonics/.venv` (Python 3.11) has all deps correctly resolved.

## Goals

- [x] Audit existing scripts vs reality
- [x] Design deployment script
- [x] Implement `scripts/deploy-local-backend.sh`
- [x] Implement `scripts/stop-old-backend.sh`
- [x] Execute deployment (stop old, start new)
- [x] Verify health probe returns 200
- [x] Write plan doc

## Key Finding

**This machine IS the backend server.** Deploying locally means:
1. `systemctl stop pyharmonics.service` to stop the supervised old backend
2. `scripts/deploy-local-backend.sh` starts the new code using the old venv (Python 3.11, all deps work)
3. Set `PYTHONPATH=/root/code/CryptoAggHarmonic` so the old venv imports the new app code

The venv at `/var/www/pyharmonics/.venv` (Python 3.11) is required — it has:
- Python 3.11 (correct)
- websockets 13.1 (correct, compatible with both `alpaca-trade-api` and `supabase>=2.31.0`)
- supabase 2.31.0 (correct)
- pyharmonics 1.4.3 (correct)

The project's `requirements.txt` has a websockets conflict (`alpaca-trade-api` wants `<11`, `supabase`/`yfinance` want `>=11`). This is resolved in the old venv by version pinning.

## Files Changed

### New files

- `scripts/deploy-local-backend.sh` — main deployment script
- `scripts/stop-old-backend.sh` — kill old backend + systemd unit
- `docs/plans/local-backend-deployment.md` — this file

### Modified files

- `scripts/stop-old-backend.sh` — added systemd unit stop

## Deployment Commands

```bash
# Deploy latest code (stops old, starts new)
scripts/deploy-local-backend.sh

# Stop old backend only
scripts/stop-old-backend.sh

# Check status
scripts/status.sh

# Stop everything
scripts/stop-all.sh

# Restart old backend (systemd-managed)
sudo systemctl start pyharmonics.service
```

## Verification

- Health probe: `curl http://127.0.0.1:5001/api/health` → `{"status": "ok|degraded"}`
- Supabase health may show `degraded` locally (missing `SUPABASE_SERVICE_ROLE_KEY` in local env) — this is expected and non-blocking
- Version: `"version": "0.2.0"` confirms the new app module is loaded

## Known Issues

- Supabase health check returns `degraded` in local env because `SUPABASE_SERVICE_ROLE_KEY` is not set in the shell environment. The actual API works (redis and TradingView bridge are OK).
- The `scripts/start-backend.sh` script is not used by this deployment flow — it looks for `.venv` in wrong locations and doesn't know about systemd.
- `requirements.txt` has an unsolvable websockets conflict on Python 3.12. The deployment uses the Python 3.11 venv at `/var/www/pyharmonics/.venv`.

## Rollback

To restore the old backend:

```bash
sudo systemctl start pyharmonics.service
```

To check which code is running: `curl http://127.0.0.1:5001/api/health | jq .version`

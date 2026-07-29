# scripts/

Local-development helpers for starting and stopping the Flask backend and
Next.js frontend without fighting `jcode`'s `run_in_background: true` 10-minute
wrapper timeout.

## Files

| Script | Purpose |
| --- | --- |
| `start-backend.sh` | Boot gunicorn detached, write pid + log under `scripts/.run/` |
| `start-frontend.sh` | Boot `next dev` detached, same pattern |
| `start-tv-bridge.sh` | Boot the TradingView Node bridge (port 5002) if `USE_TRADINGVIEW=true` |
| `stop-all.sh` | SIGTERM all three pidfiles (escalates to SIGKILL after 5s) |
| `status.sh` | Report pid + port status of the stack |

## Usage

```bash
# One-shot full stack
scripts/start-backend.sh
scripts/start-frontend.sh
scripts/status.sh

# Tail logs
tail -f scripts/.run/gunicorn.log
tail -f scripts/.run/next-dev.log

# Restart a single service
scripts/start-backend.sh restart
scripts/start-frontend.sh restart

# Stop everything
scripts/stop-all.sh
```

## Why "detached"?

`jcode`'s `bash` tool with `run_in_background: true` wraps the spawned
process in a supervisor that sends SIGKILL to its children after the task
times out (default 600s). Without detachment, the long-running dev servers
get reaped along with the wrapper, which makes a 10-minute "still running"
look like "ERR_CONNECTION_REFUSED" the next time you reload the page.

The helpers use `nohup ... &` + `disown` + closed stdin to reparent the
process to PID 1, so it survives:

- jcode task wrapper exit / timeout
- shell hangups
- terminal close

State lives under `scripts/.run/` (gitignored). If you see a stale pidfile,
either run `scripts/stop-all.sh` or `rm scripts/.run/*.pid` before restarting.

## Prerequisites

- `.venv/bin/gunicorn` exists and is executable
- `frontend/node_modules/` is installed (`npm install` inside `frontend/`)
- `.env` (project root) is configured; `DISABLE_AUTH=1` is recommended for local dev
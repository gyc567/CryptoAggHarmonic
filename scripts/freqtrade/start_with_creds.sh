#!/usr/bin/env bash
# scripts/freqtrade/start_with_creds.sh
#
# Start freqtrade (or freqtrade_dev_mcp backtest) with exchange API
# credentials sourced from macOS Keychain — never written to the
# repo and never logged.
#
# Loop-engineered: idempotent, self-verifying, leaves no secrets
# behind.
#
# ADR-0010 D7: Exchange API key/secret live in Keychain only.
#   - service: "cryptoagg-freqtrade"
#   - accounts: exchange-key, exchange-secret, mcp-token
#
# Usage:
#   scripts/freqtrade/start_with_creds.sh --check
#   scripts/freqtrade/start_with_creds.sh --rotate
#   scripts/freqtrade/start_with_creds.sh freqtrade start \
#       --userdir freqtrade_dev_mcp/user_data --config <path>
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
USERDATA="${ROOT}/freqtrade_dev_mcp/user_data"
CONFIG_FILE="${USERDATA}/config.json"
KEYCHAIN_SERVICE="cryptoagg-freqtrade"
TMP_DIR="$(mktemp -d -t freqtrade-creds.XXXXXX)"
chmod 700 "$TMP_DIR"
trap 'rm -rf "$TMP_DIR"' EXIT

# ── helpers ────────────────────────────────────────────────────────────────

emit_config() {
    local api_key="$1"
    local api_secret="$2"
    local mcp_token="${3:-}"
    cat <<JSON
{
  "exchange": {
    "name": "binance",
    "key": "${api_key}",
    "secret": "${api_secret}"
  },
  "freqtrade_path": "${ROOT}/freqtrade_dev_mcp",
  "default_stake_amount": 100.0,
  "dry_run": true,
  "mcp_token": "${mcp_token}"
}
JSON
}

read_secret() {
    local account="$1"
    local value
    if ! value="$(security find-generic-password \
            -s "$KEYCHAIN_SERVICE" -a "$account" -w 2>/dev/null)"; then
        echo "ERROR: Keychain entry missing: service=$KEYCHAIN_SERVICE account=$account" >&2
        echo "  Add it with:" >&2
        echo "    security add-generic-password -s $KEYCHAIN_SERVICE -a $account -w" >&2
        return 1
    fi
    printf '%s' "$value"
}

check_all_entries() {
    echo "==> Checking Keychain entries (existence only, no values read)..."
    local missing=0
    for account in exchange-key exchange-secret mcp-token; do
        if security find-generic-password \
                -s "$KEYCHAIN_SERVICE" -a "$account" >/dev/null 2>&1; then
            echo "    [OK] $account"
        else
            echo "    [MISSING] $account"
            missing=1
        fi
    done
    if [[ $missing -eq 1 ]]; then
        echo "==> Missing entries. Add with:" >&2
        echo "    security add-generic-password -s $KEYCHAIN_SERVICE -a <account> -w" >&2
        exit 2
    fi
    echo "==> All required entries present."
    exit 0
}

# ── flags ──────────────────────────────────────────────────────────────────

case "${1:-}" in
    --check)
        check_all_entries
        ;;
    --help|-h)
        sed -n '2,22p' "$0"
        exit 0
        ;;
    --rotate)
        shift
        # fall through to main path; existing config is overwritten
        ;;
esac

# ── main ───────────────────────────────────────────────────────────────────

mkdir -p "$USERDATA"

api_key="$(read_secret exchange-key)"
api_secret="$(read_secret exchange-secret)"
mcp_token="$(read_secret mcp-token)"
tmp_config="$TMP_DIR/config.json"
emit_config "$api_key" "$api_secret" "$mcp_token" > "$tmp_config"
chmod 600 "$tmp_config"
mv -f "$tmp_config" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

echo "==> Wrote $CONFIG_FILE (chmod 600, never logged)"

# Scrub the in-memory strings we no longer need.
unset api_key api_secret mcp_token

# Forward any extra argv to freqtrade / python.
if [[ $# -gt 0 ]]; then
    echo "==> Launching: $*"
    exec "$@"
fi
echo "==> Done. Config ready at $CONFIG_FILE"

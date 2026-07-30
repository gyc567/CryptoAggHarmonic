#!/usr/bin/env bash
# Watchlist smoke test (curl).
#
# Exercises every CRUD endpoint against a running backend. Requires
# DISABLE_AUTH=1 so the local-dev-user is used.
#
# Usage:
#   ./scripts/smoke_watchlist.sh [BASE_URL]
#
# Default base URL is http://127.0.0.1:5001.
#
# Exits non-zero on the first failure.

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:5001}"

# Tiny helpers ----------------------------------------------------------

req() {
    # req METHOD PATH [BODY]
    local method="$1"; shift
    local path="$1"; shift
    local body="${1:-}"
    if [[ -z "$body" ]]; then
        curl -sS -X "$method" "$BASE_URL$path" \
            -H "Content-Type: application/json"
    else
        curl -sS -X "$method" "$BASE_URL$path" \
            -H "Content-Type: application/json" \
            -d "$body"
    fi
}

assert_status() {
    local want="$1"; shift
    local got="$1"; shift
    local label="$1"
    if [[ "$got" != "$want" ]]; then
        echo "FAIL [$label]: expected HTTP $want, got $got"
        echo "--- body ---"
        cat /tmp/smoke_body.txt || true
        exit 1
    fi
    echo "  ok [$label] -> $got"
}

run() {
    # run METHOD PATH [BODY] EXPECTED_STATUS LABEL
    local method="$1"; shift
    local path="$1"; shift
    local body="${1:-}"; shift || true
    local want="$1"; shift
    local label="$1"
    local resp
    resp=$(req "$method" "$path" "$body")
    local code
    code=$(req "$method" "$path" "$body" -o /dev/null -w "%{http_code}")
    echo "$resp" > /tmp/smoke_body.txt
    assert_status "$want" "$code" "$label"
    echo "$resp" | head -c 200
    echo
}

# Markets search ---------------------------------------------------------

echo "=== markets/futures/symbols ==="
run GET "/api/markets/futures/symbols?q=MU" "" 200 "MU search returns 200"
run GET "/api/markets/futures/symbols" "" 200 "all symbols returns 200"

# Admin refresh ----------------------------------------------------------

echo "=== admin refresh ==="
run POST "/api/admin/markets/futures/refresh" '{"force":true}' 200 "admin refresh"

# Watchlist CRUD ---------------------------------------------------------

echo "=== watchlist CRUD ==="

# Start clean.
run GET "/api/watchlist" "" 200 "list (initial)"

# Add MUUSDT
ADD_BODY='{"symbol":"MUUSDT","note":"chip play"}'
ADD_RESP=$(req POST "/api/watchlist" "$ADD_BODY")
echo "$ADD_RESP" > /tmp/smoke_add.json
ADD_CODE=$(req POST "/api/watchlist" "$ADD_BODY" -o /dev/null -w "%{http_code}")
assert_status 200 "$ADD_CODE" "add MUUSDT"

# Extract id with python (avoid jq dep).
ITEM_ID=$(python3 -c "import json,sys; print(json.load(open('/tmp/smoke_add.json'))['data']['item']['id'])")
echo "  item id: $ITEM_ID"

# Duplicate → 409
run POST "/api/watchlist" "$ADD_BODY" 409 "duplicate add returns 409"

# Unknown symbol → 422
run POST "/api/watchlist" '{"symbol":"FOOUSDT"}' 422 "unknown symbol returns 422"

# PATCH note
run PATCH "/api/watchlist/$ITEM_ID" '{"note":"updated"}' 200 "patch note"

# DELETE
run DELETE "/api/watchlist/$ITEM_ID" "" 200 "delete item"
run DELETE "/api/watchlist/$ITEM_ID" "" 404 "delete missing returns 404"

echo
echo "ALL SMOKE CHECKS PASSED"
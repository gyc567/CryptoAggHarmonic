#!/usr/bin/env bash
# scripts/okx/install.sh
#
# Install + verify the OKX Agent Trade Kit MCP server.
#
# Loop-engineered: idempotent, non-destructive `verify` subcommand
# for CI, explicit `install` subcommand for one-time setup.
#
# ADR-0011 D1: npm global install + scripts/okx/VERSION pin.
# ADR-0011 D4: lock 1.0.4 long-term; upgrade requires a new ADR.
#
# Usage:
#   scripts/okx/install.sh install       # npm i -g @okx_ai/okx-trade-mcp@<VERSION>
#   scripts/okx/install.sh verify        # non-destructive: PATH check + version match (CI-safe)
#   scripts/okx/install.sh version       # print expected + actual versions
#   scripts/okx/install.sh --mock        # install a fake okx-trade-mcp shim under ./scripts/okx/.bin/
#                                         # (Phase 1A mock walkthrough only — DOES NOT touch global npm)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION_FILE="${ROOT}/scripts/okx/VERSION"
LOCAL_BIN="${ROOT}/scripts/okx/.bin"
PATH_LINE="export PATH=\"${LOCAL_BIN}:\${PATH}\""

# ── helpers ────────────────────────────────────────────────────────────────

read_version() {
    if [[ ! -f "$VERSION_FILE" ]]; then
        echo "ERROR: $VERSION_FILE missing" >&2
        exit 1
    fi
    # First non-empty, non-comment line
    awk 'NF && $1 !~ /^#/ {print; exit}' "$VERSION_FILE"
}

require_node() {
    if ! command -v node >/dev/null 2>&1; then
        echo "ERROR: node not found in PATH (OKX requires >= 18)" >&2
        return 1
    fi
    local major
    major="$(node -e 'console.log(process.versions.node.split(".")[0])')"
    if [[ "$major" -lt 18 ]]; then
        echo "ERROR: node $major.x found, OKX requires >= 18" >&2
        return 1
    fi
}

install_mock_shim() {
    mkdir -p "$LOCAL_BIN"
    cat > "$LOCAL_BIN/okx-trade-mcp" <<'SHIM'
#!/usr/bin/env bash
# Mock okx-trade-mcp shim — Phase 1A walkthrough only.
# Emulates the real @okx_ai/okx-trade-mcp --version / --help protocol
# and prints a fake capability snapshot for any other arg.
# NEVER install this on a real system: it returns no real OKX data.
case "${1:-}" in
--version|-V)
echo "1.0.4"
;;
--help|-h)
echo "okx-trade-mcp MOCK 1.0.4 (Phase 1A walkthrough only — no real OKX connection)"
;;
*)
echo "okx-trade-mcp MOCK 1.0.4  (no real OKX connection)"
echo "args: $*"
cat <<'JSON'
{"ok":true,"modules":["market","account","spot"],"readOnly":true,"demo":true}
JSON
;;
esac
SHIM
    chmod +x "$LOCAL_BIN/okx-trade-mcp"
    echo "==> Mock shim installed at $LOCAL_BIN/okx-trade-mcp"
    echo "    To use it in this shell:"
    echo "      $PATH_LINE"
}

# ── subcommands ────────────────────────────────────────────────────────────

cmd_install() {
    require_node
    local expected
    expected="$(read_version)"
    echo "==> Installing @okx_ai/okx-trade-mcp@$expected (global)..."
    npm i -g "@okx_ai/okx-trade-mcp@$expected"
    echo "==> Done. Run 'scripts/okx/install.sh verify' to confirm."
}

cmd_verify() {
    local expected
    expected="$(read_version)"
    local actual
    if ! actual="$(okx-trade-mcp --version 2>/dev/null)"; then
        echo "FAIL: okx-trade-mcp not found in PATH" >&2
        echo "  Run: scripts/okx/install.sh install" >&2
        return 1
    fi
    if [[ "$actual" != "$expected" ]]; then
        echo "FAIL: version mismatch — expected $expected, got $actual" >&2
        return 1
    fi
    echo "OK: okx-trade-mcp $actual matches $VERSION_FILE"
}

cmd_version() {
    local expected
    expected="$(read_version)"
    local actual="(not installed)"
    if command -v okx-trade-mcp >/dev/null 2>&1; then
        actual="$(okx-trade-mcp --version 2>/dev/null || echo '(unreadable)')"
    fi
    echo "expected (scripts/okx/VERSION): $expected"
    echo "actual   (okx-trade-mcp --version): $actual"
}

# ── flags ──────────────────────────────────────────────────────────────────

case "${1:-}" in
    --mock)
        install_mock_shim
        exit 0
        ;;
    install)
        cmd_install
        ;;
    verify)
        cmd_verify
        ;;
    version)
        cmd_version
        ;;
    --help|-h|"")
        sed -n '2,28p' "$0"
        exit 0
        ;;
    *)
        echo "Unknown subcommand: $1" >&2
        echo "Run '$0 --help' for usage." >&2
        exit 2
        ;;
esac

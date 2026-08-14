"""
FreqTrade strategy files — single source of truth.

Per ``docs/plans/freqtrade-strategy-bidirectional-compat.md`` Phase A,
all FreqTrade IStrategy files live in this directory. The
``freqtrade_dev_mcp/user_data/strategies/`` clone path is a symlink
pointing here, so any code that imports strategies from either path
reads the same file.

Phase B will add ``app/services/strategy_runner.py`` to invoke these
strategies directly from the API/bench/loop paths. Phase C will flip
the default API engine to freqtrade and delete the legacy
``app/domain/strategy_core.py`` mirror.
"""

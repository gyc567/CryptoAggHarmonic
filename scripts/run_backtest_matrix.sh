#!/bin/bash
# Backtest matrix: BTCUSDT/ETHUSDT/SOLUSDT × 1H/4H/1D × 30 months.
# Usage: ./scripts/run_backtest_matrix.sh <output_dir> [--entry-mode {market,prz}]
set -e
OUT_DIR="${1:?usage: $0 OUT_DIR [args]}"
shift
mkdir -p "$OUT_DIR"

SYMBOLS=(BTCUSDT ETHUSDT SOLUSDT)
INTERVALS=(1h 4h 1d)
DAYS=900   # ~30 months

# Map interval → window/horizon/step defaults.  Window = max(pattern length, 30).
# Step = window/3 for sub-hourly (more samples), window/2 for 4h+, full window for 1d.
declare -A WIN HOR STEP
WIN[1h]=72;   HOR[1h]=72;   STEP[1h]=24
WIN[4h]=60;   HOR[4h]=60;   STEP[4h]=20
WIN[1d]=45;   HOR[1d]=45;   STEP[1d]=15

for s in "${SYMBOLS[@]}"; do
  for i in "${INTERVALS[@]}"; do
    slug="${s}_${i}_${DAYS}d"
    echo "==> $slug"
    PYTHONPATH=. .venv/bin/python scripts/backtest_harmonic.py \
      --symbol "$s" --interval "$i" --days "$DAYS" \
      --window "${WIN[$i]}" --step "${STEP[$i]}" --horizon "${HOR[$i]}" \
      --silent "$@" --out-dir "$OUT_DIR" \
      2>&1 | tail -1
  done
done
echo "DONE -> $OUT_DIR"
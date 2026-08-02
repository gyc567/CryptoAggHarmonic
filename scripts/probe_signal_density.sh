#!/bin/bash
# Density probe across 9 cells; tweak step to gauge signal count.
set -e
OUT=/tmp/bt_probe
mkdir -p $OUT
SYMBOLS=(BTCUSDT ETHUSDT SOLUSDT)
INTERVALS=(1h 4h 1d)

# Return WIN/HOR/STEP/DAYS for an interval via case (bash 3.2-safe).
case_pars () {
    case "$1" in
        1h) echo 72 72 12 90 ;;
        4h) echo 60 60 10 180 ;;
        1d) echo 45 45  5 365 ;;
    esac
}

for s in "${SYMBOLS[@]}"; do
  for i in "${INTERVALS[@]}"; do
    read WIN HOR STEP DAYS <<< "$(case_pars "$i")"
    echo -n "==> ${s} ${i} (${DAYS}d): "
    PYTHONPATH=. .venv/bin/python scripts/backtest_harmonic.py \
      --symbol "$s" --interval "$i" --days "$DAYS" \
      --window "$WIN" --step "$STEP" --horizon "$HOR" \
      --silent --entry-mode prz --out-dir "$OUT" \
      >/dev/null 2>&1
    .venv/bin/python -c "
import json
d = json.load(open('${OUT}/${s}_${i}_${DAYS}d.json'))
sm = d['summary']
print(f\"signals={sm['total_signals']:3d} wins={sm['wins']:3d} losses={sm['losses']:3d} skips={sm['skipped_signals']:3d} win_rate={sm['win_rate']:.0%} avg_r={sm['avg_r']:+.2f}\")
"
  done
done
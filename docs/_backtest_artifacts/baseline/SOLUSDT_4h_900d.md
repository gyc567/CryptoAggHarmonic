# Walk-forward backtest — SOLUSDT 4h (900d)

## Config

- symbol: `SOLUSDT`
- interval: `4h`
- window: `60` bars
- step: `20` bar(s)
- horizon: `60` bars
- market: `binance`

## Summary

- total signals: **10**
- decisions (entry filled): 3
- skipped (entry never touched): 7
- wins / losses / scratches: 1 / 2 / 0
- win rate (of decided): **33.3%**
- avg R multiple: **-0.15**
- total R: **-1.54**
- profit factor: **0.23**

## By grade

- C(参考): count=10 wins=1 losses=2 win_rate=33.3% R=-1.54

## By family

- ABC: count=9 wins=1 losses=2 win_rate=33.3% R=-1.54
- ABCD: count=1 wins=0 losses=0 win_rate=0.0% R=+0.00

## Signals (first 20)

| time | dir | grade | pattern | entry | stop | tp1 | rr1 | result | r |
|---|---|---|---|---|---|---|---|---|---|
| 2024-06-08T04:00:00+00:00 | long | C(参考) | 1.618 | 163.6 | 151.5 | 156.1 | 1.4272 | skipped | +0.00 |
| 2024-06-18T04:00:00+00:00 | long | C(参考) | ABCD-50 | 136.7 | 125.8 | 141.3 | 6.1504 | skipped | +0.00 |
| 2024-07-31T12:00:00+00:00 | short | C(参考) | 1.414 | 180.1 | 196.2 | 190.6 | 0.988 | skipped | +0.00 |
| 2024-11-18T12:00:00+00:00 | short | C(参考) | 2 | 243.3 | 252 | 239.6 | 1.8682 | loss | -1.00 |
| 2024-11-21T20:00:00+00:00 | short | C(参考) | 1.618 | 256.4 | 263.5 | 255.5 | 0.8027 | loss | -1.00 |
| 2025-02-19T20:00:00+00:00 | long | C(参考) | 2.618 | 168.9 | 158.5 | 171.4 | 3.4548 | skipped | +0.00 |
| 2025-06-16T12:00:00+00:00 | long | C(参考) | 1.272 | 156.6 | 138.6 | 142.7 | 1.0473 | skipped | +0.00 |
| 2025-08-28T20:00:00+00:00 | short | C(参考) | 1.13 | 214.4 | 219.6 | 215.6 | 0.1782 | win | +0.46 |
| 2026-04-02T12:00:00+00:00 | long | C(参考) | 1.272 | 79.03 | 75.82 | 77.56 | 0.573 | skipped | +0.00 |
| 2026-06-01T12:00:00+00:00 | long | C(参考) | 1.414 | 79.6 | 78.7 | 80.08 | 0.8648 | skipped | +0.00 |

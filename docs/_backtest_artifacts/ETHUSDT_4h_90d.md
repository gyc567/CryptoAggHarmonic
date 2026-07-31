# Walk-forward backtest — ETHUSDT 4h (90d)

## Config

- symbol: `ETHUSDT`
- interval: `4h`
- window: `200` bars
- step: `12` bar(s)
- horizon: `30` bars
- market: `binance`

## Summary

- total signals: **11**
- decisions (entry filled): 3
- skipped (entry never touched): 8
- wins / losses / scratches: 2 / 1 / 0
- win rate (of decided): **66.7%**
- avg R multiple: **0.14**
- total R: **+1.57**
- profit factor: **2.57**

## By grade

- B: count=3 wins=1 losses=1 win_rate=50.0% R=-0.49
- C(参考): count=8 wins=1 losses=0 win_rate=100.0% R=+2.06

## By family

- ABC: count=11 wins=2 losses=1 win_rate=66.7% R=+1.57

## Signals (first 20)

| time | dir | grade | pattern | entry | stop | tp1 | rr1 | result | r |
|---|---|---|---|---|---|---|---|---|---|
| 2026-06-15T07:59:59+00:00 | short | C(参考) | 2 | 1717 | 1742 | 1718 | 0.7185 | skipped | +0.00 |
| 2026-06-19T07:59:59+00:00 | short | C(参考) | 0.5 | 1696 | 2214 | 1716 | 0.3445 | skipped | +0.00 |
| 2026-06-29T07:59:59+00:00 | short | C(参考) | 0.618 | 1580 | 1860 | 1753 | 0.2482 | skipped | +0.00 |
| 2026-07-01T07:59:59+00:00 | short | C(参考) | 0.618 | 1578 | 1864 | 1753 | 0.237 | skipped | +0.00 |
| 2026-07-13T07:59:59+00:00 | short | C(参考) | 1.272 | 1788 | 1858 | 1821 | 1.1166 | skipped | +0.00 |
| 2026-07-15T07:59:59+00:00 | short | B | 1.414 | 1870 | 1910 | 1852 | 1.9578 | loss | -1.00 |
| 2026-07-17T07:59:59+00:00 | short | C(参考) | 1.272 | 1829 | 1961 | 1909 | 1.57 | skipped | +0.00 |
| 2026-07-19T07:59:59+00:00 | short | C(参考) | 1.618 | 1870 | 1956 | 1883 | 3.8228 | skipped | +0.00 |
| 2026-07-21T07:59:59+00:00 | short | C(参考) | 1.618 | 1934 | 1959 | 1883 | 3.1688 | win | +2.06 |
| 2026-07-23T07:59:59+00:00 | short | B | 1.618 | 1916 | 1968 | 1889 | 3.4741 | win | +0.51 |
| 2026-07-25T07:59:59+00:00 | short | B | 1.618 | 1856 | 1967 | 1889 | 3.7331 | skipped | +0.00 |

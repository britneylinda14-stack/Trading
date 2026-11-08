# ATM pullback strategy: automating the 2023 manual journal

Source: Notion "Journal de Backtest ATM" (Jul–Aug 2023, 108 manual backtests on 30m/1h TradingView
charts). This document compares that journal with a mechanical version of the same checklist
(`atm_pullback`, `src/trading_agent/strategies/pullback.py`).

## The rules as coded

| Journal checklist | `atm_pullback` |
|---|---|
| Order flow / structure H or B | Last two confirmed swing highs and lows both rising (long) or falling (short) (`structure=True`) |
| MA50 and MA200 aligned | Close and MA50 both above MA200 (long), mirrored for shorts |
| Fibonacci pullback 0.382–0.618 into a zone | Pullback from the last swing extreme retraces 0.382–`fib_max` of the impulse; impulse must be at least `min_impulse_atr` ATRs |
| RSI divergence (regular or hidden) | Hidden RSI(14) divergence between the pullback low and the previous swing low (`divergence=True`) |
| Trendline break trigger | Close above the high of the last `trigger_bars` bars, within `max_wait` bars of the pullback extreme |
| SL beyond zone / swing | Stop `stop_buffer_atr` ATR beyond the pullback extreme; skipped if wider than `max_stop_atr` ATR |
| "BE + CP" | At +1R close half and move the stop to entry |
| TP1 / final target | Final target at `tp_r` R (default 2.5R, about the journal's 2.6R average winner) |

Not coded: hand-drawn supply/demand zones, volume profile, MACD, candle patterns and the
discretionary "is this a clean setup" judgment.

Engine support: a strategy can now return per-signal `take_profit_r`, `breakeven_r` and `partial`
columns. When price reaches `breakeven_r` the engine closes `partial` of the units there and moves
the stop to entry. If the same bar also trades back through entry, it is scored as a breakeven exit
(the conservative order).

## Data and costs

- HistData.com 1-minute BID bars, 2012-01 to 2026-10, resampled to 1h and 30m (`--source histdata`).
- Spreads charged on entry and exit: EUR/USD 1.4 pips, gold $0.40, silver $0.03. No commissions,
  no slippage beyond the spread.
- 1% risk per trade, 5% max open risk, $10k start.

## Results

Default settings, each market traded alone, 2012–2026:

| | Trades | TP | BE | SL | Avg R | Return | Max DD |
|---|---|---|---|---|---|---|---|
| EUR/USD 1h | 160 | 22 | 52 | 84 | -0.12 | -18% | -20% |
| Gold 1h | 144 | 22 | 41 | 78 | -0.13 | -17% | -21% |
| Silver 1h | 144 | 20 | 48 | 72 | -0.04 | -7% | -12% |
| EUR/USD 30m | 238 | 27 | 57 | 145 | -0.25 | -45% | -46% |
| Gold 30m | 243 | 44 | 68 | 126 | -0.04 | -10% | -14% |
| Silver 30m | 252 | 31 | 62 | 149 | -0.15 | -32% | -37% |

Without any spread, 1h average R improves to EUR/USD -0.09, gold -0.08, silver +0.10, so costs are
not the main problem.

Parameter sweep on the 3-market portfolio (`swing`, `fib_max`, `divergence`, `tp_r`; 16 sets),
tuned on 2012–2019 and tested on 2020–2026:

| | Positive Sharpe in-sample | Positive Sharpe out-of-sample | Median out-of-sample Sharpe |
|---|---|---|---|
| 1h | 0/16 | 0/16 | -0.40 |
| 30m | 0/16 | 0/16 | -0.90 |

## Journal vs automated

| | Journal (manual, 2023) | Automated (1h, 2012–2026) |
|---|---|---|
| Trades | 108 in ~3 weeks of logging | 448 over 15 years |
| TP / BE / SL | 48% / 28% / 24% | 14% / 31% / 52% |
| Avg R per trade | about +1.0 | -0.10 |

The breakeven share matches; the big gap is that the mechanical version gets stopped out about
twice as often and reaches the target about a third as often. Two explanations, not separable with
this data:

1. The discretionary filters that were not coded (zones, clean trendlines, overall chart quality)
   carry the edge.
2. Manual backtests on past charts select setups with hindsight, which inflates TP rates.

Like the journal, the Tokyo session is the weakest (avg R -0.16 vs London -0.09, New York -0.03 on 1h).

## Conclusion

The mechanical approximation has no edge on EUR/USD, gold or silver in any year range or setting
tested. It should not be paper traded as is. The next useful test is forward evidence for the
discretionary version: log setups live (screenshots taken before the outcome is known) for a few
months at 0.5–1% risk on a demo account, then compare with this baseline.

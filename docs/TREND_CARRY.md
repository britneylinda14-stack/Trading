# Trend-following and FX carry research

Two strategy families with the longest published track records, tested with the same
tune-then-untouched-test method as `docs/RESEARCH.md`. Historical data only; nothing trades.

## Setup

- **Data:** Yahoo daily bars from 2005-01-01 to Nov 2026. Futures use Yahoo's continuous
  front-month series (`ES=F`, `ZN=F`, ...), which are **not back-adjusted**: roll gaps show up
  as price moves. Real trading needs back-adjusted data (e.g. Databento/Norgate) or roll logic.
- **Split:** parameters tuned on 2005–2015, tested untouched on 2016–2026.
- **Costs:** futures pay 2 ticks per round trip (spread + commission proxy), no financing.
  FX pays the existing spreads plus a 1.5% financing markup, and with `--carry` earns or pays
  the central-bank rate differential (BIS policy rates, bundled in
  `calendar_data/policy_rates.csv`, refreshed by `scripts/fetch_policy_rates.py`).
- **Account:** $1M notional so 1-unit rounding doesn't skip markets. A US retail account would
  need micro futures and probably $100k+ to hold 23 markets at these risk levels.

## Strategies

- `tsmom` (time-series momentum, Moskowitz–Ooi–Pedersen 2012): hold the sign of the past
  `lookback`-bar return, re-evaluated on month-end bars, sized from an ATR stop of `atr_mult`.
  23 futures: equity indices, rates, metals, energy, grains, softs, livestock (`-i futures`).
- `fx_carry`: long the higher-yielding currency of a pair when the differential is at least
  `min_carry` and price is above its `trend`-bar average; short in the mirror case.
  7 USD pairs (`-i fx --carry`).

## Results

`tsmom`, 0.25% risk per market, 8% max open risk (`--risk 0.0025 --max-open-risk 0.08`):

| Setting | In-sample Sharpe | Out-of-sample Sharpe | OOS CAGR | OOS max DD |
|---|---|---|---|---|
| lookback 252, ATR x3 (best in-sample) | 0.53 | 0.16 | 0.8% | -16.7% |
| lookback 126, ATR x5 | 0.37 | 0.18 | 0.8% | -14.6% |
| lookback 63, ATR x5 | 0.44 | -0.02 | -0.2% | -15.4% |

Positive Sharpe: 6/6 in-sample, 5/6 out-of-sample. Sensitivity check with a wide 10-ATR stop
(closer to the literature's no-stop version, `--risk 0.00625 --max-open-risk 0.2`): 3/3
positive in both periods, out-of-sample Sharpe 0.12–0.27 (lookback 252: 1.6% CAGR, -17% DD).

`fx_carry`, 0.5% risk per pair: positive Sharpe 4/12 in-sample, **0/12 out-of-sample**
(median OOS Sharpe -0.24). Full period 2005–2026 with defaults: -6.8%, Sharpe -0.15.

## Verdict

- **Trend-following is the only thing tested so far that holds up out of sample, but the edge
  is small.** It stays positive on untouched data across nearly every setting, which is what a
  real (if weak) effect looks like. But an OOS Sharpe of 0.15–0.27 over ~11 years is not
  statistically distinguishable from zero, and it weakened from 0.4–0.6 in-sample. It lost
  money in 2008 and 2022 (default settings, full-period run), the years real managed-futures funds made the most, which points to
  the data (roll gaps, front-month only) or the simplified rules.
- **FX carry with a trend filter did not work** on 2005–2026 USD pairs. Policy-rate
  differentials were small for most of 2009–2021, and the trend filter cut the trades that did
  earn carry.

Next step if pursued: rerun `tsmom` on properly back-adjusted futures data before any paper
trading. Sharpe above ~0.4 out of sample would justify a demo account.

## Reproduce

```
trading-agent research -i futures -s tsmom --start 2005-01-01 --split 2016-01-01 \
  --equity 1000000 --risk 0.0025 --max-open-risk 0.08
trading-agent research -i fx -s fx_carry --carry --start 2005-01-01 --split 2016-01-01 \
  --equity 1000000 --risk 0.005 --max-open-risk 0.05
```

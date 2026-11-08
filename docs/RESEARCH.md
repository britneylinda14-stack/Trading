# Strategy research: first pass (2026-11)

**Setup:**
- Portfolio of all 9 instruments: 6 USD forex pairs, plus gold, silver and crude as futures proxies.
- Shared $10k account at 0.5% risk per trade, with 5% maximum open risk.
- The drawdown kill switch was raised to 50% so it doesn't cut sweeps short.
- Costs: spreads and financing.
- Data: Yahoo Finance.

Each parameter set was **tuned on 2010–2019 (in-sample) and then run untouched on
2020-01 → 2026-10 (out-of-sample)**. The hourly session breakout only has about 2 years of Yahoo
data, so its split is 2024-11 → 2025-10 / 2025-11 → 2026-11.
Yahoo only serves the most recent ~730 days of hourly bars, so these numbers shift as that window moves forward.

Reproduce: `trading-agent research -i all -s <strategy> --risk 0.005 --max-drawdown 0.5`

| Strategy | Sets | Positive Sharpe in-sample | Positive Sharpe out-of-sample | Best in-sample set → out-of-sample Sharpe | Median out-of-sample Sharpe |
|---|---|---|---|---|---|
| `donchian` (daily) | 10 | 9 | **0** | 0.34 → -0.20 | -0.31 |
| `ema_cross` (daily) | 24 | 1 | 17 | 0.00 → 0.22 | 0.10 |
| `mean_reversion` (daily) | 27 | 3 | 3 | 0.15 → -0.25 | -0.44 |
| `session_breakout` (1h) | 18 | 2 | 3 | 0.37 → -0.01 | -1.03 |

**News filter** (portfolio `ema_cross` 50/200, daily, 2010–2026):

| Variant | Return | Max drawdown | Sharpe |
|---|---|---|---|
| No filter | -1.1% | -34.0% | 0.02 |
| `--news-filter` (no entries on event days) | -0.9% | -33.9% | 0.02 |
| `--news-filter --flatten-on-events` | -7.9% | -10.9% | -0.49 |

## Takeaways

1. **None of these simple strategies has a robust edge.**
   - Donchian and the session breakout looked fine in-sample and failed out-of-sample. That's
     the classic overfitting signature.
   - EMA-cross went the other way: it was flat in 2010–2019 and mildly positive in 2020–2026,
     helped by the post-2020 rate and commodity trends. A Sharpe of about 0.1–0.2 isn't worth
     trading after real-world friction.
2. **Mean reversion on daily bars loses money.** Fading moves in FX and commodities mostly
   meant stepping in front of trends.
3. **The hourly session breakout is dominated by costs.** The spread is a large fraction
   of the typical Asian-session range.
4. **The news filter works mechanically, but on daily bars it isn't the right tool.**
   - Blocking entries only delays them by a day.
   - Flattening on every event day cuts drawdown a lot but also cuts every trend short.
   - The filter is meant for intraday strategies.

## Caveats

- Yahoo's forex data has no real spread or volume. Commodities use continuous futures with roll
  gaps, and hourly history is short.
- The spreads and financing in `instruments.py` are flat estimates.
- One train/test split is a first pass. A walk-forward with several windows would be stronger.

## Ideas worth testing next

- **FX carry with a trend filter.** Hold high-yield vs. low-yield currencies, but only when
  the trend agrees. This is the best-documented long-run FX return source.
- **Volatility-targeted, diversified time-series momentum** on a larger futures universe
  (indices, bonds, energies, metals, ags). Trend-following edges rely on breadth, and 9
  instruments is thin.
- **Better data:** OANDA candles with real bid/ask, once the practice token is available.

# AI Trading Agent: forex & commodities

A Python backtester and the foundations of a trading agent for **forex and commodities**,
built for a **US-based** account (CFTC/NFA rules). It runs without broker access today. An OANDA
paper-trading adapter comes next.

> **Disclaimer:** this is research software, not financial advice. Leveraged FX and
> commodities can lose more than you expect. Backtest, then paper trade, before any real money.

## What it does

- **Data**
  - Free historical bars from Yahoo Finance (daily for decades; hourly for about the last 2 years).
  - Your own CSVs, including **MetaTrader 5 bar exports** (`--mt5-csv`).
- **Engine** (bar by bar, no lookahead)
  - A signal on bar *i*'s close is filled at bar *i+1*'s open.
  - Fills pay the spread.
  - Overnight financing is charged.
  - Intrabar stop-loss and take-profit. A gap through the stop fills at the open.
- **Risk guards**, enforced in code rather than left to the strategy:
  - Fixed **risk per trade** (default 1% of equity, spread included), sized from the stop distance.
  - A **stop-loss on every trade**. No re-entry in the same direction after a stop until the
    signal resets.
  - **Leverage cap** at the US retail limit: 50:1 on major FX; tighter on commodities.
  - **One net position per instrument**, so no hedging and US FIFO rules are respected.
  - **Max daily loss** (default 3%): flatten and halt for the rest of the day.
  - **Max drawdown kill switch** (default 25%): flatten and stop trading for good.
- **Strategies** (pluggable)
  - `ema_cross`: 50/200 EMA trend following with a 3×ATR stop.
  - `donchian`: turtle-style 55/20 breakout with a 2×ATR stop.
- **Reports**
  - Metrics: return, CAGR, max drawdown, Sharpe, win rate, profit factor, average R, costs.
  - `equity.png`, `trades.csv`, `equity.csv` and `summary.json` in `reports/<instrument>_<strategy>/`.

## Quickstart

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -U pip setuptools && pip install -e ".[dev]"

trading-agent instruments
trading-agent backtest -i EUR_USD GBP_USD USD_JPY XAU_USD -s donchian --start 2010-01-01
trading-agent backtest -i EUR_USD -s ema_cross -p fast=20 -p slow=100 --risk 0.005
trading-agent backtest -i EUR_USD --mt5-csv ~/Downloads/EURUSD_H1.csv
pytest
```

## Instruments

| Name | Kind | Data source | Max leverage |
|---|---|---|---|
| EUR_USD, GBP_USD, AUD_USD, USD_JPY, USD_CHF, USD_CAD | spot FX | Yahoo `EURUSD=X`, ... | 50:1 |
| XAU_USD (gold), XAG_USD (silver), WTICO_USD (crude) | futures proxy | Yahoo `GC=F`, `SI=F`, `CL=F` | 20:1 / 10:1 / 10:1 |

Spreads and financing rates in `src/trading_agent/instruments.py` are rough estimates; tune
them to your broker. In the US, commodities are traded as futures (e.g. via Interactive
Brokers), not CFDs. The Yahoo continuous-futures series also contain roll gaps.

## Adding a strategy

Subclass `Strategy` and return a `direction` (+1/0/-1) and `stop_distance` per bar, using only
data up to that bar. Then register it in `strategies/__init__.py`.

```python
class MyStrategy(Strategy):
    name = "my_strategy"

    def generate(self, bars):
        ...
        return pd.DataFrame({"direction": d, "stop_distance": s}, index=bars.index)
```

## Roadmap

1. OANDA v20 adapter: historical candles and paper trading on a practice account.
2. Economic-calendar filter (pause around NFP, CPI, FOMC).
3. LLM "analyst" strategy that weighs technical signals and news.
4. Multi-instrument portfolio with a correlation-aware risk budget.
5. Deployment as a 24/5 service with alerts.

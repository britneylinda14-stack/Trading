from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .engine import BacktestResult


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def compute_metrics(result: BacktestResult) -> dict[str, float]:
    eq = result.equity
    trades = result.trades
    start, end = eq.iloc[0], eq.iloc[-1]
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)

    daily = eq.resample("D").last().dropna()
    rets = daily.pct_change().dropna()
    rets = rets[daily.index[1:].dayofweek < 5] if len(rets) else rets
    sharpe = float(rets.mean() / rets.std() * math.sqrt(252)) if rets.std() > 0 else 0.0

    pnls = np.array([t.pnl for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() < 0 else float("inf")

    bars_in_market = sum(
        ((eq.index >= t.entry_time) & (eq.index <= t.exit_time)).sum() for t in trades
    )

    return {
        "start_equity": float(start),
        "end_equity": float(end),
        "total_return_pct": float((end / start - 1) * 100),
        "cagr_pct": float(((end / start) ** (1 / years) - 1) * 100) if end > 0 else -100.0,
        "max_drawdown_pct": float(drawdown(eq).min() * 100),
        "sharpe": sharpe,
        "trades": len(trades),
        "win_rate_pct": float(len(wins) / len(trades) * 100) if trades else 0.0,
        "profit_factor": float(profit_factor) if trades else 0.0,
        "avg_r": float(np.mean([t.r_multiple for t in trades])) if trades else 0.0,
        "exposure_pct": float(bars_in_market / len(eq) * 100),
        "spread_costs": float(sum(t.spread_cost for t in trades)),
        "financing_costs": float(sum(t.financing for t in trades)),
        "years": float(years),
        "skipped_signals": result.skipped_signals,
        "blackout_skips": result.blackout_skips,
    }


def per_instrument(result: BacktestResult) -> pd.DataFrame:
    """Trade count, P&L and win rate per instrument."""
    df = result.trades_frame()
    if df.empty:
        return pd.DataFrame(columns=["trades", "pnl", "win_rate_pct", "avg_r"])
    g = df.groupby("instrument")
    return pd.DataFrame(
        {
            "trades": g.size(),
            "pnl": g["pnl"].sum(),
            "win_rate_pct": g["pnl"].apply(lambda x: (x > 0).mean() * 100),
            "avg_r": g["r_multiple"].mean(),
        }
    ).sort_values("pnl", ascending=False)

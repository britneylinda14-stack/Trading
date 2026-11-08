from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def true_range(bars: pd.DataFrame) -> pd.Series:
    prev_close = bars["close"].shift(1)
    ranges = pd.concat(
        [
            bars["high"] - bars["low"],
            (bars["high"] - prev_close).abs(),
            (bars["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    return true_range(bars).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def efficiency_ratio(series: pd.Series, period: int) -> pd.Series:
    """Kaufman efficiency ratio: |net change| / sum of |bar changes|. 1 = pure trend, 0 = noise."""
    net = (series - series.shift(period)).abs()
    path = series.diff().abs().rolling(period).sum()
    return net / path

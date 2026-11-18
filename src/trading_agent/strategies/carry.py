from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr
from .base import Strategy


class TimeSeriesMomentum(Strategy):
    """Classic time-series momentum: hold the sign of the past `lookback`-bar return.

    The direction is only re-evaluated on the first bar of each month (monthly rebalancing,
    decided from that bar's close so earlier signals never change as new bars arrive),
    and positions are sized from an ATR stop, so every market carries similar risk.
    """

    name = "tsmom"

    def __init__(self, lookback: int = 252, atr_period: int = 20, atr_mult: float = 4.0):
        self.lookback, self.atr_period, self.atr_mult = int(lookback), int(atr_period), atr_mult

    def generate(self, bars: pd.DataFrame) -> pd.DataFrame:
        close = bars["close"]
        momentum = np.sign(close / close.shift(self.lookback) - 1)
        month = pd.Series(bars.index.to_period("M"), index=bars.index)
        month_start = month.ne(month.shift(1))
        direction = momentum.where(month_start).ffill().fillna(0).astype(int)
        stop = atr(bars, self.atr_period) * self.atr_mult
        return pd.DataFrame({"direction": direction, "stop_distance": stop}, index=bars.index)


class FxCarry(Strategy):
    """Hold the higher-yielding currency of a pair while the trend agrees.

    Needs a `carry` column (base minus quote policy rate, see `data.with_carry`): go long when
    carry >= `min_carry` and close > its `trend`-bar average, short in the mirror case.
    """

    name = "fx_carry"

    def __init__(
        self, trend: int = 200, min_carry: float = 0.01, atr_period: int = 20, atr_mult: float = 4.0
    ):
        self.trend, self.min_carry = int(trend), min_carry
        self.atr_period, self.atr_mult = int(atr_period), atr_mult

    def generate(self, bars: pd.DataFrame) -> pd.DataFrame:
        if "carry" not in bars:
            raise ValueError("fx_carry needs policy-rate carry data (use --carry)")
        carry, close = bars["carry"], bars["close"]
        average = close.rolling(self.trend).mean()
        long = (carry >= self.min_carry) & (close > average)
        short = (carry <= -self.min_carry) & (close < average)
        direction = long.astype(int) - short.astype(int)
        stop = atr(bars, self.atr_period) * self.atr_mult
        return pd.DataFrame({"direction": direction, "stop_distance": stop}, index=bars.index)

from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr, ema
from .base import Strategy


class EmaCross(Strategy):
    """Long when the fast EMA is above the slow EMA, short when below. ATR-based stop."""

    name = "ema_cross"

    def __init__(
        self, fast: int = 50, slow: int = 200, atr_period: int = 14, atr_mult: float = 3.0
    ):
        if fast >= slow:
            raise ValueError("fast must be < slow")
        self.fast, self.slow, self.atr_period, self.atr_mult = fast, slow, atr_period, atr_mult

    def generate(self, bars: pd.DataFrame) -> pd.DataFrame:
        diff = ema(bars["close"], self.fast) - ema(bars["close"], self.slow)
        direction = np.sign(diff).fillna(0).astype(int)
        stop = atr(bars, self.atr_period) * self.atr_mult
        return pd.DataFrame({"direction": direction, "stop_distance": stop}, index=bars.index)


class DonchianBreakout(Strategy):
    """Turtle-style breakout: enter on an N-bar high/low break, exit on an M-bar opposite break."""

    name = "donchian"

    def __init__(
        self, entry: int = 55, exit: int = 20, atr_period: int = 20, atr_mult: float = 2.0
    ):
        if exit >= entry:
            raise ValueError("exit must be < entry")
        self.entry, self.exit, self.atr_period, self.atr_mult = entry, exit, atr_period, atr_mult

    def generate(self, bars: pd.DataFrame) -> pd.DataFrame:
        hi_entry = bars["high"].rolling(self.entry).max().shift(1)
        lo_entry = bars["low"].rolling(self.entry).min().shift(1)
        hi_exit = bars["high"].rolling(self.exit).max().shift(1)
        lo_exit = bars["low"].rolling(self.exit).min().shift(1)
        close = bars["close"].to_numpy()

        direction = np.zeros(len(bars), dtype=int)
        state = 0
        for i in range(len(bars)):
            if state == 1 and close[i] < lo_exit.iat[i]:
                state = 0
            elif state == -1 and close[i] > hi_exit.iat[i]:
                state = 0
            if close[i] > hi_entry.iat[i]:
                state = 1
            elif close[i] < lo_entry.iat[i]:
                state = -1
            direction[i] = state

        stop = atr(bars, self.atr_period) * self.atr_mult
        return pd.DataFrame({"direction": direction, "stop_distance": stop}, index=bars.index)

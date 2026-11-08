from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr, efficiency_ratio
from .base import Strategy


class MeanReversion(Strategy):
    """Fade stretched moves back to the mean in range-bound markets.

    Enter when the z-score of close vs. its rolling mean exceeds `entry_z`, exit when it
    crosses back through `exit_z`. Only enters while the Kaufman efficiency ratio is
    below `max_er`, i.e. when the market is choppy rather than trending.
    """

    name = "mean_reversion"

    def __init__(
        self,
        lookback: int = 20,
        entry_z: float = 2.0,
        exit_z: float = 0.0,
        er_period: int = 100,
        max_er: float = 0.3,
        atr_period: int = 14,
        atr_mult: float = 2.5,
    ):
        if entry_z <= exit_z:
            raise ValueError("entry_z must be > exit_z")
        self.lookback, self.entry_z, self.exit_z = lookback, entry_z, exit_z
        self.er_period, self.max_er = er_period, max_er
        self.atr_period, self.atr_mult = atr_period, atr_mult

    def generate(self, bars: pd.DataFrame) -> pd.DataFrame:
        close = bars["close"]
        mean = close.rolling(self.lookback).mean()
        std = close.rolling(self.lookback).std()
        z = ((close - mean) / std).to_numpy()
        choppy = (efficiency_ratio(close, self.er_period) < self.max_er).to_numpy()

        direction = np.zeros(len(bars), dtype=int)
        state = 0
        for i in range(len(bars)):
            zi = z[i]
            if np.isnan(zi):
                direction[i] = 0
                continue
            if state == 1 and zi >= -self.exit_z:
                state = 0
            elif state == -1 and zi <= self.exit_z:
                state = 0
            if state == 0 and choppy[i]:
                if zi <= -self.entry_z:
                    state = 1
                elif zi >= self.entry_z:
                    state = -1
            direction[i] = state

        stop = atr(bars, self.atr_period) * self.atr_mult
        return pd.DataFrame({"direction": direction, "stop_distance": stop}, index=bars.index)


class SessionBreakout(Strategy):
    """Intraday breakout of the Asian-session range during the London/NY session.

    Needs intraday bars (e.g. 1h) with UTC timestamps. The range is built from bars
    starting in [range_start, range_end) UTC hours; trades are taken from range_end
    until session_end, then the position is flattened. Stop = range height x stop_mult
    (floored at min_stop_atr x ATR).
    """

    name = "session_breakout"

    def __init__(
        self,
        range_start: int = 0,
        range_end: int = 7,
        session_end: int = 16,
        stop_mult: float = 1.0,
        min_stop_atr: float = 0.5,
        atr_period: int = 24,
    ):
        if not 0 <= range_start < range_end < session_end <= 24:
            raise ValueError("need 0 <= range_start < range_end < session_end <= 24")
        self.range_start, self.range_end, self.session_end = range_start, range_end, session_end
        self.stop_mult, self.min_stop_atr, self.atr_period = stop_mult, min_stop_atr, atr_period

    def generate(self, bars: pd.DataFrame) -> pd.DataFrame:
        hours = bars.index.hour
        days = bars.index.normalize()
        in_range = (hours >= self.range_start) & (hours < self.range_end)
        in_session = (hours >= self.range_end) & (hours < self.session_end - 1)

        rng = bars[in_range].groupby(days[in_range]).agg(hi=("high", "max"), lo=("low", "min"))
        hi = pd.Series(days, index=bars.index).map(rng["hi"])
        lo = pd.Series(days, index=bars.index).map(rng["lo"])
        close = bars["close"]

        long_break = (close > hi) & in_session
        short_break = (close < lo) & in_session
        direction = np.zeros(len(bars), dtype=int)
        state, current_day = 0, None
        for i in range(len(bars)):
            if days[i] != current_day:
                state, current_day = 0, days[i]
            if not in_session[i]:
                state = 0
            elif state == 0:
                if long_break.iat[i]:
                    state = 1
                elif short_break.iat[i]:
                    state = -1
            direction[i] = state

        height = (hi - lo) * self.stop_mult
        floor = atr(bars, self.atr_period) * self.min_stop_atr
        stop = np.fmax(height, floor)
        return pd.DataFrame({"direction": direction, "stop_distance": stop}, index=bars.index)

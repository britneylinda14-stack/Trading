from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_agent.strategies.base import Strategy


def make_bars(closes, freq="D", start="2024-01-01", wick=0.0005, opens=None, lows=None):
    closes = np.asarray(closes, dtype=float)
    o = np.r_[closes[0], closes[:-1]] if opens is None else np.asarray(opens, dtype=float)
    hi = np.maximum(o, closes) + wick
    lo = np.minimum(o, closes) - wick if lows is None else np.asarray(lows, dtype=float)
    idx = pd.date_range(start, periods=len(closes), freq=freq)
    return pd.DataFrame(
        {"open": o, "high": hi, "low": lo, "close": closes, "volume": 0.0}, index=idx
    )


class FixedStrategy(Strategy):
    name = "fixed"

    def __init__(self, direction, stop_distance):
        self.direction = list(direction)
        self.stop_distance = stop_distance

    def generate(self, bars):
        stop = self.stop_distance
        if np.isscalar(stop):
            stop = [stop] * len(bars)
        return pd.DataFrame({"direction": self.direction, "stop_distance": stop}, index=bars.index)


@pytest.fixture
def bars_factory():
    return make_bars

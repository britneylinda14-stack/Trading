from __future__ import annotations

import numpy as np
import pandas as pd

from ..indicators import atr, rsi
from .base import Strategy


class AtmPullback(Strategy):
    """Trend pullback with confluence, modelled on Britney's "ATM" backtest journal.

    Long setup (shorts are the mirror image), evaluated at each bar's close:
      1. Trend: close and MA50 above MA200; with `structure`, the last swing high and
         swing low are higher than the previous ones (bullish order flow).
      2. Impulse: last swing low -> last confirmed swing high, at least
         `min_impulse_atr` ATRs long.
      3. Pullback: the lowest low since the swing high retraced between `fib_min` and
         `fib_max` of the impulse, without a new high.
      4. With `divergence`, hidden bullish RSI divergence: the pullback low is higher
         than the impulse low but its RSI is lower.
      5. Trigger: within `max_wait` bars of the pullback low, the close breaks the highest
         high of the previous `trigger_bars` bars (proxy for the pullback trendline break).
    Stop below the pullback low (plus `stop_buffer_atr` ATRs). At `be_r` R the engine
    closes `partial` of the position and moves the stop to entry; the rest targets
    `tp_r` R. One trade per impulse; positions are released after `max_hold` bars.
    """

    name = "atm_pullback"

    def __init__(
        self,
        swing: int = 5,
        fast_ma: int = 50,
        slow_ma: int = 200,
        fib_min: float = 0.382,
        fib_max: float = 0.618,
        min_impulse_atr: float = 3.0,
        structure: bool = True,
        divergence: bool = True,
        rsi_period: int = 14,
        trigger_bars: int = 3,
        max_wait: int = 12,
        stop_buffer_atr: float = 0.2,
        max_stop_atr: float = 4.0,
        tp_r: float = 2.5,
        be_r: float = 1.0,
        partial: float = 0.5,
        max_hold: int = 120,
        atr_period: int = 14,
    ):
        swing, fast_ma, slow_ma, trigger_bars = (
            int(swing),
            int(fast_ma),
            int(slow_ma),
            int(trigger_bars),
        )
        if not 0 < fib_min < fib_max < 1:
            raise ValueError("need 0 < fib_min < fib_max < 1")
        if fast_ma >= slow_ma:
            raise ValueError("fast_ma must be < slow_ma")
        if not 0 <= partial < 1:
            raise ValueError("partial must be in [0, 1)")
        if be_r and be_r >= tp_r:
            raise ValueError("be_r must be < tp_r")
        self.swing, self.fast_ma, self.slow_ma = swing, fast_ma, slow_ma
        self.fib_min, self.fib_max, self.min_impulse_atr = fib_min, fib_max, min_impulse_atr
        self.structure, self.divergence = bool(structure), bool(divergence)
        self.rsi_period, self.trigger_bars, self.max_wait = (
            int(rsi_period),
            trigger_bars,
            int(max_wait),
        )
        self.stop_buffer_atr, self.max_stop_atr = stop_buffer_atr, max_stop_atr
        self.tp_r, self.be_r, self.partial = tp_r, be_r, partial
        self.max_hold, self.atr_period = int(max_hold), int(atr_period)

    def generate(self, bars: pd.DataFrame) -> pd.DataFrame:
        h, lo, c = (bars[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
        ma_f = bars["close"].rolling(self.fast_ma).mean().to_numpy()
        ma_s = bars["close"].rolling(self.slow_ma).mean().to_numpy()
        r = rsi(bars["close"], self.rsi_period).to_numpy()
        a = atr(bars, self.atr_period).to_numpy()

        long_dist = self._triggers(h, lo, c, ma_f, ma_s, r, a)
        short_dist = self._triggers(-lo, -h, -c, -ma_f, -ma_s, 100 - r, a)

        n = len(bars)
        direction = np.zeros(n, dtype=int)
        stop_distance = np.full(n, np.nan)
        pos, stop, target, opened = 0, 0.0, 0.0, 0
        for i in range(n):
            if pos:
                stopped = lo[i] <= stop if pos > 0 else h[i] >= stop
                reached = h[i] >= target if pos > 0 else lo[i] <= target
                if stopped or reached or i - opened >= self.max_hold:
                    pos = 0
            for side, dist in ((1, long_dist[i]), (-1, short_dist[i])):
                if np.isfinite(dist) and pos != side:
                    pos, opened = side, i
                    stop, target = c[i] - side * dist, c[i] + side * dist * self.tp_r
                    stop_distance[i] = dist
                    break
            direction[i] = pos

        return pd.DataFrame(
            {
                "direction": direction,
                "stop_distance": stop_distance,
                "take_profit_r": self.tp_r,
                "breakeven_r": self.be_r,
                "partial": self.partial,
            },
            index=bars.index,
        )

    def _triggers(self, h, lo, c, ma_f, ma_s, r, a) -> np.ndarray:
        """Stop distance on bars where a long setup triggers, NaN elsewhere."""
        k, n = self.swing, len(c)
        out = np.full(n, np.nan)
        highs: list[int] = []
        lows: list[int] = []
        used = -1
        for i in range(n):
            j = i - k
            if j >= k:
                if h[j] == h[j - k : i + 1].max():
                    _add_pivot(highs, j, k, h[j] >= h[highs[-1]] if highs else True)
                if lo[j] == lo[j - k : i + 1].min():
                    _add_pivot(lows, j, k, lo[j] <= lo[lows[-1]] if lows else True)
            if len(highs) < 2 or not (np.isfinite(ma_s[i]) and np.isfinite(a[i])):
                continue
            if not (c[i] > ma_s[i] and ma_f[i] > ma_s[i]):
                continue
            jh = highs[-1]
            if jh == used:
                continue
            before = [x for x in lows[-8:] if x < jh]
            if len(before) < 2:
                continue
            jl, jl_prev = before[-1], before[-2]
            if self.structure and not (h[jh] > h[highs[-2]] and lo[jl] > lo[jl_prev]):
                continue
            top, rng = h[jh], h[jh] - lo[jl]
            if rng < self.min_impulse_atr * a[i] or i <= jh:
                continue
            seg = slice(jh + 1, i + 1)
            if h[seg].max() > top:
                continue
            pull_idx = jh + 1 + int(np.argmin(lo[seg]))
            depth = (top - lo[pull_idx]) / rng
            if not self.fib_min <= depth <= self.fib_max or i - pull_idx > self.max_wait:
                continue
            if self.divergence and not r[pull_idx] < r[jl]:
                continue
            window = h[max(pull_idx, i - self.trigger_bars) : i]
            if window.size == 0 or c[i] <= window.max():
                continue
            dist = c[i] - (lo[pull_idx] - self.stop_buffer_atr * a[i])
            if 0 < dist <= self.max_stop_atr * a[i]:
                out[i] = dist
                used = jh
        return out


def _add_pivot(pivots: list[int], j: int, k: int, more_extreme: bool) -> None:
    """Record a swing point; pivots within `k` bars of the previous one are the same swing."""
    if pivots and j - pivots[-1] <= k:
        if more_extreme:
            pivots[-1] = j
    else:
        pivots.append(j)

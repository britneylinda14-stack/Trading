"""Bar-by-bar backtest engine for a single instrument.

Execution model:
- A signal computed on bar i's close is executed at bar i+1's open (no lookahead).
- Fills pay half the spread on entry and half on exit.
- Stops (and optional take-profits) are checked intrabar; a gap through the stop
  fills at the open. If both stop and target are touched in one bar, the stop wins.
- One net position per instrument: no hedging, so US FIFO rules are satisfied.
- Financing is charged per calendar day held on the USD notional.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import pandas as pd

from .instruments import Instrument
from .risk import RiskConfig
from .strategies.base import Strategy


@dataclass
class Trade:
    instrument: str
    direction: int
    units: int
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    risk_usd: float
    take_profit: float | None = None
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    gross_pnl: float = 0.0
    spread_cost: float = 0.0
    financing: float = 0.0

    @property
    def pnl(self) -> float:
        return self.gross_pnl - self.financing

    @property
    def r_multiple(self) -> float:
        return self.pnl / self.risk_usd if self.risk_usd else 0.0


@dataclass
class BacktestResult:
    instrument: Instrument
    strategy: str
    risk: RiskConfig
    equity: pd.Series
    trades: list[Trade] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    skipped_signals: int = 0

    def trades_frame(self) -> pd.DataFrame:
        rows = []
        for t in self.trades:
            row = asdict(t)
            row.update(pnl=t.pnl, r_multiple=t.r_multiple)
            rows.append(row)
        return pd.DataFrame(rows)


class Backtester:
    def __init__(self, instrument: Instrument, strategy: Strategy, risk: RiskConfig | None = None):
        self.instrument = instrument
        self.strategy = strategy
        self.risk = risk or RiskConfig()
        cap = instrument.max_leverage
        if self.risk.max_leverage is not None:
            cap = min(cap, self.risk.max_leverage)
        self.max_leverage = cap

    def _pnl_usd(self, trade: Trade, exit_price: float) -> float:
        quote_pnl = trade.direction * trade.units * (exit_price - trade.entry_price)
        return self.instrument.to_usd(quote_pnl, exit_price)

    def size_position(self, equity: float, price: float, stop_distance: float) -> int:
        inst = self.instrument
        loss_per_unit = inst.to_usd(stop_distance + inst.spread, price)
        if loss_per_unit <= 0 or equity <= 0:
            return 0
        units = equity * self.risk.risk_per_trade / loss_per_unit
        max_units = equity * self.max_leverage / inst.notional_usd(1, price)
        return int(math.floor(min(units, max_units)))

    def run(self, bars: pd.DataFrame) -> BacktestResult:
        inst, risk = self.instrument, self.risk
        signals = self.strategy.generate(bars).reindex(bars.index)
        direction = signals["direction"].fillna(0).astype(int).to_numpy()
        stop_dist = signals["stop_distance"].to_numpy(dtype=float)
        times = bars.index
        o, h, lo, c = (bars[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        half = inst.spread / 2

        realized = risk.initial_equity
        pos: Trade | None = None
        trades: list[Trade] = []
        events: list[str] = []
        equity_curve = [realized]
        peak = realized
        day_start_equity = realized
        current_day = times[0].date()
        halted_today = False
        killed = False
        blocked_direction = 0
        skipped_signals = 0
        last_skipped = 0

        def close(trade: Trade, mid_price: float, when: pd.Timestamp, reason: str) -> float:
            fill = mid_price - trade.direction * half
            trade.exit_price, trade.exit_time, trade.exit_reason = fill, when, reason
            trade.gross_pnl = self._pnl_usd(trade, fill)
            trade.spread_cost = inst.to_usd(trade.units * inst.spread, fill)
            trades.append(trade)
            return trade.gross_pnl

        def mark(price: float) -> float:
            return realized + (self._pnl_usd(pos, price) if pos else 0.0)

        for i in range(1, len(bars)):
            t = times[i]
            day = t.date()
            if day != current_day:
                if pos is not None:
                    days = (day - current_day).days
                    cost = inst.notional_usd(pos.units, c[i - 1]) * inst.financing_rate * days / 365
                    pos.financing += cost
                    realized -= cost
                current_day = day
                day_start_equity = equity_curve[-1]
                halted_today = False

            sig, dist = direction[i - 1], stop_dist[i - 1]
            if sig != blocked_direction:
                blocked_direction = 0

            if pos is not None and sig != pos.direction:
                realized += close(pos, o[i], t, "signal")
                pos = None

            can_trade = not (halted_today or killed)
            if pos is None and sig != 0 and sig != blocked_direction and can_trade:
                if math.isfinite(dist) and dist > 0:
                    entry = o[i] + sig * half
                    units = self.size_position(mark(o[i]), o[i], dist)
                    if units < 1 and sig != last_skipped:
                        skipped_signals += 1
                        last_skipped = sig
                    if units >= 1:
                        last_skipped = 0
                        stop = entry - sig * dist
                        tp = entry + sig * dist * risk.take_profit_r if risk.take_profit_r else None
                        pos = Trade(
                            inst.name,
                            int(sig),
                            units,
                            t,
                            entry,
                            stop,
                            risk_usd=inst.to_usd(units * (dist + inst.spread), o[i]),
                            take_profit=tp,
                        )

            if pos is not None:
                d = pos.direction
                stop_hit = lo[i] <= pos.stop_price if d > 0 else h[i] >= pos.stop_price
                tp_hit = pos.take_profit is not None and (
                    h[i] >= pos.take_profit if d > 0 else lo[i] <= pos.take_profit
                )
                if stop_hit:
                    level = pos.stop_price + d * half
                    gapped = (o[i] < level) if d > 0 else (o[i] > level)
                    fill_mid = o[i] if gapped and t != pos.entry_time else level
                    realized += close(pos, fill_mid, t, "stop_loss")
                    blocked_direction = d
                    pos = None
                elif tp_hit:
                    level = pos.take_profit + d * half
                    gapped = (o[i] > level) if d > 0 else (o[i] < level)
                    fill_mid = o[i] if gapped and t != pos.entry_time else level
                    realized += close(pos, fill_mid, t, "take_profit")
                    blocked_direction = d
                    pos = None

            eq = mark(c[i])
            if pos is not None and eq <= day_start_equity * (1 - risk.max_daily_loss):
                realized += close(pos, c[i], t, "daily_loss_limit")
                blocked_direction = pos.direction
                pos = None
                halted_today = True
                events.append(f"{t}: daily loss limit hit, trading halted for the day")
                eq = realized
            if not killed and eq <= peak * (1 - risk.max_drawdown):
                if pos is not None:
                    realized += close(pos, c[i], t, "max_drawdown_kill")
                    pos = None
                    eq = realized
                killed = True
                events.append(f"{t}: max drawdown kill switch triggered, trading stopped")
            peak = max(peak, eq)
            equity_curve.append(eq)

        if pos is not None:
            realized += close(pos, c[-1], times[-1], "end_of_data")
            equity_curve[-1] = realized

        return BacktestResult(
            inst,
            self.strategy.name,
            risk,
            pd.Series(equity_curve, index=times, name="equity"),
            trades,
            events,
            skipped_signals,
        )

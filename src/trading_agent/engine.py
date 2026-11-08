"""Bar-by-bar backtest engine, single instrument or portfolio with shared equity.

Execution model:
- A signal computed on bar i's close is executed at bar i+1's open (no lookahead).
- Fills pay half the spread on entry and half on exit.
- Stops (and optional take-profits) are checked intrabar; a gap through the stop
  fills at the open. If both stop and target are touched in one bar, the stop wins.
- One net position per instrument: no hedging, so US FIFO rules are satisfied.
- Financing is charged per calendar day held on the USD notional.
- Portfolio limits: margin used (notional / leverage cap) never exceeds equity, and the
  sum of open trades' initial risk stays under `max_open_risk`.
- Optional economic-calendar blackout: no new entries on bars overlapping an event
  window, and optionally flatten at the open of such bars.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np
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
    instruments: list[Instrument]
    strategy: str
    risk: RiskConfig
    equity: pd.Series
    trades: list[Trade] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    skipped_signals: int = 0
    blackout_skips: int = 0

    @property
    def instrument(self) -> Instrument:
        return self.instruments[0]

    @property
    def label(self) -> str:
        if len(self.instruments) == 1:
            return self.instruments[0].name
        return f"PORTFOLIO({len(self.instruments)})"

    def trades_frame(self) -> pd.DataFrame:
        rows = []
        for t in self.trades:
            row = asdict(t)
            row.update(pnl=t.pnl, r_multiple=t.r_multiple)
            rows.append(row)
        return pd.DataFrame(rows)


@dataclass
class _Leg:
    inst: Instrument
    times: pd.DatetimeIndex
    o: np.ndarray
    h: np.ndarray
    lo: np.ndarray
    c: np.ndarray
    direction: np.ndarray
    stop_dist: np.ndarray
    blackout: np.ndarray
    leverage: float
    k: int = 0
    pos: Trade | None = None
    blocked: int = 0
    last_skipped: int = 0
    last_price: float = float("nan")
    last_day: date | None = None


class PortfolioBacktester:
    def __init__(
        self,
        legs: list[tuple[Instrument, Strategy]],
        risk: RiskConfig | None = None,
        calendar=None,
        flatten_on_events: bool = False,
    ):
        if not legs:
            raise ValueError("need at least one (instrument, strategy) leg")
        names = [inst.name for inst, _ in legs]
        if len(set(names)) != len(names):
            raise ValueError("duplicate instrument in portfolio")
        self.legs = legs
        self.risk = risk or RiskConfig()
        self.calendar = calendar
        self.flatten_on_events = flatten_on_events

    def _leverage(self, inst: Instrument) -> float:
        cap = inst.max_leverage
        return min(cap, self.risk.max_leverage) if self.risk.max_leverage else cap

    def _prepare(self, inst: Instrument, strategy: Strategy, bars: pd.DataFrame) -> _Leg:
        signals = strategy.generate(bars).reindex(bars.index)
        blackout = (
            self.calendar.blackout(bars.index, inst)
            if self.calendar is not None
            else np.zeros(len(bars), dtype=bool)
        )
        return _Leg(
            inst,
            bars.index,
            *(bars[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close")),
            signals["direction"].fillna(0).astype(int).to_numpy(),
            signals["stop_distance"].to_numpy(dtype=float),
            blackout,
            self._leverage(inst),
        )

    @staticmethod
    def _pnl_usd(inst: Instrument, trade: Trade, exit_price: float) -> float:
        quote_pnl = trade.direction * trade.units * (exit_price - trade.entry_price)
        return inst.to_usd(quote_pnl, exit_price)

    def run(
        self, data: dict[str, pd.DataFrame], trade_from: pd.Timestamp | str | None = None
    ) -> BacktestResult:
        """Run the backtest. Bars before `trade_from` only warm up indicators."""
        risk = self.risk
        trade_from = pd.Timestamp(trade_from) if trade_from is not None else None
        legs = [self._prepare(inst, strat, data[inst.name]) for inst, strat in self.legs]
        timeline = legs[0].times
        for leg in legs[1:]:
            timeline = timeline.union(leg.times)

        realized = risk.initial_equity
        trades: list[Trade] = []
        events: list[str] = []
        equity_curve: list[float] = []
        peak = day_start_equity = realized
        current_day = None
        halted_today = killed = False
        skipped_signals = blackout_skips = 0

        def unrealized() -> float:
            return sum(self._pnl_usd(leg.inst, leg.pos, leg.last_price) for leg in legs if leg.pos)

        def close(leg: _Leg, mid_price: float, when: pd.Timestamp, reason: str) -> float:
            trade, inst = leg.pos, leg.inst
            fill = mid_price - trade.direction * inst.spread / 2
            trade.exit_price, trade.exit_time, trade.exit_reason = fill, when, reason
            trade.gross_pnl = self._pnl_usd(inst, trade, fill)
            trade.spread_cost = inst.to_usd(trade.units * inst.spread, fill)
            trades.append(trade)
            leg.pos = None
            return trade.gross_pnl

        def size(leg: _Leg, equity: float, price: float, dist: float) -> int:
            inst = leg.inst
            loss_per_unit = inst.to_usd(dist + inst.spread, price)
            if loss_per_unit <= 0 or equity <= 0:
                return 0
            open_risk = sum(lg.pos.risk_usd for lg in legs if lg.pos)
            margin_used = sum(
                lg.inst.notional_usd(lg.pos.units, lg.last_price) / lg.leverage
                for lg in legs
                if lg.pos
            )
            by_risk = equity * risk.risk_per_trade / loss_per_unit
            by_budget = max(equity * risk.max_open_risk - open_risk, 0) / loss_per_unit
            by_margin = max(equity - margin_used, 0) * leg.leverage / inst.notional_usd(1, price)
            return int(math.floor(min(by_risk, by_budget, by_margin)))

        for t in timeline:
            warming_up = trade_from is not None and t < trade_from
            day = t.date()
            if day != current_day:
                current_day = day
                if equity_curve:
                    day_start_equity = equity_curve[-1]
                halted_today = False

            closed_bars: list[tuple[_Leg, float]] = []
            for leg in legs:
                if leg.k >= len(leg.times) or leg.times[leg.k] != t:
                    continue
                i, inst = leg.k, leg.inst
                leg.k += 1
                if i == 0:
                    leg.last_price, leg.last_day = leg.c[0], day
                    continue
                half = inst.spread / 2

                if day != leg.last_day:
                    if leg.pos is not None:
                        days = (day - leg.last_day).days
                        notional = inst.notional_usd(leg.pos.units, leg.c[i - 1])
                        cost = notional * inst.financing_rate * days / 365
                        leg.pos.financing += cost
                        realized -= cost
                    leg.last_day = day
                leg.last_price = leg.o[i]

                sig, dist, blackout = leg.direction[i - 1], leg.stop_dist[i - 1], leg.blackout[i]
                if sig != leg.blocked:
                    leg.blocked = 0

                if leg.pos is not None:
                    if sig != leg.pos.direction:
                        realized += close(leg, leg.o[i], t, "signal")
                    elif blackout and self.flatten_on_events:
                        realized += close(leg, leg.o[i], t, "news_blackout")
                        leg.blocked = sig

                wants_entry = leg.pos is None and sig != 0 and sig != leg.blocked
                if wants_entry and blackout:
                    blackout_skips += 1
                elif wants_entry and not (halted_today or killed or warming_up):
                    if math.isfinite(dist) and dist > 0:
                        units = size(leg, realized + unrealized(), leg.o[i], dist)
                        if units < 1 and sig != leg.last_skipped:
                            skipped_signals += 1
                            leg.last_skipped = sig
                        if units >= 1:
                            leg.last_skipped = 0
                            entry = leg.o[i] + sig * half
                            tp = (
                                entry + sig * dist * risk.take_profit_r
                                if risk.take_profit_r
                                else None
                            )
                            leg.pos = Trade(
                                inst.name,
                                int(sig),
                                units,
                                t,
                                entry,
                                entry - sig * dist,
                                risk_usd=inst.to_usd(units * (dist + inst.spread), leg.o[i]),
                                take_profit=tp,
                            )

                pos = leg.pos
                if pos is not None:
                    d = pos.direction
                    stop_hit = leg.lo[i] <= pos.stop_price if d > 0 else leg.h[i] >= pos.stop_price
                    tp_hit = pos.take_profit is not None and (
                        leg.h[i] >= pos.take_profit if d > 0 else leg.lo[i] <= pos.take_profit
                    )
                    if stop_hit or tp_hit:
                        target = pos.stop_price if stop_hit else pos.take_profit
                        level = target + d * half
                        if stop_hit:
                            gapped = leg.o[i] < level if d > 0 else leg.o[i] > level
                        else:
                            gapped = leg.o[i] > level if d > 0 else leg.o[i] < level
                        fill_mid = leg.o[i] if gapped and t != pos.entry_time else level
                        reason = "stop_loss" if stop_hit else "take_profit"
                        realized += close(leg, fill_mid, t, reason)
                        leg.blocked = d
                if leg.k == len(leg.times) and leg.pos is not None:
                    realized += close(leg, leg.c[i], t, "end_of_data")
                closed_bars.append((leg, leg.c[i]))

            for leg, price in closed_bars:
                leg.last_price = price

            eq = realized + unrealized()
            if not halted_today and eq <= day_start_equity * (1 - risk.max_daily_loss):
                for leg in [leg for leg in legs if leg.pos]:
                    leg.blocked = leg.pos.direction
                    realized += close(leg, leg.last_price, t, "daily_loss_limit")
                halted_today = True
                events.append(f"{t}: daily loss limit hit, trading halted for the day")
                eq = realized
            if not killed and eq <= peak * (1 - risk.max_drawdown):
                for leg in legs:
                    if leg.pos:
                        realized += close(leg, leg.last_price, t, "max_drawdown_kill")
                eq = realized
                killed = True
                events.append(f"{t}: max drawdown kill switch triggered, trading stopped")
            peak = max(peak, eq)
            equity_curve.append(eq)

        for leg in legs:
            if leg.pos is not None:
                realized += close(leg, leg.last_price, leg.times[-1], "end_of_data")
        equity_curve[-1] = realized
        trades.sort(key=lambda tr: tr.entry_time)
        equity = pd.Series(equity_curve, index=timeline, name="equity")
        if trade_from is not None:
            equity = equity[equity.index >= trade_from]

        return BacktestResult(
            [inst for inst, _ in self.legs],
            self.legs[0][1].name,
            risk,
            equity,
            trades,
            events,
            skipped_signals,
            blackout_skips,
        )


class Backtester:
    """Single-instrument convenience wrapper around PortfolioBacktester."""

    def __init__(
        self,
        instrument: Instrument,
        strategy: Strategy,
        risk: RiskConfig | None = None,
        calendar=None,
        flatten_on_events: bool = False,
    ):
        self.instrument = instrument
        self._engine = PortfolioBacktester(
            [(instrument, strategy)], risk, calendar, flatten_on_events
        )
        self.risk = self._engine.risk

    def run(self, bars: pd.DataFrame, trade_from=None) -> BacktestResult:
        return self._engine.run({self.instrument.name: bars}, trade_from)

from __future__ import annotations

import pytest
from conftest import FixedStrategy, make_bars

from trading_agent.engine import Backtester
from trading_agent.instruments import get_instrument
from trading_agent.risk import RiskConfig

EUR = get_instrument("EUR_USD")
HALF = EUR.spread / 2


def run(bars, direction, stop, inst=EUR, **risk):
    return Backtester(inst, FixedStrategy(direction, stop), RiskConfig(**risk)).run(bars)


def test_signal_executes_at_next_open_with_spread():
    bars = make_bars([1.10, 1.10, 1.101, 1.102, 1.103])
    res = run(bars, [0, 1, 1, 1, 1], 0.01)
    t = res.trades[0]
    assert t.entry_time == bars.index[2]
    assert t.entry_price == pytest.approx(bars["open"].iat[2] + HALF)
    assert t.exit_reason == "end_of_data"
    assert t.exit_price == pytest.approx(bars["close"].iat[-1] - HALF)


def test_stop_loss_loses_about_one_risk_unit():
    closes = [1.10, 1.10, 1.10, 1.10, 1.10, 1.09, 1.09]
    bars = make_bars(closes, wick=0.0001)
    res = run(bars, [0, 1, 1, 1, 1, 1, 1], 0.005)
    t = res.trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(t.stop_price)
    loss_pct = -t.pnl / 10_000
    assert 0.0095 < loss_pct < 0.0102
    assert t.r_multiple == pytest.approx(-1, abs=0.02)
    assert len(res.trades) == 1, "must not re-enter the same direction after a stop"


def test_gap_through_stop_fills_at_open():
    closes = [1.10, 1.10, 1.10, 1.08]
    bars = make_bars(closes, opens=[1.10, 1.10, 1.10, 1.08])
    t = run(bars, [0, 1, 1, 1], 0.005).trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(1.08 - HALF)


def test_short_trade_profits_when_price_falls():
    bars = make_bars([1.10, 1.10, 1.09, 1.08, 1.07])
    t = run(bars, [0, -1, -1, -1, -1], 0.05).trades[0]
    assert t.direction == -1
    assert t.pnl > 0


def test_leverage_cap_limits_position_size():
    bars = make_bars([1.10, 1.10, 1.10, 1.10])
    t = run(bars, [0, 1, 1, 1], 0.00001).trades[0]
    assert EUR.notional_usd(t.units, t.entry_price) <= 10_000 * 50 * 1.0001
    t2 = run(bars, [0, 1, 1, 1], 0.00001, max_leverage=10).trades[0]
    assert EUR.notional_usd(t2.units, t2.entry_price) <= 10_000 * 10 * 1.0001


def test_reversal_closes_before_opening_no_hedging():
    bars = make_bars([1.10, 1.10, 1.11, 1.12, 1.11, 1.10, 1.09])
    res = run(bars, [0, 1, 1, -1, -1, -1, -1], 0.05)
    assert [t.direction for t in res.trades] == [1, -1]
    first, second = res.trades
    assert first.exit_reason == "signal"
    assert first.exit_time <= second.entry_time


def test_daily_loss_limit_flattens_and_halts():
    closes = [1.10, 1.10] + [1.10 - 0.001 * k for k in range(1, 15)]
    bars = make_bars(closes, freq="h", start="2024-01-02")
    res = run(
        bars, [1] * len(closes), 0.05, risk_per_trade=0.2, max_open_risk=0.5, max_daily_loss=0.03
    )
    assert len(res.trades) == 1
    assert res.trades[0].exit_reason == "daily_loss_limit"
    assert res.equity.iloc[-1] > 10_000 * (1 - 0.04)
    assert any("daily loss" in e for e in res.events)


def test_max_drawdown_kill_switch():
    closes = [1.10, 1.10] + [1.10 - 0.002 * k for k in range(1, 30)]
    bars = make_bars(closes, freq="D")
    res = run(
        bars,
        [1] * len(closes),
        0.2,
        risk_per_trade=0.5,
        max_open_risk=0.9,
        max_daily_loss=0.5,
        max_drawdown=0.1,
    )
    assert res.trades[-1].exit_reason == "max_drawdown_kill"
    assert len(res.trades) == 1
    assert res.equity.iloc[-1] == res.equity.iloc[-5]


def test_usd_base_pair_pnl_converted_to_usd():
    jpy = get_instrument("USD_JPY")
    assert jpy.to_usd(150.0, 150.0) == pytest.approx(1.0)
    bars = make_bars([150.0, 150.0, 150.0, 151.5], wick=0.01)
    t = run(bars, [0, 1, 1, 1], 1.0, inst=jpy).trades[0]
    expected = t.units * (t.exit_price - t.entry_price) / t.exit_price
    assert t.gross_pnl == pytest.approx(expected)


def test_financing_charged_per_day_held():
    bars = make_bars([1.10] * 6, freq="D")
    t = run(bars, [0, 1, 1, 1, 1, 1], 0.05).trades[0]
    days = (bars.index[-1] - bars.index[2]).days
    expected = EUR.notional_usd(t.units, 1.10) * EUR.financing_rate * days / 365
    assert t.financing == pytest.approx(expected, rel=1e-6)


def test_take_profit():
    closes = [1.10, 1.10, 1.10, 1.12]
    t = run(make_bars(closes), [0, 1, 1, 1], 0.005, take_profit_r=2).trades[0]
    assert t.exit_reason == "take_profit"
    assert t.r_multiple == pytest.approx(2, abs=0.1)


def test_signal_skipped_when_position_below_one_unit():
    gold = get_instrument("XAU_USD")
    bars = make_bars([2000.0] * 5, wick=1.0)
    res = run(bars, [0, 1, 1, 1, 1], 500.0, inst=gold, initial_equity=1_000)
    assert res.trades == []
    assert res.skipped_signals == 1

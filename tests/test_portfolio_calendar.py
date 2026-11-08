from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from conftest import FixedStrategy, make_bars

from trading_agent.calendar import Event, EventCalendar, nfp_release_date
from trading_agent.engine import Backtester, PortfolioBacktester
from trading_agent.instruments import get_instrument
from trading_agent.research import expand_grid, sweep
from trading_agent.risk import RiskConfig
from trading_agent.strategies import MeanReversion, SessionBreakout

EUR, GBP, AUD, JPY = (get_instrument(n) for n in ("EUR_USD", "GBP_USD", "AUD_USD", "USD_JPY"))


def portfolio(insts, direction, stop, **risk):
    strat = FixedStrategy(direction, stop)
    return PortfolioBacktester([(i, strat) for i in insts], RiskConfig(**risk))


def test_portfolio_equity_is_sum_of_trade_pnl():
    bars = make_bars([1.10, 1.10, 1.11, 1.12, 1.13, 1.12])
    res = portfolio([EUR, GBP], [0, 1, 1, 1, 1, 1], 0.05).run({"EUR_USD": bars, "GBP_USD": bars})
    assert {t.instrument for t in res.trades} == {"EUR_USD", "GBP_USD"}
    assert res.equity.iloc[-1] == pytest.approx(10_000 + sum(t.pnl for t in res.trades))


def test_portfolio_open_risk_budget_caps_total_risk():
    bars = make_bars([1.10] * 5)
    data = {i.name: bars for i in (EUR, GBP, AUD)}
    res = portfolio(
        [EUR, GBP, AUD], [0, 1, 1, 1, 1], 0.01, risk_per_trade=0.02, max_open_risk=0.03
    ).run(data)
    total_risk = sum(t.risk_usd for t in res.trades)
    assert total_risk <= 10_000 * 0.03 * 1.001
    assert res.trades[0].risk_usd == pytest.approx(200, rel=0.01)


def test_portfolio_margin_shared_across_positions():
    bars = make_bars([1.10] * 4, wick=0.0001)
    res = portfolio([EUR, GBP], [0, 1, 1, 1], 0.001, risk_per_trade=0.5, max_open_risk=0.99).run(
        {"EUR_USD": bars, "GBP_USD": bars}
    )
    margin = sum(
        get_instrument(t.instrument).notional_usd(t.units, t.entry_price) / 50 for t in res.trades
    )
    assert all(t.exit_reason == "end_of_data" for t in res.trades)
    assert margin <= 10_000 * 1.001


def test_portfolio_handles_different_calendars():
    fx = make_bars([1.10, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15], freq="D")
    gold = make_bars([2000, 2000, 2010, 2020], freq="2D", wick=1.0)
    res = PortfolioBacktester(
        [
            (EUR, FixedStrategy([0, 1, 1, 1, 1, 1, 1], 0.05)),
            (get_instrument("XAU_USD"), FixedStrategy([0, 1, 1, 1], 50.0)),
        ]
    ).run({"EUR_USD": fx, "XAU_USD": gold})
    assert len(res.equity) == len(fx.index.union(gold.index))
    assert {t.instrument for t in res.trades} == {"EUR_USD", "XAU_USD"}


def test_trade_from_warms_up_without_trading():
    bars = make_bars(np.linspace(1.10, 1.20, 30))
    res = Backtester(EUR, FixedStrategy([1] * 30, 0.05)).run(bars, trade_from=bars.index[10])
    assert res.trades[0].entry_time == bars.index[10]
    assert res.equity.index[0] == bars.index[9]
    assert res.equity.iloc[0] == pytest.approx(10_000)


def test_nfp_rule_matches_known_dates():
    assert nfp_release_date(2024, 2) == date(2024, 3, 8)
    assert nfp_release_date(2024, 10) == date(2024, 11, 1)
    assert nfp_release_date(2025, 1) == date(2025, 2, 7)


def test_default_calendar_has_all_event_types():
    cal = EventCalendar.default()
    assert {"FOMC", "NFP", "CPI"} <= cal.names()
    times = {e.time for e in cal.events if e.name == "FOMC"}
    assert pd.Timestamp("2024-12-18 19:00") in times  # 14:00 EST
    nfp = {e.time for e in cal.events if e.name == "NFP"}
    assert pd.Timestamp("2025-01-10 13:30") in nfp  # holiday-shifted release


def test_blackout_window_hourly_and_currency_filter():
    cal = EventCalendar([Event(pd.Timestamp("2024-06-12 18:00"), "FOMC")])
    idx = pd.date_range("2024-06-12 14:00", periods=10, freq="h")
    mask = pd.Series(cal.blackout(idx, EUR), index=idx)
    assert list(mask[mask].index.hour) == [16, 17, 18, 19]
    eur_only = EventCalendar([Event(pd.Timestamp("2024-06-12 18:00"), "ECB", "EUR")])
    assert eur_only.blackout(idx, EUR).any()
    assert not eur_only.blackout(idx, JPY).any()


def test_blackout_blocks_entry_and_flattens():
    bars = make_bars([1.10, 1.10, 1.11, 1.12, 1.13, 1.14])
    cal = EventCalendar([Event(bars.index[2] + pd.Timedelta(hours=13), "CPI")])
    strat = FixedStrategy([0, 1, 1, 1, 1, 1], 0.05)
    res = Backtester(EUR, strat, calendar=cal).run(bars)
    assert res.blackout_skips == 1
    assert res.trades[0].entry_time == bars.index[3]

    cal2 = EventCalendar([Event(bars.index[4] + pd.Timedelta(hours=13), "CPI")])
    res2 = Backtester(EUR, strat, calendar=cal2, flatten_on_events=True).run(bars)
    assert res2.trades[0].exit_reason == "news_blackout"
    assert res2.trades[0].exit_time == bars.index[4]


def test_mean_reversion_trades_both_sides_without_lookahead():
    x = np.arange(400)
    bars = make_bars(1.10 + 0.01 * np.sin(x / 6) + 0.002 * np.sin(x * 1.7))
    strat = MeanReversion(lookback=20, entry_z=1.5)
    sig = strat.generate(bars)
    assert {-1, 1} <= set(sig["direction"].unique())
    assert sig.iloc[:200].equals(strat.generate(bars.iloc[:200]))


def test_session_breakout_enters_after_range_and_flattens_at_session_end():
    idx = pd.date_range("2024-01-02 00:00", periods=48, freq="h")
    close = np.full(48, 1.1000)
    close[9:16] = 1.1030
    bars = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.0002,
            "low": close - 0.0002,
            "close": close,
            "volume": 0.0,
        },
        index=idx,
    )
    sig = SessionBreakout(range_end=7, session_end=16).generate(bars).set_index(idx)
    d = sig["direction"]
    assert d.iloc[:9].eq(0).all()
    assert d.iloc[9:15].eq(1).all()
    assert d.iloc[15:].eq(0).all()
    assert sig["stop_distance"].iloc[9] > 0


def test_research_sweep_splits_in_and_out_of_sample():
    rng = np.random.default_rng(1)
    idx_n = 600
    bars = make_bars(1.0 + 0.0004 * np.arange(idx_n) + rng.normal(0, 0.002, idx_n))
    data = {"EUR_USD": bars, "GBP_USD": bars}
    grid = {"fast": [10, 20], "slow": [20, 50]}
    assert len(expand_grid(grid)) == 4
    res = sweep([EUR, GBP], "ema_cross", data, bars.index[400], grid)
    assert len(res.table) == 3  # fast=20/slow=20 is invalid and skipped
    assert {"is_sharpe", "oos_sharpe", "fast", "slow"} <= set(res.table.columns)
    assert res.table["is_sharpe"].is_monotonic_decreasing
    assert "out-of-sample" in res.summary()


def test_leg_closes_when_its_data_ends():
    short = make_bars([1.10, 1.10, 1.11, 1.12], freq="D")
    long = make_bars([1.10] * 8, freq="D")
    res = PortfolioBacktester(
        [(EUR, FixedStrategy([0, 1, 1, 1], 0.05)), (GBP, FixedStrategy([0] * 8, 0.05))]
    ).run({"EUR_USD": short, "GBP_USD": long})
    t = res.trades[0]
    assert t.exit_reason == "end_of_data" and t.exit_time == short.index[-1]
    assert res.equity.iloc[-1] == pytest.approx(res.equity.loc[short.index[-1]])


def test_research_rejects_split_outside_data():
    bars = make_bars(np.linspace(1.0, 1.1, 50), start="2025-01-01")
    with pytest.raises(ValueError, match="inside the data range"):
        sweep([EUR], "ema_cross", {"EUR_USD": bars}, "2020-01-01", {"fast": [5], "slow": [10]})


def test_default_calendar_covers_scheduled_cpi():
    cal = EventCalendar.default(include=("CPI",))
    assert pd.Timestamp("2027-01-13 13:30") in {e.time for e in cal.events}


def _pullback_bars():
    up = np.linspace(1.00, 1.10, 300)
    swings = []
    level = 1.10
    for _ in range(4):
        swings += list(np.linspace(level, level + 0.02, 15)) + list(
            np.linspace(level + 0.02, level + 0.01, 8)
        )
        level += 0.01
    closes = np.r_[up, swings, np.linspace(level, level + 0.03, 20)]
    return make_bars(closes, freq="h", wick=0.0003)


def test_atm_pullback_buys_trend_pullbacks_with_exit_plan():
    from trading_agent.strategies import AtmPullback

    bars = _pullback_bars()
    sig = AtmPullback(swing=3, min_impulse_atr=1.0, divergence=False).generate(bars)
    entries = sig.index[(sig["direction"] == 1) & (sig["direction"].shift(fill_value=0) != 1)]
    assert len(entries) >= 1
    assert (sig["direction"] >= 0).all()
    assert (sig.loc[entries, "stop_distance"] > 0).all()
    assert {"take_profit_r", "breakeven_r", "partial"} <= set(sig.columns)


def test_atm_pullback_has_no_lookahead():
    from trading_agent.strategies import AtmPullback

    bars = _pullback_bars()
    strat = AtmPullback(swing=3, min_impulse_atr=1.0, divergence=False)
    full = strat.generate(bars)
    cut = len(bars) - 25
    partial = strat.generate(bars.iloc[:cut])
    pd.testing.assert_series_equal(full["direction"].iloc[:cut], partial["direction"])


def test_histdata_parses_est_minutes_into_utc_bars():
    import io
    import zipfile

    from trading_agent.data.histdata import parse_m1

    rows = "20180101 170000;1.2;1.3;1.1;1.25;0\n20180101 170100;1.25;1.4;1.2;1.3;0\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("DAT_ASCII_EURUSD_M1_2018.csv", rows)
    df = parse_m1(buf.getvalue())
    assert list(df.index) == [pd.Timestamp("2018-01-01 22:00"), pd.Timestamp("2018-01-01 22:01")]
    assert df.iloc[1]["high"] == 1.4 and df.iloc[0]["close"] == 1.25

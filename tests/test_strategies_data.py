from __future__ import annotations

import numpy as np
import pytest
from conftest import make_bars

from trading_agent.data import load_csv, load_mt5_csv
from trading_agent.engine import Backtester
from trading_agent.indicators import atr
from trading_agent.instruments import get_instrument
from trading_agent.metrics import compute_metrics
from trading_agent.strategies import DonchianBreakout, EmaCross, get_strategy


def trending(n=400, slope=0.0005):
    rng = np.random.default_rng(0)
    return make_bars(1.0 + slope * np.arange(n) + rng.normal(0, 0.002, n))


@pytest.mark.parametrize("strategy", [EmaCross(), DonchianBreakout()])
def test_strategies_go_long_in_uptrend(strategy):
    bars = trending()
    sig = strategy.generate(bars)
    assert list(sig.columns) == ["direction", "stop_distance"]
    assert set(sig["direction"].unique()) <= {-1, 0, 1}
    assert (sig["direction"].iloc[-100:] == 1).mean() > 0.9


def test_strategy_has_no_lookahead():
    bars = trending()
    full = EmaCross(fast=10, slow=30).generate(bars)
    partial = EmaCross(fast=10, slow=30).generate(bars.iloc[:200])
    assert full.iloc[:200].equals(partial)


def test_trend_backtest_profitable_and_metrics():
    res = Backtester(get_instrument("EUR_USD"), get_strategy("ema_cross", fast=10, slow=30)).run(
        trending()
    )
    m = compute_metrics(res)
    assert m["total_return_pct"] > 0
    assert m["trades"] >= 1
    assert m["max_drawdown_pct"] <= 0


def test_atr_constant_range():
    bars = make_bars([1.0] * 50, wick=0.01)
    assert atr(bars, 14).iloc[-1] == pytest.approx(0.02)


def test_load_mt5_csv(tmp_path):
    f = tmp_path / "EURUSD_H1.csv"
    f.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2024.01.02\t00:00:00\t1.10000\t1.10100\t1.09900\t1.10050\t120\t0\t5\n"
        "2024.01.02\t01:00:00\t1.10050\t1.10200\t1.10000\t1.10150\t98\t0\t5\n"
    )
    bars = load_mt5_csv(f)
    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert str(bars.index[1]) == "2024-01-02 01:00:00"
    assert bars["close"].iat[1] == pytest.approx(1.1015)


def test_load_csv_repairs_bad_rows(tmp_path):
    f = tmp_path / "bars.csv"
    f.write_text(
        "time,open,high,low,close\n"
        "2024-01-01,1.0,1.0,1.0,1.0\n"
        "2024-01-02,1.0,0.9,1.2,1.1\n"
        "2024-01-03,,1,1,1\n"
        "2024-01-04,-1,1,1,1\n"
    )
    bars = load_csv(f)
    assert len(bars) == 2
    assert bars["high"].iat[1] == pytest.approx(1.2)
    assert bars["low"].iat[1] == pytest.approx(0.9)

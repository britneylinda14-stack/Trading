from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from conftest import FixedStrategy, make_bars

from trading_agent.data import policy_rates, with_carry
from trading_agent.engine import Backtester
from trading_agent.instruments import INSTRUMENT_GROUPS, get_instrument
from trading_agent.risk import RiskConfig
from trading_agent.strategies import FxCarry, TimeSeriesMomentum

AUD = get_instrument("AUD_USD")


def test_policy_rates_cover_all_fx_currencies():
    rates = policy_rates()
    assert {"USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "NZD"} <= set(rates.columns)
    assert rates.loc["2008-06-30", "AUD"] > rates.loc["2008-06-30", "USD"]
    assert rates.loc["2014-06-30", "JPY"] < 0.5


def test_carry_uses_previous_day_rates():
    bars = make_bars([0.7] * 5, start="2025-12-09")
    carry = with_carry(bars, AUD)["carry"]
    rates = policy_rates()
    for day, value in carry.items():
        prev = day - pd.Timedelta(days=1)
        assert value == pytest.approx((rates.loc[prev, "AUD"] - rates.loc[prev, "USD"]) / 100)


def test_with_carry_rejects_unknown_currency():
    with pytest.raises(ValueError):
        with_carry(make_bars([1.0] * 3), get_instrument("XAU_USD"))


def _financing(direction, carry):
    bars = make_bars([0.70] * 40).assign(carry=carry)
    t = Backtester(AUD, FixedStrategy([0] + [direction] * 39, 0.02), RiskConfig()).run(bars)
    return t.trades[0].financing


def test_long_high_yielder_earns_carry_and_short_pays_it():
    assert _financing(1, 0.04) < 0 < _financing(1, 0.0)
    assert _financing(-1, 0.04) > _financing(-1, 0.0) > 0


def test_tsmom_only_changes_direction_at_month_start():
    closes = np.r_[np.linspace(1, 2, 80), np.linspace(2, 1, 80)]
    bars = make_bars(closes)
    sig = TimeSeriesMomentum(lookback=20).generate(bars)["direction"]
    changes = sig.index[sig.ne(sig.shift()).to_numpy()][1:]
    assert len(changes) >= 2
    for day in changes:
        assert (day - pd.Timedelta(days=1)).month != day.month, "signal flips on month-start bars"
    assert sig.iloc[60] == 1 and sig.iloc[-1] == -1
    assert sig.iloc[:100].equals(
        TimeSeriesMomentum(lookback=20).generate(bars.iloc[:100])["direction"]
    ), "appending bars must not revise earlier signals"


def test_fx_carry_needs_trend_and_rate_agreement():
    closes = np.r_[np.linspace(1, 1.5, 60), np.linspace(1.5, 1.0, 60)]
    bars = make_bars(closes).assign(carry=0.02)
    sig = FxCarry(trend=20, min_carry=0.01).generate(bars)["direction"]
    assert set(sig.unique()) == {0, 1}, "positive carry must never be shorted"
    assert sig.iloc[50] == 1 and sig.iloc[-1] == 0
    neg = FxCarry(trend=20).generate(bars.assign(carry=-0.02))["direction"]
    assert neg.iloc[50] == 0 and neg.iloc[-1] == -1
    small = FxCarry(trend=20, min_carry=0.03).generate(bars)["direction"]
    assert (small == 0).all()
    with pytest.raises(ValueError):
        FxCarry().generate(make_bars(closes))


def test_instrument_groups():
    assert "NZD_USD" in INSTRUMENT_GROUPS["fx"] and "XAU_USD" not in INSTRUMENT_GROUPS["fx"]
    assert {"ES_USD", "ZN_USD", "XAU_USD", "WTICO_USD"} <= set(INSTRUMENT_GROUPS["futures"])
    assert len(INSTRUMENT_GROUPS["futures"]) >= 20

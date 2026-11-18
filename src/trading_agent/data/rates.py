"""Central-bank policy rates (bundled from the BIS) for modelling FX carry."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import pandas as pd

from ..instruments import Instrument


@lru_cache(maxsize=1)
def policy_rates() -> pd.DataFrame:
    """Daily policy rates in percent, one column per currency, forward-filled."""
    ref = resources.files("trading_agent") / "calendar_data" / "policy_rates.csv"
    with ref.open() as fh:
        df = pd.read_csv(fh, parse_dates=["date"])
    wide = df.pivot_table(index="date", columns="currency", values="rate", aggfunc="last")
    days = pd.date_range(wide.index.min(), pd.Timestamp.today().normalize(), freq="D")
    return wide.reindex(days).ffill()


def with_carry(bars: pd.DataFrame, instrument: Instrument) -> pd.DataFrame:
    """Add a `carry` column: base minus quote policy rate (annual fraction) known at each bar.

    Long positions earn it and shorts pay it on top of the instrument's financing markup.
    """
    rates = policy_rates()
    if instrument.base not in rates or instrument.quote not in rates:
        raise ValueError(f"No policy rates for {instrument.name}")
    diff = (rates[instrument.base] - rates[instrument.quote]) / 100
    day = bars.index.normalize()
    if getattr(day, "tz", None) is not None:
        day = day.tz_localize(None)
    known = diff.shift(1).reindex(day).to_numpy()
    return bars.assign(carry=known)

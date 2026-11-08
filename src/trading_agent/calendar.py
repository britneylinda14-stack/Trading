"""Economic-calendar blackout filter for high-impact USD releases.

Sources:
- FOMC decisions (14:00 ET): bundled CSV scraped from federalreserve.gov
  (refresh with `python scripts/fetch_fomc.py`).
- CPI (08:30 ET): bundled CSV of historical release dates, if present.
- NFP / Employment Situation (08:30 ET): bundled CSV of actual release dates, extended past
  its last date with the BLS scheduling rule (third Friday after the week containing the 12th).
- Refresh CPI/NFP with `python scripts/fetch_bls.py` (needs a browser; BLS blocks scripts).
- Extra events: any CSV with columns `date[,time_et],event[,currency]`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from importlib import resources
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .instruments import Instrument

ET = ZoneInfo("America/New_York")
DEFAULT_TIMES_ET = {"FOMC": time(14, 0), "NFP": time(8, 30), "CPI": time(8, 30)}


@dataclass(frozen=True)
class Event:
    time: pd.Timestamp
    name: str
    currency: str = "USD"


def et_to_utc(day: date, at: time) -> pd.Timestamp:
    local = datetime.combine(day, at, tzinfo=ET)
    return pd.Timestamp(local).tz_convert("UTC").tz_localize(None)


def nfp_release_date(year: int, month: int) -> date:
    """Release date of the Employment Situation report for reference month (year, month)."""
    twelfth = date(year, month, 12)
    saturday = twelfth + timedelta(days=(5 - twelfth.weekday()) % 7)
    return saturday + timedelta(days=6 + 14)


def nfp_events(start_year: int, end_year: int) -> list[Event]:
    events = []
    for year in range(start_year - 1, end_year + 1):
        for month in range(1, 13):
            day = nfp_release_date(year, month)
            if start_year <= day.year <= end_year:
                events.append(Event(et_to_utc(day, DEFAULT_TIMES_ET["NFP"]), "NFP"))
    return events


def events_from_csv(source) -> list[Event]:
    df = pd.read_csv(source)
    events = []
    for row in df.itertuples(index=False):
        name = str(row.event)
        at = DEFAULT_TIMES_ET.get(name, time(8, 30))
        if "time_et" in df.columns and isinstance(row.time_et, str):
            at = time.fromisoformat(row.time_et)
        currency = getattr(row, "currency", "USD") if "currency" in df.columns else "USD"
        events.append(Event(et_to_utc(pd.Timestamp(row.date).date(), at), name, currency))
    return events


def _bundled(name: str) -> list[Event]:
    ref = resources.files("trading_agent") / "calendar_data" / name
    if not ref.is_file():
        return []
    with ref.open() as f:
        return events_from_csv(f)


class EventCalendar:
    def __init__(
        self,
        events: list[Event],
        before: pd.Timedelta | None = None,
        after: pd.Timedelta | None = None,
    ):
        self.events = sorted(events, key=lambda e: e.time)
        self.before = pd.Timedelta(hours=2) if before is None else pd.Timedelta(before)
        self.after = pd.Timedelta(hours=2) if after is None else pd.Timedelta(after)

    @classmethod
    def default(
        cls,
        start_year: int = 2005,
        end_year: int = 2027,
        include: tuple[str, ...] = ("FOMC", "NFP", "CPI"),
        extra_csv: str | Path | None = None,
        **kwargs,
    ) -> EventCalendar:
        events: list[Event] = []
        if "FOMC" in include:
            events += _bundled("fomc.csv")
        if "CPI" in include:
            events += _bundled("cpi.csv")
        if "NFP" in include:
            nfp = _bundled("nfp.csv")
            last = max((e.time for e in nfp), default=pd.Timestamp(f"{start_year - 1}-12-31"))
            events += nfp + [e for e in nfp_events(start_year, end_year) if e.time > last]
        if extra_csv:
            events += events_from_csv(extra_csv)
        return cls(events, **kwargs)

    def names(self) -> set[str]:
        return {e.name for e in self.events}

    def blackout(self, index: pd.DatetimeIndex, instrument: Instrument) -> np.ndarray:
        """True for bars whose time span overlaps an event window for this instrument."""
        currencies = {instrument.base, instrument.quote}
        times = np.array(
            [e.time.to_datetime64() for e in self.events if e.currency in currencies],
            dtype="datetime64[ns]",
        )
        if len(index) == 0 or len(times) == 0:
            return np.zeros(len(index), dtype=bool)
        starts = index.to_numpy(dtype="datetime64[ns]")
        bar = np.median(np.diff(starts)) if len(starts) > 1 else np.timedelta64(1, "D")
        bar = min(bar, np.timedelta64(1, "D"))
        ends = starts + bar
        win_end = times + self.after.to_timedelta64()
        win_start = times - self.before.to_timedelta64()
        k = np.searchsorted(win_end, starts, side="right")
        k_clipped = np.minimum(k, len(times) - 1)
        return (k < len(times)) & (win_start[k_clipped] < ends)

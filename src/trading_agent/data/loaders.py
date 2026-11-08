"""Historical OHLC loaders. All return a DataFrame indexed by UTC-naive timestamps
with lowercase columns: open, high, low, close, volume."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..instruments import Instrument

OHLC = ["open", "high", "low", "close"]
DEFAULT_CACHE = Path("data/cache")


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize columns, drop bad rows and repair inconsistent high/low values."""
    df = df.rename(columns=str.lower)
    if "volume" not in df:
        df["volume"] = 0.0
    df = df[OHLC + ["volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df.dropna(subset=OHLC)
    df = df[(df[OHLC] > 0).all(axis=1)]
    high, low = df[OHLC].max(axis=1), df[OHLC].min(axis=1)
    df["high"], df["low"] = high, low
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    df.index.name = "time"
    return df


def load_yahoo(
    instrument: Instrument,
    start: str,
    end: str | None = None,
    interval: str = "1d",
    cache_dir: Path | None = DEFAULT_CACHE,
) -> pd.DataFrame:
    """Download bars from Yahoo Finance (free; hourly data limited to ~730 days).

    Commodities use front-month futures (e.g. GC=F) as a proxy.
    """
    cache_file = None
    if cache_dir is not None:
        cache_file = Path(cache_dir) / f"{instrument.name}_{interval}_{start}_{end or 'latest'}.csv"
        if cache_file.exists() and end is not None:
            return clean_bars(pd.read_csv(cache_file, index_col=0, parse_dates=True))

    import yfinance as yf

    raw = yf.download(
        instrument.yahoo_symbol,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError(f"No data returned from Yahoo for {instrument.yahoo_symbol}")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    bars = clean_bars(raw)
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        bars.to_csv(cache_file)
    return bars


def load_csv(path: str | Path, time_col: str = "time") -> pd.DataFrame:
    """Load a generic CSV with a time column and open/high/low/close[/volume]."""
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    df[time_col] = pd.to_datetime(df[time_col])
    return clean_bars(df.set_index(time_col))


def load_mt5_csv(path: str | Path) -> pd.DataFrame:
    """Load a MetaTrader 5 history export (View > Symbols > Bars > Export).

    Format: tab-separated, columns like <DATE> <TIME> <OPEN> <HIGH> <LOW> <CLOSE> <TICKVOL> ...
    Daily exports may omit <TIME>.
    """
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip("<>").lower() for c in df.columns]
    stamp = df["date"].astype(str)
    if "time" in df:
        stamp = stamp + " " + df["time"].astype(str)
    df.index = pd.to_datetime(stamp.str.replace(".", "-", regex=False))
    if "volume" not in df:
        df["volume"] = df.get("tickvol", df.get("vol", 0))
    return clean_bars(df)

"""Free multi-year intraday history from Dukascopy's public datafeed.

Bars are built from BID candles: hourly candles come in monthly files, minute candles in
daily files (used for sub-hour intervals, so they are slower to download). Raw files are
cached on disk. Months/days are 0-indexed in the datafeed URL scheme.
"""

from __future__ import annotations

import lzma
import struct
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from ..instruments import Instrument
from .loaders import DEFAULT_CACHE, clean_bars

URL = "https://datafeed.dukascopy.com/datafeed/{symbol}/{path}"
SYMBOLS: dict[str, tuple[str, float]] = {
    "EUR_USD": ("EURUSD", 1e5),
    "GBP_USD": ("GBPUSD", 1e5),
    "AUD_USD": ("AUDUSD", 1e5),
    "USD_JPY": ("USDJPY", 1e3),
    "USD_CHF": ("USDCHF", 1e5),
    "USD_CAD": ("USDCAD", 1e5),
    "XAU_USD": ("XAUUSD", 1e3),
    "XAG_USD": ("XAGUSD", 1e3),
}
RESAMPLE = {"1h": None, "2h": "2h", "4h": "4h", "1d": "1D"}
MINUTE_RESAMPLE = {"1m": None, "5m": "5min", "15m": "15min", "30m": "30min"}
RECORD = struct.Struct(">5if")


def parse_candles(raw: bytes, base: datetime, scale: float) -> pd.DataFrame:
    """Decode a .bi5 candle file: (seconds offset, open, close, low, high, volume) records."""
    data = lzma.decompress(raw) if raw else b""
    rows = [RECORD.unpack_from(data, i) for i in range(0, len(data) - RECORD.size + 1, RECORD.size)]
    df = pd.DataFrame(rows, columns=["t", "open", "close", "low", "high", "volume"])
    df = df[df["volume"] > 0]
    df.index = pd.to_datetime(base) + pd.to_timedelta(df.pop("t"), unit="s")
    df[["open", "close", "low", "high"]] /= scale
    return df


def _fetch(symbol: str, path: str, cache_dir: Path | None, final: bool) -> bytes:
    cache_file = Path(cache_dir) / "dukascopy" / symbol / path if cache_dir else None
    if cache_file is not None and cache_file.exists():
        return cache_file.read_bytes()
    req = urllib.request.Request(
        URL.format(symbol=symbol, path=path), headers={"User-Agent": "Mozilla/5.0"}
    )
    for attempt in range(6):
        try:
            raw = urllib.request.urlopen(req, timeout=60).read()
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raw = b""
                break
            if attempt == 5:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 5:
                raise
        time.sleep(2**attempt)
    if cache_file is not None and final:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(raw)
    return raw


def load_dukascopy(
    instrument: Instrument,
    start: str,
    end: str | None = None,
    interval: str = "1h",
    cache_dir: Path | None = DEFAULT_CACHE,
    workers: int = 4,
) -> pd.DataFrame:
    if instrument.name not in SYMBOLS:
        raise ValueError(f"{instrument.name} is not available from Dukascopy")
    if interval not in RESAMPLE and interval not in MINUTE_RESAMPLE:
        raise ValueError(f"interval must be one of {', '.join([*RESAMPLE, *MINUTE_RESAMPLE])}")
    symbol, scale = SYMBOLS[instrument.name]
    now = datetime.utcnow()
    first = pd.Timestamp(start).to_pydatetime()
    last = min(pd.Timestamp(end).to_pydatetime(), now) if end else now

    if interval in RESAMPLE:
        bases, cur = [], datetime(first.year, first.month, 1)
        while cur <= last:
            bases.append(cur)
            cur = datetime(cur.year + cur.month // 12, cur.month % 12 + 1, 1)
        paths = [f"{b.year}/{b.month - 1:02d}/BID_candles_hour_1.bi5" for b in bases]
        finals = [(b.year, b.month) < (now.year, now.month) for b in bases]
        rule = RESAMPLE[interval]
    else:
        days = pd.date_range(first.date(), last.date(), freq="D").to_pydatetime()
        bases = [d for d in days if d.weekday() != 5]
        paths = [f"{b.year}/{b.month - 1:02d}/{b.day:02d}/BID_candles_min_1.bi5" for b in bases]
        finals = [b + timedelta(days=1) < now for b in bases]
        rule = MINUTE_RESAMPLE[interval]

    with ThreadPoolExecutor(workers) as pool:
        raws = list(
            pool.map(
                lambda a: _fetch(symbol, a[0], cache_dir, a[1]), zip(paths, finals, strict=True)
            )
        )
    frames = [parse_candles(raw, base, scale) for raw, base in zip(raws, bases, strict=True) if raw]
    if not frames:
        raise RuntimeError(f"No Dukascopy data for {symbol} between {start} and {end}")
    bars = pd.concat(frames)
    if rule:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        bars = bars.resample(rule).agg(agg).dropna(subset=["open"])
    bars = bars[(bars.index >= first) & (bars.index <= last)]
    return clean_bars(bars)

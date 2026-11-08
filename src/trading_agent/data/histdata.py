"""Free multi-year 1-minute FX/metals history from HistData.com (BID M1 bars).

Complete years download as one zip per year, the current year as one zip per month. Timestamps
in the files are EST without daylight saving (UTC-5) and are converted to UTC. Zips are cached.
"""

from __future__ import annotations

import io
import re
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..instruments import Instrument
from .loaders import DEFAULT_CACHE, clean_bars

PAGE = "https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/{pair}/{period}"
GET = "https://www.histdata.com/get.php"
HEADERS = {"User-Agent": "Mozilla/5.0"}
FORM_FIELDS = ("tk", "date", "datemonth", "platform", "timeframe", "fxpair")
PAIRS = {
    "EUR_USD": "eurusd",
    "GBP_USD": "gbpusd",
    "AUD_USD": "audusd",
    "USD_JPY": "usdjpy",
    "USD_CHF": "usdchf",
    "USD_CAD": "usdcad",
    "XAU_USD": "xauusd",
    "XAG_USD": "xagusd",
}
RULES = {
    "1m": None,
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1D",
}


def parse_m1(raw: bytes) -> pd.DataFrame:
    """Decode a HistData ASCII M1 zip: `YYYYMMDD HHMMSS;open;high;low;close;volume` rows."""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        df = pd.read_csv(
            zf.open(name),
            sep=";",
            header=None,
            names=["time", "open", "high", "low", "close", "volume"],
        )
    df.index = pd.to_datetime(df.pop("time"), format="%Y%m%d %H%M%S") + pd.Timedelta(hours=5)
    return df


def _fetch(pair: str, period: str, cache_dir: Path | None, final: bool) -> bytes:
    path = cache_dir / "histdata" / f"{pair}_{period.replace('/', '_')}.zip" if cache_dir else None
    if path is not None and path.exists():
        return path.read_bytes()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    page = PAGE.format(pair=pair, period=period)
    html = opener.open(urllib.request.Request(page, headers=HEADERS), timeout=60).read().decode()
    form = dict(re.findall(r'name="(\w+)" id="\w+" value="([^"]*)"', html))
    if not all(f in form for f in FORM_FIELDS):
        return b""
    body = urllib.parse.urlencode({f: form[f] for f in FORM_FIELDS}).encode()
    req = urllib.request.Request(GET, data=body, headers={**HEADERS, "Referer": page})
    raw = opener.open(req, timeout=180).read()
    if not raw.startswith(b"PK"):
        return b""
    if path is not None and final:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return raw


def load_histdata(
    instrument: Instrument,
    start: str,
    end: str | None = None,
    interval: str = "1h",
    cache_dir: Path | None = DEFAULT_CACHE,
) -> pd.DataFrame:
    if instrument.name not in PAIRS:
        raise ValueError(f"{instrument.name} is not available from HistData")
    if interval not in RULES:
        raise ValueError(f"interval must be one of {', '.join(RULES)}")
    pair, now = PAIRS[instrument.name], datetime.utcnow()
    first = pd.Timestamp(start).to_pydatetime()
    last = min(pd.Timestamp(end).to_pydatetime(), now) if end else now

    frames = []
    for year in range(first.year, last.year + 1):
        if year < now.year:
            periods = [(str(year), True)]
        else:
            months = range(1, (last.month if year == last.year else 12) + 1)
            periods = [(f"{year}/{m}", m < now.month) for m in months]
        for period, final in periods:
            raw = _fetch(pair, period, cache_dir, final)
            if raw:
                frames.append(parse_m1(raw))
    if not frames:
        raise RuntimeError(f"No HistData data for {pair} between {start} and {end}")
    bars = pd.concat(frames)
    if RULES[interval]:
        agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        bars = bars.resample(RULES[interval]).agg(agg).dropna(subset=["open"])
    bars = bars[(bars.index >= first) & (bars.index <= last)]
    return clean_bars(bars)

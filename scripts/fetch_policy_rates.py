"""Refresh calendar_data/policy_rates.csv: central-bank policy rates from the BIS (WS_CBPOL).

Only the dates where a rate changes are kept. Used to model FX carry (rate differentials).
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

import pandas as pd

AREAS = {
    "US": "USD",
    "XM": "EUR",
    "JP": "JPY",
    "GB": "GBP",
    "AU": "AUD",
    "CA": "CAD",
    "CH": "CHF",
    "NZ": "NZD",
}
URL = "https://stats.bis.org/api/v1/data/WS_CBPOL/D.{areas}/all?format=csv&startPeriod=2000-01-01"
OUT = Path(__file__).resolve().parents[1] / "src/trading_agent/calendar_data/policy_rates.csv"


def main() -> None:
    frames = []
    for area in AREAS:
        req = urllib.request.Request(URL.format(areas=area), headers={"User-Agent": "Mozilla/5.0"})
        body = urllib.request.urlopen(req, timeout=300).read()
        frames.append(pd.read_csv(io.BytesIO(body), low_memory=False))
    raw = pd.concat(frames)
    raw = raw[raw["REF_AREA"].isin(AREAS)].dropna(subset=["OBS_VALUE"])
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["TIME_PERIOD"]),
            "currency": raw["REF_AREA"].map(AREAS),
            "rate": raw["OBS_VALUE"].astype(float),
        }
    ).sort_values(["currency", "date"])
    df = df[df.groupby("currency")["rate"].diff().ne(0)]
    df.to_csv(OUT, index=False, date_format="%Y-%m-%d")
    print(f"wrote {len(df)} rate changes to {OUT}")
    print(
        df.groupby("currency").agg(first=("date", "min"), last=("date", "max"), n=("rate", "size"))
    )


if __name__ == "__main__":
    main()

"""Scrape scheduled FOMC meeting decision dates from federalreserve.gov into a CSV.

Usage: python scripts/fetch_fomc.py [first_year]
"""

from __future__ import annotations

import csv
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://www.federalreserve.gov/monetarypolicy"
OUT = Path(__file__).resolve().parents[1] / "src/trading_agent/calendar_data/fomc.csv"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/130.0 Safari/537.36"}
MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def decision_date(year: int, month_text: str, day_text: str) -> date:
    """'April/May' + '30-1' -> May 1. 'June' + '16-17*' -> June 17."""
    month = MONTHS[month_text.split("/")[-1].strip()[:3].lower()]
    day = int(re.findall(r"\d+", day_text)[-1])
    return date(year, month, day)


def parse_current(html: str) -> set[date]:
    dates = set()
    token = re.compile(
        r"(?P<year>\d{4}) FOMC Meetings"
        r"|fomc-meeting__month[^>]*><strong>(?P<month>[^<]+)</strong>"
        r"|fomc-meeting__date[^>]*>(?P<day>[^<]+)<"
    )
    year = month = None
    for m in token.finditer(html):
        if m["year"]:
            year = int(m["year"])
        elif m["month"]:
            month = m["month"]
        elif m["day"] and year and month:
            if re.search(r"\d", m["day"]) and "notation" not in m["day"].lower():
                dates.add(decision_date(year, month, m["day"]))
            month = None
    return dates


def parse_historical(html: str) -> set[date]:
    pattern = re.compile(
        r"<h5[^>]*>\s*([A-Za-z/]+)\s+(\d+)(?:\s*-\s*(?:([A-Za-z]+)\s+)?(\d+))?\s+Meeting\s+-\s+(\d{4})"
    )
    dates = set()
    for month, day1, month2, day2, year in pattern.findall(html):
        dates.add(decision_date(int(year), month2 or month, day2 or day1))
    return dates


def main() -> None:
    first_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2005
    dates = parse_current(fetch(f"{BASE}/fomccalendars.htm"))
    covered = {d.year for d in dates}
    for year in range(first_year, min(covered)):
        try:
            dates |= parse_historical(fetch(f"{BASE}/fomchistorical{year}.htm"))
        except Exception as exc:  # noqa: BLE001
            print(f"warning: {year}: {exc}", file=sys.stderr)
    dates = sorted(d for d in dates if d.year >= first_year)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "event"])
        writer.writerows([d.isoformat(), "FOMC"] for d in dates)
    print(f"wrote {len(dates)} FOMC dates ({dates[0]} .. {dates[-1]}) to {OUT}")


if __name__ == "__main__":
    main()

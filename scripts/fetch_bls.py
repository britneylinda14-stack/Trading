"""Build CPI and NFP (Employment Situation) release-date CSVs from BLS archive pages.

BLS blocks non-browser HTTP clients, so this drives a running Chrome over CDP:
    pip install playwright
    python scripts/fetch_bls.py [--cdp http://localhost:9222]
Past release dates are parsed from archive file names like cpi_10142026.htm (MMDDYYYY);
upcoming ones from the BLS release schedule tables ("Nov. 10, 2026").
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
from datetime import date
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "src/trading_agent/calendar_data"
PAGES = {
    "CPI": ("cpi", "cpi.csv"),
    "NFP": ("empsit", "nfp.csv"),
}
ARCHIVE_URL = "https://www.bls.gov/bls/news-release/{}.htm"
SCHEDULE_URL = "https://www.bls.gov/schedule/news_release/{}.htm"
MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}


def parse_schedule(html: str) -> set[date]:
    pattern = r"<td[^>]*>\s*([A-Z][a-z]{2})\.? (\d{1,2}), (\d{4})\s*</td>"
    return {date(int(y), MONTHS[m], int(d)) for m, d, y in re.findall(pattern, html)}


def parse_dates(html: str, prefix: str) -> list[date]:
    found = {
        date(int(y), int(m), int(d))
        for m, d, y in re.findall(rf"{prefix}_(\d{{2}})(\d{{2}})(\d{{4}})\.(?:htm|txt|pdf)", html)
    }
    return sorted(found)


async def fetch_all(cdp: str) -> dict[str, str]:
    from playwright.async_api import async_playwright

    out = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp)
        page = await browser.contexts[0].new_page()
        for name, (prefix, _) in PAGES.items():
            html = []
            for url in (ARCHIVE_URL.format(prefix), SCHEDULE_URL.format(prefix)):
                await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(2_000)
                html.append(await page.content())
            out[name] = html
        await page.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://localhost:9222")
    args = ap.parse_args()
    pages = asyncio.run(fetch_all(args.cdp))
    for name, (prefix, filename) in PAGES.items():
        archive, schedule = pages[name]
        dates = sorted(set(parse_dates(archive, prefix)) | parse_schedule(schedule))
        with (OUT_DIR / filename).open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "event"])
            writer.writerows([d.isoformat(), name] for d in dates)
        print(f"{name}: {len(dates)} release dates ({dates[0]} .. {dates[-1]}) -> {filename}")


if __name__ == "__main__":
    main()

"""Build CPI and NFP (Employment Situation) release-date CSVs from BLS archive pages.

BLS blocks non-browser HTTP clients, so this drives a running Chrome over CDP:
    pip install playwright
    python scripts/fetch_bls.py [--cdp http://localhost:9222]
Release dates are parsed from archive file names like cpi_10142026.htm (MMDDYYYY).
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
    "CPI": ("https://www.bls.gov/bls/news-release/cpi.htm", "cpi", "cpi.csv"),
    "NFP": ("https://www.bls.gov/bls/news-release/empsit.htm", "empsit", "nfp.csv"),
}


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
        for name, (url, _, _) in PAGES.items():
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(2_000)
            out[name] = await page.content()
        await page.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://localhost:9222")
    args = ap.parse_args()
    pages = asyncio.run(fetch_all(args.cdp))
    for name, (_, prefix, filename) in PAGES.items():
        dates = parse_dates(pages[name], prefix)
        with (OUT_DIR / filename).open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["date", "event"])
            writer.writerows([d.isoformat(), name] for d in dates)
        print(f"{name}: {len(dates)} release dates ({dates[0]} .. {dates[-1]}) -> {filename}")


if __name__ == "__main__":
    main()

"""Instrument specs. Names follow OANDA's convention (BASE_QUOTE).

Spreads and financing rates are rough retail estimates; tune them to your broker.
Leverage caps follow US (CFTC/NFA) retail limits: 50:1 on major FX pairs. Commodities
are traded in the US as futures, so their caps approximate typical futures margin.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    name: str
    yahoo_symbol: str
    pip_size: float
    spread: float
    max_leverage: float
    financing_rate: float = 0.015
    kind: str = "forex"

    @property
    def base(self) -> str:
        return self.name.split("_")[0]

    @property
    def quote(self) -> str:
        return self.name.split("_")[1]

    def _check_usd(self) -> None:
        if "USD" not in (self.base, self.quote):
            raise ValueError(f"{self.name}: only USD-denominated instruments are supported")

    def to_usd(self, quote_amount: float, price: float) -> float:
        """Convert an amount in the quote currency to USD at `price`."""
        self._check_usd()
        return quote_amount if self.quote == "USD" else quote_amount / price

    def notional_usd(self, units: float, price: float) -> float:
        self._check_usd()
        return abs(units) * price if self.quote == "USD" else abs(units)


INSTRUMENTS: dict[str, Instrument] = {
    i.name: i
    for i in [
        Instrument("EUR_USD", "EURUSD=X", 0.0001, 0.00014, 50),
        Instrument("GBP_USD", "GBPUSD=X", 0.0001, 0.00020, 50),
        Instrument("AUD_USD", "AUDUSD=X", 0.0001, 0.00016, 50),
        Instrument("USD_JPY", "JPY=X", 0.01, 0.014, 50),
        Instrument("USD_CHF", "CHF=X", 0.0001, 0.00018, 50),
        Instrument("USD_CAD", "CAD=X", 0.0001, 0.00022, 50),
        Instrument("XAU_USD", "GC=F", 0.01, 0.40, 20, 0.0, "future"),
        Instrument("XAG_USD", "SI=F", 0.001, 0.03, 10, 0.0, "future"),
        Instrument("WTICO_USD", "CL=F", 0.01, 0.04, 10, 0.0, "future"),
    ]
}


def get_instrument(name: str) -> Instrument:
    try:
        return INSTRUMENTS[name.upper()]
    except KeyError:
        raise KeyError(
            f"Unknown instrument {name!r}. Available: {', '.join(INSTRUMENTS)}"
        ) from None

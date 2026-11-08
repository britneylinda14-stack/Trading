from .base import Strategy
from .trend import DonchianBreakout, EmaCross

STRATEGIES: dict[str, type[Strategy]] = {
    EmaCross.name: EmaCross,
    DonchianBreakout.name: DonchianBreakout,
}


def get_strategy(name: str, **params) -> Strategy:
    try:
        return STRATEGIES[name](**params)
    except KeyError:
        raise KeyError(f"Unknown strategy {name!r}. Available: {', '.join(STRATEGIES)}") from None


__all__ = ["STRATEGIES", "DonchianBreakout", "EmaCross", "Strategy", "get_strategy"]

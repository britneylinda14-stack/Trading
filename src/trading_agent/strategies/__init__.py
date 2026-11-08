from .base import Strategy
from .pullback import AtmPullback
from .reversion import MeanReversion, SessionBreakout
from .trend import DonchianBreakout, EmaCross

STRATEGIES: dict[str, type[Strategy]] = {
    EmaCross.name: EmaCross,
    DonchianBreakout.name: DonchianBreakout,
    MeanReversion.name: MeanReversion,
    SessionBreakout.name: SessionBreakout,
    AtmPullback.name: AtmPullback,
}


def get_strategy(name: str, **params) -> Strategy:
    try:
        return STRATEGIES[name](**params)
    except KeyError:
        raise KeyError(f"Unknown strategy {name!r}. Available: {', '.join(STRATEGIES)}") from None


__all__ = [
    "STRATEGIES",
    "AtmPullback",
    "DonchianBreakout",
    "EmaCross",
    "MeanReversion",
    "SessionBreakout",
    "Strategy",
    "get_strategy",
]

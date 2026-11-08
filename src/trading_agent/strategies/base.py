from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """A strategy maps bars to a target direction and a stop distance per bar.

    `generate` must return a DataFrame on the same index as `bars` with:
      - direction: +1 long, -1 short, 0 flat (decided at the bar's close)
      - stop_distance: positive stop-loss distance in price units

    The engine acts on a bar's signal at the NEXT bar's open, so only use data
    up to and including the current bar.
    """

    name: str = "base"

    @abstractmethod
    def generate(self, bars: pd.DataFrame) -> pd.DataFrame: ...

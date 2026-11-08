from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskConfig:
    """Hard risk limits enforced by the engine.

    - risk_per_trade: fraction of equity lost if the stop is hit (spread included)
    - max_daily_loss: flatten and stop trading for the rest of the day past this drawdown
      from the day's starting equity
    - max_drawdown: kill switch; flatten and stop trading for good past this drawdown from peak
    - max_open_risk: cap on the summed initial risk of all open trades (portfolio budget)
    - max_leverage: optional override; the effective cap is min(this, instrument cap)
    """

    initial_equity: float = 10_000.0
    risk_per_trade: float = 0.01
    max_daily_loss: float = 0.03
    max_drawdown: float = 0.25
    max_open_risk: float = 0.05
    max_leverage: float | None = None
    take_profit_r: float | None = None

    def __post_init__(self) -> None:
        for field in ("risk_per_trade", "max_daily_loss", "max_drawdown", "max_open_risk"):
            value = getattr(self, field)
            if not 0 < value < 1:
                raise ValueError(f"{field} must be between 0 and 1, got {value}")
        if self.max_open_risk < self.risk_per_trade:
            raise ValueError("max_open_risk must be >= risk_per_trade")
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")

"""Position sizing and account-level guards. Shared by backtest and any live broker."""

from __future__ import annotations

import math
from dataclasses import dataclass


def pip_size(symbol: str) -> float:
    return 0.01 if "JPY" in symbol.upper() else 0.0001


@dataclass
class RiskConfig:
    risk_pct: float = 1.0            # % of equity lost if the stop is hit
    max_leverage: float = 25.0       # Japanese retail cap
    lot_step: int = 1000             # smallest tradable increment (units)
    max_drawdown_pct: float = 20.0   # halt trading once equity falls this far from its peak
    quote_to_account: float = 1.0    # 1 quote-currency unit in account currency (USDJPY w/ JPY account = 1)


def size_units(equity: float, price: float, stop: float, cfg: RiskConfig) -> int:
    """Units so that hitting `stop` (price distance) loses risk_pct of equity."""
    if equity <= 0 or stop <= 0 or price <= 0:
        return 0
    by_risk = equity * cfg.risk_pct / 100 / (stop * cfg.quote_to_account)
    by_leverage = equity * cfg.max_leverage / (price * cfg.quote_to_account)
    units = math.floor(min(by_risk, by_leverage) / cfg.lot_step) * cfg.lot_step
    return max(units, 0)


class DrawdownGuard:
    """Trips permanently once equity drops max_drawdown_pct below its peak."""

    def __init__(self, max_drawdown_pct: float) -> None:
        self.limit = max_drawdown_pct
        self.peak = 0.0
        self.tripped = False

    def update(self, equity: float) -> bool:
        self.peak = max(self.peak, equity)
        if self.limit > 0 and self.peak > 0 and equity < self.peak * (1 - self.limit / 100):
            self.tripped = True
        return self.tripped

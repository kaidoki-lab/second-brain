"""Position sizing and account-level guards. Shared by backtest and any live broker."""

from __future__ import annotations

import math
from dataclasses import dataclass


CRYPTO = ("BTC", "XBT", "ETH", "XRP", "LTC", "BCH", "SOL")


def is_crypto(symbol: str) -> bool:
    return symbol.upper().startswith(CRYPTO)


def pip_size(symbol: str) -> float:
    """Unit for --spread. Crypto has no pips, so its spread is quoted in price (e.g. JPY)."""
    if is_crypto(symbol):
        return 1.0
    return 0.01 if "JPY" in symbol.upper() else 0.0001


def tidy(units: float) -> float:
    """Round away float noise; whole amounts (all FX sizes) come back as int."""
    units = round(units, 10)
    return int(units) if float(units).is_integer() else units


def unit_label(symbol: str) -> str:
    return "" if is_crypto(symbol) else "通貨"


def defaults_for(symbol: str) -> dict[str, float]:
    """Sizing defaults that differ between FX and crypto (Japanese retail rules)."""
    if is_crypto(symbol):
        return {"max_leverage": 2.0, "lot_step": 0.001}
    return {"max_leverage": 25.0, "lot_step": 1000}


@dataclass
class RiskConfig:
    risk_pct: float = 1.0            # % of equity lost if the stop is hit
    max_leverage: float = 25.0       # Japanese retail cap
    lot_step: float = 1000           # smallest tradable increment (FX: currency units, crypto: coins)
    max_drawdown_pct: float = 20.0   # halt trading once equity falls this far from its peak
    quote_to_account: float = 1.0    # 1 quote-currency unit in account currency (USDJPY w/ JPY account = 1)
    long_only: bool = False          # spot crypto cannot be sold short: sell signals just go flat


def size_units(equity: float, price: float, stop: float, cfg: RiskConfig) -> float:
    """Units so that hitting `stop` (price distance) loses risk_pct of equity."""
    if equity <= 0 or stop <= 0 or price <= 0:
        return 0
    by_risk = equity * cfg.risk_pct / 100 / (stop * cfg.quote_to_account)
    by_leverage = equity * cfg.max_leverage / (price * cfg.quote_to_account)
    steps = math.floor(min(by_risk, by_leverage) / cfg.lot_step + 1e-9)
    return tidy(max(steps, 0) * cfg.lot_step)


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

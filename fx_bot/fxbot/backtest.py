"""Drive a strategy bar by bar through a broker, applying risk rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from .broker import Broker, PaperBroker, SwapRates, Trade
from .data import Bar
from .risk import DrawdownGuard, RiskConfig, size_units
from .strategy import Strategy


@dataclass
class Result:
    strategy: str
    initial_equity: float
    trades: list[Trade]
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    halted_at: datetime | None = None

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.initial_equity


def step(broker: Broker, strategy: Strategy, bars: Sequence[Bar], i: int, risk: RiskConfig) -> None:
    """Ask the strategy about bar i and turn its answer into orders.

    The same function is meant to drive a live broker: call it once per
    closed bar with the bars received so far.
    """
    decision = strategy.decide(bars, i)
    if decision is None:
        return
    pos = broker.position()
    held = pos.direction if pos else 0
    if decision.direction == held:
        return
    if pos is not None:
        broker.close("signal")
    if decision.direction != 0 and decision.stop:
        units = size_units(broker.equity(), bars[i].close, decision.stop, risk)
        broker.open(decision.direction, units, decision.stop, decision.take)


def run(
    bars: Sequence[Bar],
    strategy: Strategy,
    risk: RiskConfig | None = None,
    initial_equity: float = 1_000_000,
    spread: float = 0.0,
    slippage: float = 0.0,
    swap: SwapRates | None = None,
) -> Result:
    risk = risk or RiskConfig()
    broker = PaperBroker(initial_equity, spread, risk.quote_to_account, slippage, swap)
    guard = DrawdownGuard(risk.max_drawdown_pct)
    result = Result(strategy.describe(), initial_equity, broker.trades)

    for i, bar in enumerate(bars):
        broker.on_bar(bar)
        equity = broker.equity()
        result.equity_curve.append((bar.time, equity))
        if guard.update(equity):
            result.halted_at = bar.time
            break
        step(broker, strategy, bars, i, risk)

    broker.close_now("halt" if result.halted_at else "end")
    if result.equity_curve:
        result.equity_curve[-1] = (result.equity_curve[-1][0], broker.cash)
    return result

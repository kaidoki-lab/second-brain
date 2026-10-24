"""Broker interface and the paper (simulated) broker.

A real broker (MT5, OANDA, ...) is added later by implementing `Broker`;
strategy and risk code stay unchanged.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from .data import Bar


@dataclass
class Position:
    direction: int
    units: int
    entry_time: datetime
    entry_price: float
    stop_price: float | None
    take_price: float | None


@dataclass(frozen=True)
class Trade:
    direction: int
    units: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl: float
    reason: str        # signal / stop / take / halt / end


class Broker(ABC):
    @abstractmethod
    def equity(self) -> float: ...

    @abstractmethod
    def position(self) -> Position | None: ...

    @abstractmethod
    def open(self, direction: int, units: int, stop: float | None, take: float | None) -> None:
        """Market order. `stop` / `take` are distances from the fill price."""

    @abstractmethod
    def close(self, reason: str = "signal") -> None: ...


class PaperBroker(Broker):
    """Simulated fills on BID bars with a fixed spread.

    Orders placed after bar i's close fill at bar i+1's open. Inside a bar,
    if both the stop and the target could have been hit, the stop is assumed
    (pessimistic). Gaps through a stop fill at the open, not at the stop.
    """

    def __init__(self, initial_equity: float, spread: float, quote_to_account: float = 1.0) -> None:
        self.cash = initial_equity
        self.spread = spread
        self.q2a = quote_to_account
        self.trades: list[Trade] = []
        self._pos: Position | None = None
        self._pending: list[tuple] = []
        self._last: Bar | None = None

    # -- Broker API ---------------------------------------------------------
    def equity(self) -> float:
        if self._pos is None or self._last is None:
            return self.cash
        return self.cash + self._pnl(self._pos, self._exit_price(self._pos.direction, self._last.close))

    def position(self) -> Position | None:
        return self._pos

    def open(self, direction: int, units: int, stop: float | None, take: float | None) -> None:
        self._pending.append(("open", direction, units, stop, take))

    def close(self, reason: str = "signal") -> None:
        self._pending.append(("close", reason))

    # -- simulation ---------------------------------------------------------
    def on_bar(self, bar: Bar) -> None:
        """Advance one bar: fill pending orders at the open, then run stops/targets."""
        pending, self._pending = self._pending, []
        for order in pending:
            if order[0] == "close":
                if self._pos is not None:
                    self._exit(bar.time, self._exit_price(self._pos.direction, bar.open), order[1])
            else:
                _, direction, units, stop, take = order
                if self._pos is None and units > 0:
                    fill = bar.open + self.spread if direction > 0 else bar.open
                    self._pos = Position(
                        direction, units, bar.time, fill,
                        fill - direction * stop if stop else None,
                        fill + direction * take if take else None,
                    )
        if self._pos is not None:
            self._check_exits(bar)
        self._last = bar

    def close_now(self, reason: str = "end") -> None:
        """Flatten at the last seen close (used when the data runs out)."""
        self._pending = []
        if self._pos is not None and self._last is not None:
            self._exit(self._last.time, self._exit_price(self._pos.direction, self._last.close), reason)

    # -- internals ----------------------------------------------------------
    def _exit_price(self, direction: int, bid: float) -> float:
        # long sells at bid, short buys back at ask
        return bid if direction > 0 else bid + self.spread

    def _pnl(self, pos: Position, exit_price: float) -> float:
        return pos.direction * (exit_price - pos.entry_price) * pos.units * self.q2a

    def _exit(self, when: datetime, price: float, reason: str) -> None:
        pos = self._pos
        assert pos is not None
        pnl = self._pnl(pos, price)
        self.cash += pnl
        self.trades.append(Trade(pos.direction, pos.units, pos.entry_time, pos.entry_price, when, price, pnl, reason))
        self._pos = None

    def _check_exits(self, bar: Bar) -> None:
        pos = self._pos
        assert pos is not None
        d = pos.direction
        # prices at which this position would close, expressed on its exit side
        o, hi, lo = (self._exit_price(d, x) for x in (bar.open, bar.high, bar.low))
        worst, best = (lo, hi) if d > 0 else (hi, lo)
        if pos.stop_price is not None and d * (worst - pos.stop_price) <= 0:
            gap = d * (o - pos.stop_price) <= 0
            self._exit(bar.time, o if gap else pos.stop_price, "stop")
        elif pos.take_price is not None and d * (best - pos.take_price) >= 0:
            gap = d * (o - pos.take_price) >= 0
            self._exit(bar.time, o if gap else pos.take_price, "take")

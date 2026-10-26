"""Line up live trades against the backtest of the same bars.

Live entries happen a few seconds after a bar closes; the backtest enters at
the next bar's open. So a live trade and a backtest trade are "the same" when
they share a direction and start within `tolerance` of each other.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .broker import Trade


@dataclass(frozen=True)
class Pair:
    live: Trade | None
    test: Trade | None

    @property
    def time(self):
        return (self.live or self.test).entry_time

    def entry_gap(self, pip: float) -> float | None:
        """How much worse (pips) the live entry was than the backtest's. Positive = live paid more."""
        if self.live is None or self.test is None:
            return None
        return self.live.direction * (self.live.entry_price - self.test.entry_price) / pip

    def exit_gap(self, pip: float) -> float | None:
        """How much worse (pips) the live exit was than the backtest's. Positive = live got less."""
        if self.live is None or self.test is None:
            return None
        return self.live.direction * (self.test.exit_price - self.live.exit_price) / pip


def match(live: list[Trade], test: list[Trade], tolerance: timedelta = timedelta(hours=1)) -> list[Pair]:
    pairs: list[Pair] = []
    unused = list(test)
    for lt in sorted(live, key=lambda t: t.entry_time):
        hit = next((t for t in unused if t.direction == lt.direction
                    and abs(t.entry_time - lt.entry_time) < tolerance), None)
        if hit is not None:
            unused.remove(hit)
        pairs.append(Pair(lt, hit))
    pairs += [Pair(None, t) for t in unused]
    return sorted(pairs, key=lambda p: p.time)


def pips(t: Trade, pip: float) -> float:
    return t.direction * (t.exit_price - t.entry_price) / pip

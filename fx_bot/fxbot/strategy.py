"""Strategies decide a target direction; they never place orders themselves.

`decide(bars, i)` may read only bars[0..i]. The decision is executed at the
NEXT bar's open, so a strategy can never trade on a price it hasn't seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .data import Bar
from .indicators import atr, highest, lowest, sma


@dataclass(frozen=True)
class Decision:
    direction: int               # +1 long, -1 short, 0 flat
    stop: float | None = None    # stop-loss distance in price units
    take: float | None = None    # take-profit distance in price units


class Strategy:
    name = "base"
    summary = ""
    params: dict[str, float] = {}

    def __init__(self, **params: float) -> None:
        unknown = set(params) - set(self.params)
        if unknown:
            raise ValueError(f"{self.name}: 未知のパラメータ {sorted(unknown)} (使えるもの: {sorted(self.params)})")
        self.p = {**self.params, **params}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        """Return the wanted position, or None to keep whatever is held."""
        raise NotImplementedError

    def _exits(self, bars: Sequence[Bar], i: int) -> tuple[float, float | None] | None:
        a = atr(bars, i, int(self.p["atr"]))
        if not a:
            return None
        take = a * self.p["tp_atr"] if self.p["tp_atr"] > 0 else None
        return a * self.p["sl_atr"], take

    def describe(self) -> str:
        args = ",".join(f"{k}={_fmt(v)}" for k, v in self.p.items())
        return f"{self.name}({args})"


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


_EXIT_PARAMS = {"atr": 14, "sl_atr": 2.0, "tp_atr": 0.0}


class MACross(Strategy):
    """Long while fast SMA > slow SMA, short while below. Always in the market."""

    name = "ma_cross"
    summary = "短期SMAが長期SMAより上なら買い、下なら売り（常にポジションを持つ）"
    params = {"fast": 20, "slow": 80, **_EXIT_PARAMS}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        fast = sma(bars, i, int(self.p["fast"]))
        slow = sma(bars, i, int(self.p["slow"]))
        exits = self._exits(bars, i)
        if fast is None or slow is None or exits is None or fast == slow:
            return None
        return Decision(1 if fast > slow else -1, *exits)


class Breakout(Strategy):
    """Donchian breakout: enter when the close breaks the prior n-bar range."""

    name = "breakout"
    summary = "直近n本の高値/安値を終値で抜けたらその方向に入る"
    params = {"n": 50, **_EXIT_PARAMS}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        n = int(self.p["n"])
        exits = self._exits(bars, i)
        if i < n or exits is None:
            return None
        close = bars[i].close
        if close > highest(bars, i - n, i):
            return Decision(1, *exits)
        if close < lowest(bars, i - n, i):
            return Decision(-1, *exits)
        return None


STRATEGIES: dict[str, type[Strategy]] = {cls.name: cls for cls in (MACross, Breakout)}


def parse_params(text: str | None) -> dict[str, float]:
    """`"fast=10,slow=40"` -> {"fast": 10.0, "slow": 40.0}"""
    out: dict[str, float] = {}
    for part in (text or "").split(","):
        if not part.strip():
            continue
        key, _, value = part.partition("=")
        if not value:
            raise ValueError(f"パラメータは key=value 形式で指定してください: {part!r}")
        out[key.strip()] = float(value)
    return out


def build(name: str, params: dict[str, float] | None = None) -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(f"未知の戦略 {name!r} (使えるもの: {', '.join(STRATEGIES)})")
    return STRATEGIES[name](**(params or {}))

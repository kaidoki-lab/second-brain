"""Indicators evaluated at bar index `i`, using only bars[..i] (no lookahead)."""

from __future__ import annotations

from typing import Sequence

from .data import Bar


def sma(bars: Sequence[Bar], i: int, n: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(b.close for b in bars[i - n + 1:i + 1]) / n


def atr(bars: Sequence[Bar], i: int, n: int) -> float | None:
    """Simple-average true range over the last n bars."""
    if i < n:
        return None
    total = 0.0
    for k in range(i - n + 1, i + 1):
        b, prev = bars[k], bars[k - 1].close
        total += max(b.high - b.low, abs(b.high - prev), abs(b.low - prev))
    return total / n


def highest(bars: Sequence[Bar], start: int, end: int) -> float:
    return max(b.high for b in bars[start:end])


def lowest(bars: Sequence[Bar], start: int, end: int) -> float:
    return min(b.low for b in bars[start:end])

"""Indicators evaluated at bar index `i`, using only bars[..i] (no lookahead)."""

from __future__ import annotations

from typing import Sequence

from .data import Bar


def sma(bars: Sequence[Bar], i: int, n: int) -> float | None:
    if i + 1 < n:
        return None
    return sum(b.close for b in bars[i - n + 1:i + 1]) / n


def stdev(bars: Sequence[Bar], i: int, n: int) -> float | None:
    """Population standard deviation of the last n closes."""
    mean = sma(bars, i, n)
    if mean is None:
        return None
    return (sum((b.close - mean) ** 2 for b in bars[i - n + 1:i + 1]) / n) ** 0.5


def rsi(bars: Sequence[Bar], i: int, n: int) -> float | None:
    """RSI from simple averages of gains/losses over the last n changes (Cutler)."""
    if i < n:
        return None
    gain = loss = 0.0
    for k in range(i - n + 1, i + 1):
        d = bars[k].close - bars[k - 1].close
        if d > 0:
            gain += d
        else:
            loss -= d
    if gain + loss == 0:
        return 50.0
    return 100 * gain / (gain + loss)


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

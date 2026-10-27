"""Indicators evaluated at bar index `i`, using only bars[..i] (no lookahead).

Recursive ones (EMA, MACD, ADX, Parabolic SAR) are computed as a whole series
once per bars list and cached; each value still depends only on earlier bars.
"""

from __future__ import annotations

from typing import Callable, Sequence

from .data import Bar

_CACHE: list[tuple[Sequence[Bar], int, dict]] = []   # (bars, len, {key: series}); holds the list so its id can't be reused
_CACHE_SIZE = 4


def _series(bars: Sequence[Bar], key: tuple, make: Callable[[Sequence[Bar]], list]) -> list:
    for b, n, store in _CACHE:
        if b is bars and n == len(bars):
            break
    else:
        store = {}
        _CACHE.insert(0, (bars, len(bars), store))
        del _CACHE[_CACHE_SIZE:]
    if key not in store:
        store[key] = make(bars)
    return store[key]


def _ema_of(values: list[float | None], n: int) -> list[float | None]:
    """EMA (alpha 2/(n+1)) seeded with the SMA of the first n non-None values."""
    out: list[float | None] = [None] * len(values)
    alpha, seed, cur = 2 / (n + 1), [], None
    for k, v in enumerate(values):
        if v is None:
            continue
        if cur is None:
            seed.append(v)
            if len(seed) == n:
                cur = sum(seed) / n
                out[k] = cur
            continue
        cur += alpha * (v - cur)
        out[k] = cur
    return out


def _wilder(values: list[float | None], n: int) -> list[float | None]:
    """Wilder's smoothing (alpha 1/n), seeded with the mean of the first n values."""
    out: list[float | None] = [None] * len(values)
    seed, cur = [], None
    for k, v in enumerate(values):
        if v is None:
            continue
        if cur is None:
            seed.append(v)
            if len(seed) == n:
                cur = sum(seed) / n
                out[k] = cur
            continue
        cur += (v - cur) / n
        out[k] = cur
    return out


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


def ema(bars: Sequence[Bar], i: int, n: int) -> float | None:
    return _series(bars, ("ema", n), lambda bs: _ema_of([b.close for b in bs], n))[i]


def macd(bars: Sequence[Bar], i: int, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[float, float] | None:
    """(MACD line, signal line): EMA(fast) - EMA(slow), and the EMA(signal) of that line."""
    def make(bs: Sequence[Bar]) -> list:
        f = _series(bs, ("ema", fast), lambda x: _ema_of([b.close for b in x], fast))
        s = _series(bs, ("ema", slow), lambda x: _ema_of([b.close for b in x], slow))
        line = [a - b if a is not None and b is not None else None for a, b in zip(f, s)]
        sig = _ema_of(line, signal)
        return [(m, g) if g is not None else None for m, g in zip(line, sig)]
    return _series(bars, ("macd", fast, slow, signal), make)[i]


def stoch(bars: Sequence[Bar], i: int, k: int = 14, d: int = 3, smooth: int = 3) -> tuple[float, float] | None:
    """Slow stochastics (%K, %D): raw %K over k bars, smoothed by `smooth`, %D = SMA(d) of %K."""
    def make(bs: Sequence[Bar]) -> list:
        raw: list[float | None] = [None] * len(bs)
        for j in range(k - 1, len(bs)):
            hi, lo = highest(bs, j - k + 1, j + 1), lowest(bs, j - k + 1, j + 1)
            raw[j] = 50.0 if hi == lo else 100 * (bs[j].close - lo) / (hi - lo)
        slow_k = _sma_of(raw, smooth)
        slow_d = _sma_of(slow_k, d)
        return [(a, b) if b is not None else None for a, b in zip(slow_k, slow_d)]
    return _series(bars, ("stoch", k, d, smooth), make)[i]


def _sma_of(values: list[float | None], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for j in range(n - 1, len(values)):
        window = values[j - n + 1:j + 1]
        if None not in window:
            out[j] = sum(window) / n
    return out


def adx(bars: Sequence[Bar], i: int, n: int = 14) -> tuple[float, float, float] | None:
    """(ADX, +DI, -DI) with Wilder's smoothing. ADX ~25+ is usually read as 'trending'."""
    def make(bs: Sequence[Bar]) -> list:
        tr: list[float | None] = [None]
        pdm: list[float | None] = [None]
        mdm: list[float | None] = [None]
        for j in range(1, len(bs)):
            b, p = bs[j], bs[j - 1]
            up, down = b.high - p.high, p.low - b.low
            tr.append(max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close)))
            pdm.append(up if up > down and up > 0 else 0.0)
            mdm.append(down if down > up and down > 0 else 0.0)
        atr_s, p_s, m_s = _wilder(tr, n), _wilder(pdm, n), _wilder(mdm, n)
        pdi: list[float | None] = []
        mdi: list[float | None] = []
        dx: list[float | None] = []
        for a, pp, mm in zip(atr_s, p_s, m_s):
            if a is None or pp is None or mm is None or a == 0:
                pdi.append(None), mdi.append(None), dx.append(None)
                continue
            pi, mi = 100 * pp / a, 100 * mm / a
            pdi.append(pi), mdi.append(mi)
            dx.append(0.0 if pi + mi == 0 else 100 * abs(pi - mi) / (pi + mi))
        adx_s = _wilder(dx, n)
        return [(x, pi, mi) if x is not None else None for x, pi, mi in zip(adx_s, pdi, mdi)]
    return _series(bars, ("adx", n), make)[i]


def psar(bars: Sequence[Bar], i: int, step: float = 0.02, cap: float = 0.2) -> tuple[float, int] | None:
    """Parabolic SAR: (stop level for the next bar, trend +1/-1)."""
    def make(bs: Sequence[Bar]) -> list:
        out: list[tuple[float, int] | None] = [None] * len(bs)
        if len(bs) < 2:
            return out
        trend = 1 if bs[1].close >= bs[0].close else -1
        sar = min(bs[0].low, bs[1].low) if trend == 1 else max(bs[0].high, bs[1].high)
        ep = max(bs[0].high, bs[1].high) if trend == 1 else min(bs[0].low, bs[1].low)
        af = step
        out[1] = (sar, trend)
        for j in range(2, len(bs)):
            b = bs[j]
            sar = sar + af * (ep - sar)
            if trend == 1:
                sar = min(sar, bs[j - 1].low, bs[j - 2].low)
                if b.low < sar:
                    trend, sar, ep, af = -1, ep, b.low, step
                elif b.high > ep:
                    ep, af = b.high, min(af + step, cap)
            else:
                sar = max(sar, bs[j - 1].high, bs[j - 2].high)
                if b.high > sar:
                    trend, sar, ep, af = 1, ep, b.high, step
                elif b.low < ep:
                    ep, af = b.low, min(af + step, cap)
            out[j] = (sar, trend)
        return out
    return _series(bars, ("psar", step, cap), make)[i]


def ichimoku(bars: Sequence[Bar], i: int, tenkan: int = 9, kijun: int = 26, span_b: int = 52) -> tuple[float, float, float, float] | None:
    """(tenkan, kijun, cloud top, cloud bottom) as seen at bar i.

    The cloud plotted at bar i was computed `kijun` bars earlier, so it only uses old bars.
    """
    j = i - kijun
    if j + 1 < span_b or i + 1 < kijun:
        return None

    def mid(end: int, n: int) -> float:
        return (highest(bars, end - n + 1, end + 1) + lowest(bars, end - n + 1, end + 1)) / 2

    a = (mid(j, tenkan) + mid(j, kijun)) / 2
    b = mid(j, span_b)
    return mid(i, tenkan), mid(i, kijun), max(a, b), min(a, b)

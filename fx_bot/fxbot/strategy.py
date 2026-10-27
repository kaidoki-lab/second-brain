"""Strategies decide a target direction; they never place orders themselves.

`decide(bars, i)` may read only bars[0..i]. The decision is executed at the
NEXT bar's open, so a strategy can never trade on a price it hasn't seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from . import swap
from .data import Bar
from .indicators import adx, atr, ema, highest, ichimoku, lowest, macd, psar, rsi, sma, stdev, stoch


@dataclass(frozen=True)
class Decision:
    direction: int               # +1 long, -1 short, 0 flat
    stop: float | None = None    # stop-loss distance in price units
    take: float | None = None    # take-profit distance in price units


class Strategy:
    name = "base"
    summary = ""
    params: dict[str, float] = {}
    symbol = ""   # set by build(); only strategies that need the pair (carry) read it

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


class BandRevert(Strategy):
    """Fade stretches: short above mean + k*stdev, long below mean - k*stdev, flat when price crosses the mean."""

    name = "band_revert"
    summary = "移動平均から標準偏差k個分以上離れたら逆張り、平均に戻ったら手仕舞い"
    params = {"n": 20, "k": 2.0, **_EXIT_PARAMS}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        n = int(self.p["n"])
        mean, sd = sma(bars, i, n), stdev(bars, i, n)
        prev_mean = sma(bars, i - 1, n) if i > 0 else None
        exits = self._exits(bars, i)
        if mean is None or prev_mean is None or not sd or exits is None:
            return None
        close, prev = bars[i].close, bars[i - 1].close
        if close > mean + self.p["k"] * sd:
            return Decision(-1, *exits)
        if close < mean - self.p["k"] * sd:
            return Decision(1, *exits)
        if (prev - prev_mean) * (close - mean) <= 0:
            return Decision(0)
        return None


class RSIRevert(Strategy):
    """Long when RSI is oversold, short when overbought, flat when RSI crosses 50."""

    name = "rsi_revert"
    summary = "RSIが売られすぎで買い・買われすぎで売り、50を跨いだら手仕舞い"
    params = {"n": 14, "lo": 30, "hi": 70, **_EXIT_PARAMS}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        n = int(self.p["n"])
        now, prev = rsi(bars, i, n), rsi(bars, i - 1, n) if i > 0 else None
        exits = self._exits(bars, i)
        if now is None or prev is None or exits is None:
            return None
        if now < self.p["lo"]:
            return Decision(1, *exits)
        if now > self.p["hi"]:
            return Decision(-1, *exits)
        if (prev - 50) * (now - 50) <= 0:
            return Decision(0)
        return None


class Pullback(Strategy):
    """Trade dips in the direction of the long SMA trend; flat when RSI crosses 50."""

    name = "pullback"
    summary = "長期SMAの方向に、RSIが逆に振れた押し目/戻りで入る。RSIが50を跨いだら手仕舞い"
    params = {"trend": 200, "n": 14, "lo": 30, "hi": 70, **_EXIT_PARAMS}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        n = int(self.p["n"])
        trend = sma(bars, i, int(self.p["trend"]))
        now, prev = rsi(bars, i, n), rsi(bars, i - 1, n) if i > 0 else None
        exits = self._exits(bars, i)
        if trend is None or now is None or prev is None or exits is None:
            return None
        up = bars[i].close > trend
        if up and now < self.p["lo"]:
            return Decision(1, *exits)
        if not up and now > self.p["hi"]:
            return Decision(-1, *exits)
        if (prev - 50) * (now - 50) <= 0:
            return Decision(0)
        return None


class SessionBreakout(Strategy):
    """Break of the day's early-session range, traded until a fixed hour, then flat.

    Hours are the data's own clock (MT5 server time). Meant for H1 or shorter bars.
    Being flat every evening also means never holding over the weekend.
    `side` 1 / -1 trades only longs / shorts (a break the other way goes flat);
    `no_fri` 1 stays flat on Fridays. `shift` adds hours to the data's clock first,
    so hours tuned on one broker's server time can be reused on another's
    (e.g. shift=-1 when the new broker's clock runs one hour ahead).
    """

    name = "session_bo"
    summary = ("その日の rs〜re 時の高値/安値を抜けたら入り、exit_h 時に必ず手仕舞い（時刻はサーバー時刻）。"
               "side=1 で買いのみ / -1 で売りのみ、no_fri=1 で金曜は休む、shift で時計をずらす")
    params = {"rs": 0, "re": 8, "exit_h": 20, "side": 0, "no_fri": 0, "shift": 0, **_EXIT_PARAMS}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        rs, re_, exit_h = int(self.p["rs"]), int(self.p["re"]), int(self.p["exit_h"])
        side = int(self.p["side"])
        shift = timedelta(hours=int(self.p["shift"]))
        t = bars[i].time + shift
        if t.hour >= exit_h or t.hour < re_ or (self.p["no_fri"] and t.weekday() == 4):
            return Decision(0)
        hi = lo = None
        k = i
        while k >= 0 and (bars[k].time + shift).date() == t.date():
            if rs <= (bars[k].time + shift).hour < re_:
                hi = bars[k].high if hi is None else max(hi, bars[k].high)
                lo = bars[k].low if lo is None else min(lo, bars[k].low)
            k -= 1
        exits = self._exits(bars, i)
        if hi is None or lo is None or exits is None:
            return None
        direction = 1 if bars[i].close > hi else -1 if bars[i].close < lo else 0
        if direction == 0:
            return None
        if side and direction != side:
            return Decision(0)
        return Decision(direction, *exits)


class Carry(Strategy):
    """Hold the side the overnight swap pays, but only while price is on that side of its long SMA.

    Meant for daily bars. The side comes from the policy-rate table (swap.py): the
    yearly rate a side earns after the broker's `cut` must reach `edge`, else stay flat.
    `side` 1 / -1 fixes the side instead (use the broker's actual swap sheet live).
    Dropping out when the close crosses the `regime`-bar SMA is what keeps a carry
    unwind (2008, 2024-08) from turning into a deep open loss; the `sl_atr` stop is a
    wide backstop on the server. `regime` 0 holds regardless of price.
    """

    name = "carry"
    summary = ("スワップが受け取れる側に持ち続け、終値が regime 本SMAより不利側に来たら降りる（日足向け）。"
               "side=0 は金利表で自動（業者の取り分 cut、受け取り edge 未満なら持たない）、1/-1 で固定")
    params = {"regime": 100, "edge": 0.5, "cut": 1.0, "side": 0, "atr": 20, "sl_atr": 5.0, "tp_atr": 0.0}

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        side = int(self.p["side"])
        if not side:
            if not self.symbol:
                raise ValueError("carry: side=1/-1 を指定するか、通貨ペア (--symbol) を渡してください")
            if not swap.covered(bars[i].time.date()):
                return None
            d = swap.diff(self.symbol, bars[i].time.date())
            cut, edge = self.p["cut"], self.p["edge"]
            side = 1 if d - cut >= edge else -1 if -d - cut >= edge else 0
            if not side:
                return Decision(0)
        n = int(self.p["regime"])
        if n:
            mean = sma(bars, i, n)
            if mean is None:
                return None
            if (bars[i].close - mean) * side < 0:
                return Decision(0)
        exits = self._exits(bars, i)
        return Decision(side, *exits) if exits else None


class Combo(Strategy):
    """An entry signal gated by a market-state filter.

    sig: 1 MACD crosses its signal line / 2 stochastics %K crosses %D below `lo` (buy)
         or above `hi` (sell) / 3 Parabolic SAR flips / 4 Ichimoku tenkan crosses kijun /
         5 EMA(fast) crosses EMA(slow)
    flt: 0 none / 1 ADX >= `adx` and the DI lines agree (trending) / 2 ADX < `adx` (ranging) /
         3 close on the signal's side of SMA(`trend`) / 4 close outside the Ichimoku cloud on that side
    Ichimoku uses `tenkan` / `kijun` with span B = 2 x kijun.
    A signal the filter allows is entered (reversing any opposite position); one it
    blocks closes the position. Between signals the position is kept.
    """

    name = "combo"
    summary = ("入る合図 sig（1 MACD / 2 ストキャス / 3 パラボリック / 4 一目の転換線×基準線 / 5 EMA交差）を、"
               "地合い flt（0 なし / 1 ADXで強いトレンド / 2 ADXでレンジ / 3 SMA(trend)の向き / 4 雲の外）で絞る")
    params = {"sig": 1, "flt": 0, "fast": 12, "slow": 26, "signal": 9, "k": 14, "lo": 20, "hi": 80,
              "adx_n": 14, "adx": 25, "trend": 200, "tenkan": 9, "kijun": 26, "side": 0, **_EXIT_PARAMS}

    def _ichimoku(self, bars: Sequence[Bar], i: int):
        kijun = int(self.p["kijun"])
        return ichimoku(bars, i, int(self.p["tenkan"]), kijun, 2 * kijun)

    def _signal(self, bars: Sequence[Bar], i: int) -> int | None:
        """+1 / -1 on a fresh signal at bar i, 0 when none, None while indicators warm up."""
        sig, p = int(self.p["sig"]), self.p
        if sig in (1, 4, 5):
            if sig == 1:
                now, prev = macd(bars, i, int(p["fast"]), int(p["slow"]), int(p["signal"])), \
                    macd(bars, i - 1, int(p["fast"]), int(p["slow"]), int(p["signal"]))
            elif sig == 4:
                now, prev = self._ichimoku(bars, i), self._ichimoku(bars, i - 1)
            else:
                f0, s0 = ema(bars, i, int(p["fast"])), ema(bars, i, int(p["slow"]))
                f1, s1 = ema(bars, i - 1, int(p["fast"])), ema(bars, i - 1, int(p["slow"]))
                now = (f0, s0) if f0 is not None and s0 is not None else None
                prev = (f1, s1) if f1 is not None and s1 is not None else None
            if now is None or prev is None:
                return None
            a0, b0, a1, b1 = now[0], now[1], prev[0], prev[1]
            return 1 if a1 <= b1 and a0 > b0 else -1 if a1 >= b1 and a0 < b0 else 0
        if sig == 2:
            now, prev = stoch(bars, i, int(p["k"])), stoch(bars, i - 1, int(p["k"]))
            if now is None or prev is None:
                return None
            if prev[0] <= prev[1] and now[0] > now[1] and now[1] < p["lo"]:
                return 1
            if prev[0] >= prev[1] and now[0] < now[1] and now[1] > p["hi"]:
                return -1
            return 0
        if sig == 3:
            now, prev = psar(bars, i), psar(bars, i - 1)
            if now is None or prev is None:
                return None
            return now[1] if now[1] != prev[1] else 0
        raise ValueError(f"combo: sig は 1〜5 です ({sig})")

    def _allows(self, bars: Sequence[Bar], i: int, direction: int) -> bool | None:
        flt, p = int(self.p["flt"]), self.p
        if flt == 0:
            return True
        if flt in (1, 2):
            a = adx(bars, i, int(p["adx_n"]))
            if a is None:
                return None
            if flt == 2:
                return a[0] < p["adx"]
            return a[0] >= p["adx"] and (a[1] - a[2]) * direction > 0
        if flt == 3:
            mean = sma(bars, i, int(p["trend"]))
            return None if mean is None else (bars[i].close - mean) * direction > 0
        if flt == 4:
            ich = self._ichimoku(bars, i)
            if ich is None:
                return None
            return bars[i].close > ich[2] if direction > 0 else bars[i].close < ich[3]
        raise ValueError(f"combo: flt は 0〜4 です ({flt})")

    def decide(self, bars: Sequence[Bar], i: int) -> Decision | None:
        if i < 1:
            return None
        direction = self._signal(bars, i)
        if not direction:
            return None
        side = int(self.p["side"])
        ok = self._allows(bars, i, direction)
        exits = self._exits(bars, i)
        if ok is None or exits is None:
            return None
        if not ok or (side and direction != side):
            return Decision(0)
        return Decision(direction, *exits)


STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (MACross, Breakout, BandRevert, RSIRevert, Pullback, SessionBreakout, Carry, Combo)
}


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


def build(name: str, params: dict[str, float] | None = None, symbol: str = "") -> Strategy:
    if name not in STRATEGIES:
        raise ValueError(f"未知の戦略 {name!r} (使えるもの: {', '.join(STRATEGIES)})")
    strat = STRATEGIES[name](**(params or {}))
    strat.symbol = symbol
    return strat

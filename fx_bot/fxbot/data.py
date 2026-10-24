"""Price bars: load from CSV, write to CSV, or synthesize for dry runs.

Bars are assumed to be BID prices (the MT5 / most broker export default).
The spread is added on top by the broker simulation.
"""

from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


_TIME_KEYS = ("time", "datetime", "timestamp", "date")


def _norm(name: str) -> str:
    return name.strip().strip("<>").lower()


def _parse_time(text: str) -> datetime:
    text = text.strip().replace(".", "-").replace("/", "-").replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d %H%M%S", "%Y%m%d %H%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(text)


def load_csv(path: str | Path) -> list[Bar]:
    """Read OHLC bars. Accepts comma/tab/semicolon files with a header.

    Handles both `time,open,high,low,close` and the MT5 export style
    `<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>...`.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{path}: 空のファイルです")
    dialect = csv.Sniffer().sniff(lines[0], delimiters=",\t;")
    reader = csv.reader(lines, dialect)
    header = [_norm(h) for h in next(reader)]

    def col(*names: str) -> int | None:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_open, i_high, i_low, i_close = col("open"), col("high"), col("low"), col("close")
    if None in (i_open, i_high, i_low, i_close):
        raise ValueError(f"{path}: open/high/low/close 列が見つかりません (列: {header})")
    i_time = col(*_TIME_KEYS)
    i_clock = col("time") if col("date") is not None else None
    if i_clock is not None:
        i_time = col("date")
    if i_time is None:
        raise ValueError(f"{path}: 日時の列が見つかりません (列: {header})")
    i_vol = col("volume", "tickvol", "tick_volume", "vol")

    bars: list[Bar] = []
    for row in reader:
        stamp = row[i_time] if i_clock is None else f"{row[i_time]} {row[i_clock]}"
        bars.append(Bar(
            time=_parse_time(stamp),
            open=float(row[i_open]),
            high=float(row[i_high]),
            low=float(row[i_low]),
            close=float(row[i_close]),
            volume=float(row[i_vol]) if i_vol is not None and row[i_vol] else 0.0,
        ))
    bars.sort(key=lambda b: b.time)
    return bars


def write_csv(path: str | Path, bars: Iterable[Bar]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        for b in bars:
            w.writerow([b.time.strftime("%Y-%m-%d %H:%M:%S"), b.open, b.high, b.low, b.close, b.volume])


def synthetic(
    n: int = 5000,
    start: float = 150.0,
    seed: int = 1,
    minutes: int = 60,
    vol: float = 0.0015,
    digits: int = 3,
) -> list[Bar]:
    """Random-walk bars with slowly drifting trend regimes.

    For wiring checks only — profits on synthetic data mean nothing.
    """
    rng = random.Random(seed)
    t = datetime(2020, 1, 1)
    price = start
    drift = 0.0
    bars: list[Bar] = []
    for _ in range(n):
        if rng.random() < 0.01:
            drift = rng.gauss(0, vol / 40)
        o = price
        path = [o]
        for _ in range(4):
            path.append(path[-1] * math.exp(drift / 4 + rng.gauss(0, vol / 2)))
        c = path[-1]
        bars.append(Bar(
            time=t,
            open=round(o, digits),
            high=round(max(path), digits),
            low=round(min(path), digits),
            close=round(c, digits),
            volume=float(rng.randint(100, 1000)),
        ))
        price = c
        t += timedelta(minutes=minutes)
    return bars

"""Put the package on sys.path and build bars for tests."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fxbot.data import Bar  # noqa: E402


def bars(rows):
    """rows: (open, high, low, close) tuples -> hourly bars from 2024-01-01."""
    t = datetime(2024, 1, 1)
    return [Bar(t + timedelta(hours=k), *r) for k, r in enumerate(rows)]


def flat(n, price=100.0):
    return bars([(price, price + 0.1, price - 0.1, price)] * n)

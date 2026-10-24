#!/usr/bin/env python3
"""FX bot launcher — `python run.py backtest --csv data/xxx.csv`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fxbot.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

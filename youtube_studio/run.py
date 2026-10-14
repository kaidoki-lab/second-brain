#!/usr/bin/env python3
"""YOUTUBE STUDIO launcher — `python run.py auto`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

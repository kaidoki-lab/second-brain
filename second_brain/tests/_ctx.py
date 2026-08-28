"""Put the package on sys.path and build ready-made brains for tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from secondbrain.defaults import install_defaults, seed_demo  # noqa: E402
from secondbrain.store import Store  # noqa: E402


def fresh_store() -> Store:
    store = Store.open(":memory:")
    install_defaults(store)
    return store


def seeded_store() -> Store:
    store = fresh_store()
    seed_demo(store)
    return store

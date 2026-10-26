import unittest
from datetime import datetime

import _ctx  # noqa: F401

from fxbot.broker import Trade
from fxbot.compare import match, pips


def trade(direction, hh, mm, entry, exit_, reason="signal"):
    t = datetime(2026, 10, 27, hh, mm)
    return Trade(direction, 1000, t, entry, t.replace(hour=22, minute=0), exit_, 0.0, reason)


class CompareTest(unittest.TestCase):
    def test_pairs_by_direction_and_time(self):
        live = [trade(1, 11, 0, 150.005, 150.30), trade(1, 15, 0, 151.0, 150.9)]
        test = [trade(1, 11, 0, 150.003, 150.31), trade(-1, 15, 0, 151.0, 150.8), trade(1, 18, 0, 152, 152.1)]
        pairs = match(live, test)
        self.assertEqual(len(pairs), 4)
        first = pairs[0]
        self.assertAlmostEqual(first.entry_gap(0.01), 0.2)     # live paid 0.2 pips more
        self.assertAlmostEqual(first.exit_gap(0.01), 1.0)      # and sold 1 pip lower
        self.assertEqual(sum(p.test is None for p in pairs), 1)    # live long at 15:00 vs backtest short
        self.assertEqual(sum(p.live is None for p in pairs), 2)
        self.assertAlmostEqual(pips(live[0], 0.01), 29.5)

    def test_live_seconds_after_the_bar_still_match(self):
        live = [Trade(1, 1000, datetime(2026, 10, 27, 11, 0, 7), 150, datetime(2026, 10, 27, 22, 0, 5), 150.1, 0, "signal")]
        test = [trade(1, 11, 0, 150, 150.1)]
        self.assertIsNotNone(match(live, test)[0].test)


if __name__ == "__main__":
    unittest.main()

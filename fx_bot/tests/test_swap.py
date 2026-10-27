import unittest
from datetime import date, datetime

import _ctx  # noqa: F401 - puts fxbot on the path

from fxbot import swap


class SwapTableTest(unittest.TestCase):
    def test_rate_steps_on_the_change_date(self):
        self.assertEqual(swap.rate("JPY", date(2024, 7, 30)), 0.05)
        self.assertEqual(swap.rate("JPY", date(2024, 7, 31)), 0.25)

    def test_diff_and_broker_suffixes(self):
        self.assertAlmostEqual(swap.diff("USDJPY", date(2024, 1, 10)), 5.375 + 0.1)
        self.assertAlmostEqual(swap.diff("usdjpy.m", date(2024, 1, 10)), swap.diff("USDJPY-", date(2024, 1, 10)))

    def test_estimator_takes_the_cut_from_both_sides(self):
        at = swap.estimator("AUDJPY", cut=1.0)
        d = swap.diff("AUDJPY", date(2026, 1, 5))
        self.assertEqual(at(datetime(2026, 1, 5, 12)), (d - 1.0, -d - 1.0))

    def test_no_swap_before_the_table(self):
        self.assertEqual(swap.estimator("AUDJPY")(datetime(2005, 6, 1)), (0.0, 0.0))

    def test_unknown_currency_is_an_error(self):
        with self.assertRaises(ValueError):
            swap.estimator("XAUUSD")


if __name__ == "__main__":
    unittest.main()

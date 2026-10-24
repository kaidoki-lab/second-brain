import unittest

import _ctx  # noqa: F401

from fxbot.risk import DrawdownGuard, RiskConfig, pip_size, size_units


class RiskTest(unittest.TestCase):
    def test_pip_size(self):
        self.assertEqual(pip_size("USDJPY"), 0.01)
        self.assertEqual(pip_size("eurusd"), 0.0001)

    def test_risk_based_size(self):
        # 1% of 1,000,000 JPY = 10,000; stop 0.5 JPY -> 20,000 units
        self.assertEqual(size_units(1_000_000, 150, 0.5, RiskConfig()), 20_000)

    def test_leverage_cap(self):
        # tiny stop would ask for huge size; 25x of 1,000,000 at 150 = 166,666 -> 166,000
        self.assertEqual(size_units(1_000_000, 150, 0.01, RiskConfig()), 166_000)

    def test_quote_conversion(self):
        # EURUSD on a JPY account: stop 0.0050 USD * 150 JPY/USD = 0.75 JPY per unit
        cfg = RiskConfig(quote_to_account=150)
        self.assertEqual(size_units(1_000_000, 1.08, 0.005, cfg), 13_000)

    def test_too_small_is_zero(self):
        self.assertEqual(size_units(1000, 150, 5, RiskConfig()), 0)

    def test_drawdown_guard(self):
        g = DrawdownGuard(20)
        self.assertFalse(g.update(100))
        self.assertFalse(g.update(120))
        self.assertFalse(g.update(97))
        self.assertTrue(g.update(95))
        self.assertTrue(g.update(200))   # stays tripped


if __name__ == "__main__":
    unittest.main()

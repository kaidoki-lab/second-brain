import unittest
from datetime import datetime

from _ctx import bars

from fxbot.broker import PaperBroker
from fxbot.data import Bar


class PaperBrokerTest(unittest.TestCase):
    def test_order_fills_at_next_open_with_spread(self):
        b = PaperBroker(1_000_000, spread=0.02)
        series = bars([(100, 100.5, 99.5, 100.2), (100.3, 100.6, 100.1, 100.4)])
        b.on_bar(series[0])
        b.open(1, 1000, stop=1.0, take=None)
        self.assertIsNone(b.position())          # not filled until the next bar
        b.on_bar(series[1])
        pos = b.position()
        self.assertAlmostEqual(pos.entry_price, 100.32)
        self.assertAlmostEqual(pos.stop_price, 99.32)

    def test_short_pays_spread_on_exit(self):
        b = PaperBroker(0, spread=0.02)
        series = bars([(100, 100, 100, 100)] * 3)
        b.on_bar(series[0])
        b.open(-1, 1000, stop=5, take=None)
        b.on_bar(series[1])
        b.close()
        b.on_bar(series[2])
        self.assertAlmostEqual(b.trades[0].exit_price, 100.02)
        self.assertAlmostEqual(b.trades[0].pnl, -20)

    def test_stop_wins_when_both_hit(self):
        b = PaperBroker(0, spread=0)
        series = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 103, 97, 100)])
        b.on_bar(series[0])
        b.open(1, 1000, stop=2, take=2)
        b.on_bar(series[1])
        b.on_bar(series[2])
        self.assertEqual(b.trades[0].reason, "stop")
        self.assertAlmostEqual(b.trades[0].exit_price, 98)

    def test_gap_through_stop_fills_at_open(self):
        b = PaperBroker(0, spread=0)
        series = bars([(100, 100, 100, 100), (100, 100, 100, 100), (95, 96, 94, 95)])
        b.on_bar(series[0])
        b.open(1, 1000, stop=2, take=None)
        b.on_bar(series[1])
        b.on_bar(series[2])
        self.assertAlmostEqual(b.trades[0].exit_price, 95)
        self.assertAlmostEqual(b.trades[0].pnl, -5000)

    def test_short_take_profit(self):
        b = PaperBroker(0, spread=0)
        series = bars([(100, 100, 100, 100), (100, 100, 100, 100), (99.5, 99.8, 96, 97)])
        b.on_bar(series[0])
        b.open(-1, 1000, stop=5, take=3)
        b.on_bar(series[1])
        b.on_bar(series[2])
        self.assertEqual(b.trades[0].reason, "take")
        self.assertAlmostEqual(b.trades[0].exit_price, 97)
        self.assertAlmostEqual(b.trades[0].pnl, 3000)

    def test_slippage_worsens_market_and_stop_fills(self):
        b = PaperBroker(0, spread=0, slippage=0.1)
        flat = (100, 100, 100, 100)
        series = bars([flat, flat, flat, flat, (100, 100, 97, 98)])
        b.on_bar(series[0])
        b.open(-1, 1000, stop=5, take=None)
        b.on_bar(series[1])
        self.assertAlmostEqual(b.position().entry_price, 99.9)   # short sells lower
        b.close()
        b.on_bar(series[2])
        self.assertAlmostEqual(b.trades[0].exit_price, 100.1)    # buys back higher
        b.open(1, 1000, stop=2, take=None)
        b.on_bar(series[3])
        self.assertAlmostEqual(b.position().stop_price, 98.1)
        b.on_bar(series[4])
        self.assertEqual(b.trades[1].reason, "stop")
        self.assertAlmostEqual(b.trades[1].exit_price, 98.0)     # stop 98.1 filled 0.1 worse

    def test_take_profit_has_no_slippage(self):
        b = PaperBroker(0, spread=0, slippage=0.1)
        series = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 103, 100, 102)])
        b.on_bar(series[0])
        b.open(1, 1000, stop=5, take=2)
        b.on_bar(series[1])
        b.on_bar(series[2])
        self.assertEqual(b.trades[0].reason, "take")
        self.assertAlmostEqual(b.trades[0].exit_price, 102.1)

    def test_swap_accrues_per_calendar_day_held(self):
        # +3.65%/yr long, -5%/yr short; daily bars Thu, Fri, Mon (weekend = 3 days)
        b = PaperBroker(0, spread=0, swap=lambda t: (3.65, -5.0))
        days = [datetime(2024, 1, 4), datetime(2024, 1, 5), datetime(2024, 1, 8), datetime(2024, 1, 9)]
        series = [Bar(d, 100, 100, 100, 100) for d in days]
        b.on_bar(series[0])
        b.open(1, 1000, stop=5, take=None)
        b.on_bar(series[1])                       # filled Fri open: nothing held overnight yet
        self.assertAlmostEqual(b.position().swap, 0)
        b.on_bar(series[2])                       # Fri -> Mon: 3 days x 1000 x 100 x 3.65% / 365
        self.assertAlmostEqual(b.position().swap, 30)
        self.assertAlmostEqual(b.equity(), 30)
        b.close()
        b.on_bar(series[3])                       # one more night, then closed at Tue open
        self.assertAlmostEqual(b.trades[0].swap, 40)
        self.assertAlmostEqual(b.trades[0].pnl, 40)

    def test_short_pays_negative_swap(self):
        b = PaperBroker(0, spread=0, swap=lambda t: (3.65, -3.65))
        series = [Bar(datetime(2024, 1, d), 100, 100, 100, 100) for d in (1, 2, 3)]
        b.on_bar(series[0])
        b.open(-1, 1000, stop=5, take=None)
        b.on_bar(series[1])
        b.on_bar(series[2])
        self.assertAlmostEqual(b.position().swap, -10)

    def test_equity_marks_to_market(self):
        b = PaperBroker(1000, spread=0)
        series = bars([(100, 100, 100, 100), (100, 101, 100, 101)])
        b.on_bar(series[0])
        b.open(1, 10, stop=5, take=None)
        b.on_bar(series[1])
        self.assertAlmostEqual(b.equity(), 1010)


if __name__ == "__main__":
    unittest.main()

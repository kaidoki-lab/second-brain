import random
import unittest

from _ctx import bars

from fxbot.indicators import adx, ema, ichimoku, macd, psar, stoch
from fxbot.strategy import Decision, build


def closes(values):
    """Bars whose range is +-0.5 around each close."""
    return bars([(c, c + 0.5, c - 0.5, c) for c in values])


def walk(n, seed=3):
    rnd, c, out = random.Random(seed), 100.0, []
    for _ in range(n):
        o = c
        c = o + rnd.gauss(0, 0.3)
        out.append((o, max(o, c) + rnd.random() * 0.2, min(o, c) - rnd.random() * 0.2, c))
    return bars(out)


class IndicatorTest(unittest.TestCase):
    def test_ema_seeds_with_sma_then_smooths(self):
        series = closes(range(1, 11))
        self.assertIsNone(ema(series, 1, 3))
        self.assertEqual(ema(series, 2, 3), 2.0)          # (1+2+3)/3
        self.assertEqual(ema(series, 3, 3), 3.0)          # 2 + 0.5*(4-2)
        self.assertAlmostEqual(ema(series, 9, 3), 9.0)    # lags a straight line by one step

    def test_macd_is_zero_on_a_flat_market(self):
        series = closes([100.0] * 60)
        self.assertIsNone(macd(series, 30))
        self.assertEqual(macd(series, 59), (0.0, 0.0))

    def test_stoch_is_high_in_a_rally_and_low_in_a_fall(self):
        up, down = closes([100 + k for k in range(30)]), closes([100 - k for k in range(30)])
        self.assertGreater(stoch(up, 29)[0], 90)
        self.assertLess(stoch(down, 29)[0], 10)

    def test_adx_sees_a_trend_and_its_side(self):
        series = closes([100 + k * 0.8 for k in range(80)])
        value, plus, minus = adx(series, 79)
        self.assertGreater(value, 25)
        self.assertGreater(plus, minus)

    def test_psar_flips_after_a_reversal(self):
        series = closes([100 + k for k in range(20)] + [119 - 3 * k for k in range(1, 8)])
        self.assertEqual(psar(series, 19)[1], 1)
        self.assertEqual(psar(series, 26)[1], -1)

    def test_ichimoku_cloud_uses_bars_kijun_back(self):
        series = closes([float(k) for k in range(100)])
        tenkan, kijun, top, bottom = ichimoku(series, 99)
        self.assertEqual(tenkan, (99.5 + 90.5) / 2)
        self.assertEqual(kijun, (99.5 + 73.5) / 2)
        a = ((73.5 + 64.5) / 2 + (73.5 + 47.5) / 2) / 2    # tenkan/kijun as of bar 73
        b = (73.5 + 21.5) / 2                              # 52-bar midpoint as of bar 73
        self.assertEqual((top, bottom), (max(a, b), min(a, b)))

    def test_values_never_depend_on_later_bars(self):
        series = walk(300)
        for i in (60, 150, 299):
            cut = series[:i + 1]
            for fn in (lambda s: ema(s, i, 20), lambda s: macd(s, i), lambda s: stoch(s, i),
                       lambda s: adx(s, i), lambda s: psar(s, i), lambda s: ichimoku(s, i)):
                self.assertEqual(fn(series), fn(cut))

    def test_cache_tells_lists_of_the_same_length_apart(self):
        a, b = closes([100.0] * 50), closes([200.0] * 50)
        self.assertEqual(ema(a, 49, 10), 100.0)
        self.assertEqual(ema(b, 49, 10), 200.0)


class ComboTest(unittest.TestCase):
    def v_shape(self):
        return closes([110 - k for k in range(10)] + [101 + k for k in range(10)])

    def test_ema_cross_buys_after_the_turn(self):
        strat = build("combo", {"sig": 5, "fast": 2, "slow": 5, "atr": 3})
        series = self.v_shape()
        hits = [i for i in range(len(series)) if (d := strat.decide(series, i)) and d.direction == 1]
        self.assertEqual(len(hits), 1)
        self.assertGreater(hits[0], 10)

    def test_side_and_filter_turn_signals_into_flat(self):
        series = self.v_shape()
        hit = next(i for i in range(len(series))
                   if (d := build("combo", {"sig": 5, "fast": 2, "slow": 5, "atr": 3}).decide(series, i))
                   and d.direction == 1)
        sell_only = build("combo", {"sig": 5, "fast": 2, "slow": 5, "atr": 3, "side": -1})
        self.assertEqual(sell_only.decide(series, hit), Decision(0))
        # still below the 10-bar SMA right after the turn, so the trend filter blocks the buy
        trend = build("combo", {"sig": 5, "fast": 2, "slow": 5, "atr": 3, "flt": 3, "trend": 10})
        self.assertEqual(trend.decide(series, hit), Decision(0))

    def test_decisions_never_depend_on_later_bars(self):
        series = walk(400, seed=8)
        for sig in range(1, 6):
            for flt in range(5):
                strat = build("combo", {"sig": sig, "flt": flt, "trend": 50})
                for i in (120, 250, 399):
                    self.assertEqual(strat.decide(series, i), strat.decide(series[:i + 1], i), (sig, flt, i))

    def test_unknown_codes_are_errors(self):
        with self.assertRaises(ValueError):
            build("combo", {"sig": 9}).decide(walk(50), 49)


if __name__ == "__main__":
    unittest.main()

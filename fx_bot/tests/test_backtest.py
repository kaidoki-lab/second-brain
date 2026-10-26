import unittest

from _ctx import bars, flat

from fxbot import backtest, data, metrics
from fxbot.risk import RiskConfig
from fxbot.indicators import rsi, stdev
from fxbot.strategy import (BandRevert, Breakout, Decision, MACross, Pullback, RSIRevert, SessionBreakout,
                            Strategy, build, parse_params)


class Script(Strategy):
    """Returns pre-set decisions by bar index; records what it was allowed to see."""

    name = "script"

    def __init__(self, plan):
        super().__init__()
        self.plan = plan
        self.seen = []

    def decide(self, bars_, i):
        self.seen.append(i)
        return self.plan.get(i)


class BacktestTest(unittest.TestCase):
    def test_signal_executes_next_open_and_reverses(self):
        series = bars([(100, 100, 100, 100), (101, 101, 101, 101), (102, 102, 102, 102),
                       (103, 103, 103, 103), (104, 104, 104, 104)])
        strat = Script({0: Decision(1, stop=10), 2: Decision(-1, stop=10)})
        risk = RiskConfig(risk_pct=1, lot_step=1)
        r = backtest.run(series, strat, risk, initial_equity=100_000)
        self.assertEqual([t.reason for t in r.trades], ["signal", "end"])
        long, short = r.trades
        self.assertEqual((long.entry_price, long.exit_price), (101, 103))
        self.assertEqual(long.units, 100)               # 1,000 risk / 10 stop
        self.assertEqual((short.entry_price, short.exit_price), (103, 104))
        self.assertEqual(r.final_equity, 100_000 + 200 - short.units)

    def test_halt_on_drawdown(self):
        series = bars([(100, 100, 100, 100), (100, 100, 100, 100)] + [(90, 90, 90, 90)] * 3)
        strat = Script({0: Decision(1, stop=20)})
        r = backtest.run(series, strat, RiskConfig(risk_pct=50, lot_step=1, max_drawdown_pct=10), 10_000)
        self.assertIsNotNone(r.halted_at)
        self.assertEqual(r.trades[-1].reason, "halt")

    def test_no_trades_on_flat_market(self):
        r = backtest.run(flat(300), MACross())
        self.assertEqual(r.trades, [])
        self.assertEqual(r.final_equity, 1_000_000)

    def test_synthetic_runs_end_to_end(self):
        series = data.synthetic(n=1500, seed=3)
        for strat in (MACross(fast=10, slow=40), Breakout(n=20)):
            r = backtest.run(series, strat, spread=0.003)
            stats = metrics.summarize(r)
            self.assertGreater(stats["trades"], 0)
            self.assertAlmostEqual(r.final_equity, 1_000_000 + sum(t.pnl for t in r.trades), places=4)

    def test_spread_costs_money(self):
        series = data.synthetic(n=1500, seed=5)
        free = backtest.run(series, MACross(fast=10, slow=40), spread=0)
        paid = backtest.run(series, MACross(fast=10, slow=40), spread=0.05)
        self.assertLess(paid.final_equity, free.final_equity)


class StrategyTest(unittest.TestCase):
    def test_parse_and_build(self):
        s = build("ma_cross", parse_params("fast=5, slow=30"))
        self.assertEqual((s.p["fast"], s.p["slow"]), (5, 30))
        with self.assertRaises(ValueError):
            build("ma_cross", {"nope": 1})
        with self.assertRaises(ValueError):
            build("unknown")
        with self.assertRaises(ValueError):
            parse_params("fast")

    def test_breakout_direction(self):
        rows = [(100, 101, 99, 100)] * 20 + [(100, 103, 100, 102.5)]
        d = Breakout(n=10, atr=5).decide(bars(rows), 20)
        self.assertEqual(d.direction, 1)
        self.assertIsNone(Breakout(n=10, atr=5).decide(bars(rows), 19))

    def test_indicators(self):
        series = bars([(c, c, c, c) for c in (1, 2, 3, 2, 1)])
        self.assertAlmostEqual(stdev(series, 2, 3), (2 / 3) ** 0.5)
        self.assertEqual(rsi(series, 2, 2), 100)        # two gains
        self.assertEqual(rsi(series, 4, 2), 0)          # two losses
        self.assertEqual(rsi(series, 3, 2), 50)         # +1 then -1
        self.assertIsNone(rsi(series, 1, 2))

    def test_band_revert_fades_and_exits_at_mean(self):
        rows = [(100, 100.5, 99.5, 100 + (0.2 if k % 2 else -0.2)) for k in range(30)]
        spike = bars(rows + [(100, 103, 100, 103)])
        self.assertEqual(BandRevert(n=20, atr=5).decide(spike, 30).direction, -1)
        dip = bars(rows + [(100, 100, 97, 97)])
        self.assertEqual(BandRevert(n=20, atr=5).decide(dip, 30).direction, 1)
        back = bars(rows + [(100, 101, 99, 100.25), (100, 100, 99.8, 99.9)])
        self.assertEqual(BandRevert(n=20, atr=5).decide(back, 31).direction, 0)

    def test_rsi_revert(self):
        falling = bars([(100 - k, 101 - k, 99 - k, 100 - k) for k in range(20)])
        self.assertEqual(RSIRevert(n=14, atr=5).decide(falling, 19).direction, 1)
        rising = bars([(100 + k, 101 + k, 99 + k, 100 + k) for k in range(20)])
        self.assertEqual(RSIRevert(n=14, atr=5).decide(rising, 19).direction, -1)

    def test_pullback_only_with_trend(self):
        up = [(100 + k, 101 + k, 99 + k, 100 + k) for k in range(60)]
        dip = up + [(c, c + 1, c - 1, c) for c in (158, 157, 156)]
        s = Pullback(trend=50, n=3, atr=5)
        self.assertEqual(s.decide(bars(dip), len(dip) - 1).direction, 1)
        # same RSI dip below a falling trend is not bought
        down = [(200 - k, 201 - k, 199 - k, 200 - k) for k in range(60)]
        self.assertNotEqual(getattr(s.decide(bars(down), 59), "direction", None), 1)

    def test_session_breakout_range_and_forced_exit(self):
        # 00:00-07:00 range 99..101, then a break at 09:00, then 20:00 forces flat
        rows = [(100, 101, 99, 100)] * 8 + [(100, 100.5, 99.5, 100), (100, 102, 100, 101.5)]
        rows += [(101, 101.5, 100.5, 101)] * 10 + [(101, 101, 101, 101)]
        series = bars(rows)
        s = SessionBreakout(rs=0, re=8, exit_h=20, atr=5)
        self.assertEqual(s.decide(series, 7).direction, 0)      # still inside the range window
        self.assertIsNone(s.decide(series, 8))                  # inside the range
        self.assertEqual(s.decide(series, 9).direction, 1)      # broke 101
        self.assertEqual(s.decide(series, 20).direction, 0)     # 20:00 -> flat

    def test_session_breakout_side_and_friday_filters(self):
        up = [(100, 101, 99, 100)] * 8 + [(100, 102, 100, 101.5)]
        down = [(100, 101, 99, 100)] * 8 + [(100, 100, 98, 98.5)]
        p = dict(rs=0, re=8, exit_h=20, atr=5)
        self.assertEqual(SessionBreakout(side=1, **p).decide(bars(up), 8).direction, 1)
        self.assertEqual(SessionBreakout(side=1, **p).decide(bars(down), 8).direction, 0)   # short break -> flat
        self.assertEqual(SessionBreakout(side=-1, **p).decide(bars(down), 8).direction, -1)
        friday = bars([(100, 100, 100, 100)] * 96 + up)         # 2024-01-01 is a Monday
        self.assertEqual(friday[104].time.weekday(), 4)
        self.assertEqual(SessionBreakout(**p).decide(friday, 104).direction, 1)
        self.assertEqual(SessionBreakout(no_fri=1, **p).decide(friday, 104).direction, 0)

    def test_session_breakout_shift_moves_the_clock(self):
        # the same day seen by a broker one hour ahead: everything one bar later
        rows = [(100, 100, 100, 100)] + [(100, 101, 99, 100)] * 8 + [(100, 102, 100, 101.5)]
        series = bars(rows)
        s = SessionBreakout(rs=0, re=8, exit_h=20, atr=5, shift=-1)
        self.assertEqual(s.decide(series, 8).direction, 0)      # 08:00 data = 07:00 shifted, still in the range
        self.assertEqual(s.decide(series, 9).direction, 1)

    def test_new_strategies_run_end_to_end(self):
        series = data.synthetic(n=1500, seed=3)
        for name in ("band_revert", "rsi_revert", "pullback", "session_bo"):
            r = backtest.run(series, build(name), spread=0.003)
            self.assertAlmostEqual(r.final_equity, 1_000_000 + sum(t.pnl for t in r.trades), places=4)


if __name__ == "__main__":
    unittest.main()

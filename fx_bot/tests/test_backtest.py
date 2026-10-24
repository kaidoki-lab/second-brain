import unittest

from _ctx import bars, flat

from fxbot import backtest, data, metrics
from fxbot.risk import RiskConfig
from fxbot.strategy import Breakout, Decision, MACross, Strategy, build, parse_params


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


if __name__ == "__main__":
    unittest.main()

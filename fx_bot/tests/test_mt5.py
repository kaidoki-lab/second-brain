"""MT5 link against an in-memory fake of the MetaTrader5 module."""

import unittest
from types import SimpleNamespace as NS

import _ctx  # noqa: F401

from fxbot import mt5 as link
from fxbot.risk import RiskConfig
from fxbot.strategy import Decision, Strategy


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    TIMEFRAME_H1 = 16385
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    TRADE_ACTION_DEAL, ORDER_TIME_GTC, TRADE_RETCODE_DONE = 1, 0, 10009

    def __init__(self, trade_mode=0, closes=(150.0,) * 30):
        self.trade_mode = trade_mode
        self.equity = 1_000_000.0
        self.closes = list(closes)
        self.positions = []
        self.requests = []
        self.ticket = 0
        self.reject = False

    def account_info(self):
        return NS(trade_mode=self.trade_mode, equity=self.equity, balance=self.equity,
                  currency="JPY", login=1, server="Demo")

    def symbol_info(self, symbol):
        if symbol != "USDJPY":
            return None
        return NS(visible=True, digits=3, volume_step=0.01, volume_min=0.01,
                  trade_contract_size=100_000, filling_mode=2)

    def symbol_info_tick(self, symbol):
        return NS(bid=self.closes[-1], ask=self.closes[-1] + 0.003)

    def copy_rates_from_pos(self, symbol, tf, start, count):
        t0 = 1_700_000_000
        rows = [{"time": t0 + k * 3600, "open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "tick_volume": 10}
                for k, c in enumerate(self.closes)]
        return rows[-count:]

    def positions_get(self, symbol=None):
        return tuple(self.positions)

    def last_error(self):
        return (0, "ok")

    def order_send(self, req):
        self.requests.append(req)
        if self.reject:
            return NS(retcode=10019, comment="No money", price=0)
        if "position" in req:
            self.positions = [p for p in self.positions if p.ticket != req["position"]]
        else:
            self.ticket += 1
            self.positions.append(NS(ticket=self.ticket, type=req["type"], volume=req["volume"], time=0,
                                     price_open=req["price"], sl=req["sl"], tp=req["tp"], magic=req["magic"]))
        return NS(retcode=self.TRADE_RETCODE_DONE, comment="done", price=req["price"])


class Fixed(Strategy):
    name = "fixed"

    def __init__(self, direction):
        super().__init__()
        self.direction = direction

    def decide(self, bars, i):
        return Decision(self.direction, stop=0.5)


class MT5BrokerTest(unittest.TestCase):
    def test_lot_conversion(self):
        b = link.MT5Broker(FakeMT5(), "USDJPY", log=lambda m: None)
        self.assertEqual(b.unit_step, 1000)
        self.assertEqual(b.to_lots(20_000), 0.2)
        self.assertEqual(b.to_lots(20_999), 0.2)
        self.assertEqual(b.to_lots(500), 0.0)

    def test_open_sets_absolute_sl_and_close_uses_ticket(self):
        fake = FakeMT5()
        b = link.MT5Broker(fake, "USDJPY", log=lambda m: None)
        b.open(1, 20_000, stop=0.5, take=1.0)
        req = fake.requests[-1]
        self.assertEqual((req["type"], req["price"], req["sl"], req["tp"]), (0, 150.003, 149.503, 151.003))
        self.assertEqual(req["type_filling"], fake.ORDER_FILLING_IOC)
        pos = b.position()
        self.assertEqual((pos.direction, pos.units), (1, 20_000))
        b.close()
        self.assertEqual(fake.requests[-1]["position"], 1)
        self.assertEqual(fake.requests[-1]["type"], fake.ORDER_TYPE_SELL)
        self.assertIsNone(b.position())

    def test_ignores_manual_positions(self):
        fake = FakeMT5()
        fake.positions.append(NS(ticket=99, type=0, volume=1.0, time=0, price_open=150, sl=0, tp=0, magic=0))
        b = link.MT5Broker(fake, "USDJPY", log=lambda m: None)
        self.assertIsNone(b.position())
        b.close()
        self.assertEqual(fake.requests, [])

    def test_rejected_order_raises(self):
        fake = FakeMT5()
        fake.reject = True
        b = link.MT5Broker(fake, "USDJPY", log=lambda m: None)
        with self.assertRaises(link.MT5Error):
            b.open(1, 20_000, stop=0.5, take=None)

    def test_unknown_symbol(self):
        with self.assertRaises(link.MT5Error):
            link.MT5Broker(FakeMT5(), "USDJPY-", log=lambda m: None)

    def test_fetch_bars(self):
        bars = link.fetch_bars(FakeMT5(closes=[150, 151, 152]), "USDJPY", "H1", 2)
        self.assertEqual([b.close for b in bars], [151, 152])
        with self.assertRaises(link.MT5Error):
            link.fetch_bars(FakeMT5(), "USDJPY", "H2", 2)


class RunLiveTest(unittest.TestCase):
    def test_refuses_real_account(self):
        with self.assertRaises(link.MT5Error):
            link.run_live(FakeMT5(trade_mode=2), "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=lambda m: None)

    def test_once_opens_risk_sized_position(self):
        fake = FakeMT5()
        link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=lambda m: None)
        # 1% of 1,000,000 / 0.5 stop = 20,000 units = 0.2 lot
        self.assertEqual(fake.requests[-1]["volume"], 0.2)

    def test_acts_once_per_new_bar_and_reverses(self):
        fake = FakeMT5()
        strat = Fixed(1)
        polls = []

        def sleep(_):
            polls.append(1)
            if len(polls) == 2:          # a new bar closes and the strategy flips
                fake.closes.append(150.2)
                strat.direction = -1
            if len(polls) == 3:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            link.run_live(fake, "USDJPY", "H1", strat, RiskConfig(), log=lambda m: None, sleep=sleep)
        kinds = [("close" if "position" in r else "open", r["type"]) for r in fake.requests]
        self.assertEqual(kinds, [("open", 0), ("close", 1), ("open", 1)])

    def test_order_error_is_logged_not_fatal(self):
        fake = FakeMT5()
        fake.reject = True
        logs = []
        link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=logs.append)
        self.assertTrue(any("注文エラー" in m for m in logs))

    def test_drawdown_halt_closes(self):
        fake = FakeMT5()
        strat = Fixed(1)

        def sleep(_):
            fake.equity = 700_000
            fake.closes.append(149.0)

        link.run_live(fake, "USDJPY", "H1", strat, RiskConfig(), log=lambda m: None, sleep=sleep)
        self.assertIn("position", fake.requests[-1])
        self.assertEqual(fake.positions, [])


if __name__ == "__main__":
    unittest.main()

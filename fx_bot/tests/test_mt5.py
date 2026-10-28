"""MT5 link against an in-memory fake of the MetaTrader5 module."""

import csv
import tempfile
import unittest
from pathlib import Path
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

    deals = ()

    def history_deals_get(self, *span, position=None):
        return tuple(d for d in self.deals if position is None or getattr(d, "position_id", None) == position)

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

    def test_fills_csv_records_slippage(self):
        fake = FakeMT5()
        send = fake.order_send

        def slipping(req):                           # every fill 0.2 pips worse than asked
            res = send(req)
            res.price = round(req["price"] + (0.002 if req["type"] == fake.ORDER_TYPE_BUY else -0.002), 3)
            return res

        fake.order_send = slipping
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fills.csv"
            b = link.MT5Broker(fake, "USDJPY", log=lambda m: None, fills=path)
            b.open(1, 20_000, stop=0.5, take=None)
            b.close()
            with path.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual([r["action"] for r in rows], ["新規買い", "決済 (signal)"])
        self.assertEqual([float(r["slip_pips"]) for r in rows], [0.2, 0.2])
        self.assertEqual(float(rows[0]["spread_pips"]), 0.3)

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

    def test_custom_magic_tags_orders(self):
        fake = FakeMT5()
        link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=lambda m: None, magic=777)
        self.assertEqual(fake.requests[-1]["magic"], 777)

    def test_stay_awake_is_requested_and_released(self):
        calls = []
        original = link.keep_awake
        link.keep_awake = lambda on: calls.append(on) or True
        try:
            link.run_live(FakeMT5(), "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=lambda m: None,
                          stay_awake=True)
            link.run_live(FakeMT5(), "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=lambda m: None)
        finally:
            link.keep_awake = original
        self.assertEqual(calls, [True, False])

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

    def test_refused_order_is_retried_on_the_same_bar(self):
        fake = FakeMT5()
        fake.reject = True
        logs, polls = [], []

        def sleep(_):
            polls.append(1)
            if len(polls) == 2:          # the market reopens after the rollover
                fake.reject = False
            if len(polls) == 4:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), log=logs.append, sleep=sleep)
        self.assertEqual(len(fake.positions), 1)
        self.assertEqual(sum("注文エラー" in m for m in logs), 1)
        self.assertTrue(any("3 回目で通りました" in m for m in logs))

    def test_refused_order_gives_up_after_the_retry_window(self):
        fake = FakeMT5()
        fake.reject = True
        logs, polls = [], []
        original = link.ORDER_RETRY_FOR
        link.ORDER_RETRY_FOR = 15.0      # 3 tries at poll=5

        def sleep(_):
            polls.append(1)
            if len(polls) == 5:
                raise KeyboardInterrupt

        try:
            with self.assertRaises(KeyboardInterrupt):
                link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), log=logs.append, sleep=sleep)
        finally:
            link.ORDER_RETRY_FOR = original
        self.assertEqual(len(fake.requests), 3)   # no more tries until the next bar
        self.assertTrue(any("あきらめました" in m for m in logs))

    def test_drawdown_halt_closes(self):
        fake = FakeMT5()
        strat = Fixed(1)

        def sleep(_):
            fake.equity = 700_000
            fake.closes.append(149.0)

        link.run_live(fake, "USDJPY", "H1", strat, RiskConfig(), log=lambda m: None, sleep=sleep)
        self.assertIn("position", fake.requests[-1])
        self.assertEqual(fake.positions, [])

    def test_lost_connection_retries_and_relinks(self):
        fake = FakeMT5()
        rates = fake.copy_rates_from_pos
        down = {"left": 4}
        relinks, waits, logs = [], [], []

        def flaky(*a):
            if down["left"] > 0:
                down["left"] -= 1
                return None                  # what MT5 returns while the terminal is gone
            return rates(*a)

        def sleep(s):
            waits.append(s)
            if len(waits) == 6:
                raise KeyboardInterrupt

        fake.copy_rates_from_pos = flaky
        with self.assertRaises(KeyboardInterrupt):
            link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), log=logs.append, sleep=sleep,
                          relink=lambda: relinks.append(1) or True)
        self.assertEqual(len(relinks), 1)                     # after 3 failures in a row
        self.assertEqual(waits[:4], [10.0, 20.0, 40.0, 60.0])  # backoff, capped
        self.assertTrue(any("復旧" in m for m in logs))
        self.assertEqual(len(fake.requests), 1)               # traded once it came back

    def test_server_side_stop_is_logged_and_recorded(self):
        fake = FakeMT5()
        fake.DEAL_ENTRY_OUT, fake.DEAL_REASON_SL = 1, 4
        fake.history_deals_get = lambda position: (
            NS(entry=0, reason=0, volume=0.2, price=150.003, profit=0),
            NS(entry=1, reason=4, volume=0.2, price=149.498, profit=-10_100),
        )
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fills.csv"
            b = link.MT5Broker(fake, "USDJPY", log=logs.append, fills=path)
            b.open(1, 20_000, stop=0.5, take=None)
            b.check_server_exits()                    # sees the position
            fake.positions = []                       # the server hits the stop at 149.503 -> filled 149.498
            b.check_server_exits()
            with path.open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[-1]["action"], "損切り (MT5)")
        self.assertEqual(float(rows[-1]["requested"]), 149.503)
        self.assertEqual(float(rows[-1]["slip_pips"]), 0.5)
        self.assertTrue(any("損切り" in m for m in logs))


T0 = 1_700_000_000                       # 2023-11-14 22:13 (server time); bar k closes at T0 + k*3600


def deal(hours, profit, magic=link.MAGIC, symbol="USDJPY", **kw):
    return NS(time=T0 + hours * 3600, profit=profit, swap=0.0, commission=0.0, magic=magic, symbol=symbol,
              entry=1, reason=0, volume=0.2, price=150.0, **kw)


class LossLimitTest(unittest.TestCase):
    def broker(self, fake):
        return link.MT5Broker(fake, "USDJPY", log=lambda m: None)

    def test_day_limit_closes_and_pauses_until_next_day(self):
        fake = FakeMT5()
        b = self.broker(fake)
        b.open(1, 20_000, stop=0.5, take=None)
        fake.positions[0].profit = -6_000
        fake.deals = (deal(0, -5_000), deal(0, -50_000, magic=999))     # another bot's loss does not count
        lim, logs = link.LossLimit(day_pct=1.0), []
        now = link._server_time(T0)                                         # 11-14 22:13
        self.assertTrue(lim.check(b, now, logs.append))                     # 5,000 + 6,000 >= 10,000
        self.assertEqual(fake.positions, [])
        self.assertEqual(lim.paused_until, link._server_time(T0).replace(hour=0, minute=0, second=0) + link.timedelta(days=1))
        self.assertTrue(lim.check(b, now + link.timedelta(hours=1), logs.append))
        self.assertFalse(lim.check(b, lim.paused_until, logs.append))
        self.assertTrue(any("[日報] 2023-11-14 の確定損益 -5,000" in m for m in logs))
        self.assertTrue(any("[再開]" in m for m in logs))

    def test_under_limit_and_off(self):
        fake = FakeMT5()
        fake.deals = (deal(0, -9_000),)
        now = link._server_time(T0)
        self.assertFalse(link.LossLimit(day_pct=1.0).check(self.broker(fake), now, lambda m: None))
        fake.deals = (deal(0, -90_000),)
        self.assertFalse(link.LossLimit().check(self.broker(fake), now, lambda m: None))

    def test_week_limit_counts_earlier_days(self):
        fake = FakeMT5()
        fake.deals = (deal(-24, -12_000), deal(0, -9_000), deal(-24 * 3, -40_000))   # Mon, Tue / the Sat before
        lim, logs = link.LossLimit(day_pct=1.0, week_pct=2.0), []
        self.assertTrue(lim.check(self.broker(fake), link._server_time(T0), logs.append))
        self.assertEqual(lim.paused_until.weekday(), 0)                      # next Monday 00:00
        self.assertTrue(any("今週" in m for m in logs))

    def test_paused_bot_skips_new_entries(self):
        fake = FakeMT5()
        fake.deals = (deal(29, -20_000),)                                    # the last bar's day
        logs = []
        link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=logs.append,
                      limits=link.LossLimit(day_pct=1.0))
        self.assertEqual(fake.requests, [])
        self.assertTrue(any("損失上限で停止中" in m for m in logs))


class StateTest(unittest.TestCase):
    def test_state_written_each_poll_and_marked_stopped(self):
        fake = FakeMT5()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=lambda m: None, state=path)
            import json
            s = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(s["stopped"])
        self.assertEqual((s["symbol"], s["magic"]), ("USDJPY", link.MAGIC))
        self.assertEqual(len(s["positions"]), 1)
        self.assertEqual(s["positions"][0]["sl"], 149.503)

    def test_restart_reports_stop_hit_while_away_and_restores_pause(self):
        fake = FakeMT5()
        fake.DEAL_ENTRY_OUT, fake.DEAL_REASON_SL = 1, 4
        fake.deals = (NS(position_id=7, entry=1, reason=4, volume=0.2, price=149.49, profit=-10_200,
                         time=T0, magic=link.MAGIC, symbol="USDJPY", swap=0.0, commission=0.0),)
        fake.positions.append(NS(ticket=99, type=0, volume=1.0, time=0, price_open=150, sl=0, tp=0, magic=0))
        logs = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            import json
            path.write_text(json.dumps({
                "updated": "2023-11-14T20:00:00", "paused_until": "2099-01-01T00:00:00",
                "positions": [{"ticket": 7, "type": 0, "volume": 0.2, "price_open": 150.0, "sl": 149.5, "tp": 0}],
            }), encoding="utf-8")
            link.run_live(fake, "USDJPY", "H1", Fixed(1), RiskConfig(), once=True, log=logs.append, state=path)
        self.assertTrue(any("損切り (MT5)" in m and "-10,200" in m for m in logs))
        self.assertTrue(any("停止を引き継ぎ" in m for m in logs))
        self.assertTrue(any("目印の違うポジションが 1 件" in m for m in logs))
        self.assertEqual(fake.requests, [])                                  # still paused

    def test_warns_about_position_without_stop(self):
        fake = FakeMT5()
        fake.positions.append(NS(ticket=5, type=1, volume=0.1, time=0, price_open=150, sl=0, tp=0, magic=link.MAGIC))
        logs = []
        link.reconcile(link.MT5Broker(fake, "USDJPY", log=logs.append), None, link.LossLimit(), logs.append)
        self.assertTrue(any("引き継ぎ: 売り 0.1 lot" in m for m in logs))
        self.assertTrue(any("損切りが置かれていない" in m for m in logs))


if __name__ == "__main__":
    unittest.main()

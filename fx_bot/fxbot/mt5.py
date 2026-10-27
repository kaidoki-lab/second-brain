"""MetaTrader 5 connection: history export and a live Broker.

Needs the MT5 terminal running on the same Windows PC and
`pip install MetaTrader5`. The module object is injected so tests can
pass a fake; real callers use `connect()`.
"""

from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .backtest import step
from .broker import Broker, Position, Trade
from .data import Bar
from .risk import DrawdownGuard, RiskConfig, pip_size
from .strategy import Strategy

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")
MAGIC = 21_0001          # tags orders from this bot so manual trades are never touched


class MT5Error(RuntimeError):
    pass


def connect(terminal: str | None = None) -> Any:
    try:
        import MetaTrader5 as mt5  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MT5Error("MetaTrader5 パッケージがありません。`pip install MetaTrader5` を実行してください (Windows のみ)") from exc
    ok = mt5.initialize(path=terminal) if terminal else mt5.initialize()
    if not ok:
        raise MT5Error(f"MT5 に接続できません: {mt5.last_error()}  (MT5 を起動してログインしているか確認してください)")
    return mt5


def account_summary(mt5: Any) -> str:
    acc = mt5.account_info()
    kind = {mt5.ACCOUNT_TRADE_MODE_DEMO: "デモ", mt5.ACCOUNT_TRADE_MODE_REAL: "リアル"}.get(acc.trade_mode, "コンテスト")
    return f"口座 {acc.login} ({acc.server}) [{kind}]  残高 {acc.balance:,.0f} {acc.currency}  有効証拠金 {acc.equity:,.0f}"


def is_demo(mt5: Any) -> bool:
    return mt5.account_info().trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO


def _symbol(mt5: Any, symbol: str) -> Any:
    info = mt5.symbol_info(symbol)
    if info is None:
        raise MT5Error(f"銘柄 {symbol!r} が見つかりません。業者によっては USDJPY- や USDJPY.m のような名前です (気配値表示で確認)")
    if not info.visible and not mt5.symbol_select(symbol, True):
        raise MT5Error(f"銘柄 {symbol!r} を気配値表示に追加できません")
    return info


def fetch_bars(mt5: Any, symbol: str, timeframe: str, count: int) -> list[Bar]:
    """The last `count` CLOSED bars (the still-forming bar is excluded)."""
    if timeframe not in TIMEFRAMES:
        raise MT5Error(f"時間足は {', '.join(TIMEFRAMES)} のどれかです")
    _symbol(mt5, symbol)
    rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, "TIMEFRAME_" + timeframe), 1, count)
    if rates is None or len(rates) == 0:
        raise MT5Error(f"{symbol} {timeframe} の価格を取得できません: {mt5.last_error()}")
    return [
        Bar(
            time=datetime.fromtimestamp(int(r["time"]), timezone.utc).replace(tzinfo=None),   # broker server time
            open=float(r["open"]), high=float(r["high"]), low=float(r["low"]), close=float(r["close"]),
            volume=float(r["tick_volume"]),
        )
        for r in rates
    ]


FILL_FIELDS = ("time", "symbol", "action", "volume", "bid", "ask", "requested", "filled", "slip_pips", "spread_pips")


class MT5Broker(Broker):
    """Market orders with server-side SL/TP. Only sees positions carrying our magic number.

    With `fills`, every market fill is appended to that CSV with the price asked
    for and the price got, so live slippage can be compared with the backtest's.
    `slip_pips` is positive when the fill was worse than requested. Stops and
    targets filled by the server are picked up by `check_server_exits()`.
    """

    def __init__(self, mt5: Any, symbol: str, magic: int = MAGIC, deviation: int = 20,
                 log: Callable[[str], None] = print, fills: str | Path | None = None) -> None:
        self.mt5 = mt5
        self.symbol = symbol
        self.magic = magic
        self.deviation = deviation
        self.log = log
        self.fills = Path(fills) if fills else None
        self.info = _symbol(mt5, symbol)
        self.contract = self.info.trade_contract_size
        self._known: dict[int, Any] = {}     # our open positions as last seen, by ticket

    @property
    def unit_step(self) -> int:
        """Smallest tradable size in currency units (e.g. 0.01 lot x 100,000 = 1,000)."""
        return max(int(round(self.info.volume_step * self.contract)), 1)

    def to_lots(self, units: int) -> float:
        step = self.info.volume_step
        lots = int(units / self.contract / step + 1e-9) * step
        return round(lots, 8) if lots >= self.info.volume_min else 0.0

    def equity(self) -> float:
        return float(self.mt5.account_info().equity)

    def _mine(self) -> list[Any]:
        return [p for p in (self.mt5.positions_get(symbol=self.symbol) or ()) if p.magic == self.magic]

    def position(self) -> Position | None:
        mine = self._mine()
        if not mine:
            return None
        p = mine[0]
        return Position(
            direction=1 if p.type == self.mt5.POSITION_TYPE_BUY else -1,
            units=int(round(sum(x.volume for x in mine) * self.contract)),
            entry_time=datetime.fromtimestamp(int(p.time), timezone.utc).replace(tzinfo=None),
            entry_price=p.price_open,
            stop_price=p.sl or None,
            take_price=p.tp or None,
        )

    def _filling(self) -> int:
        mode = self.info.filling_mode
        if mode & 1:
            return self.mt5.ORDER_FILLING_FOK
        if mode & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _send(self, request: dict[str, Any], what: str) -> None:
        request = {
            "action": self.mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "deviation": self.deviation,
            "magic": self.magic, "comment": "fxbot", "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(), **request,
        }
        tick = self.mt5.symbol_info_tick(self.symbol)
        result = self.mt5.order_send(request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            detail = f"{result.retcode} {result.comment}" if result is not None else str(self.mt5.last_error())
            raise MT5Error(f"{what} に失敗: {detail}")
        self.log(f"{what}: {request['volume']} lot @ {result.price}")
        self._record_fill(what, request["type"] == self.mt5.ORDER_TYPE_BUY, request["volume"],
                          request["price"], result.price, tick)

    def _record_fill(self, what: str, buy: bool, volume: float, requested: float, filled: float,
                     tick: Any = None) -> None:
        if self.fills is None:
            return
        pip = pip_size(self.symbol)
        sign = 1 if buy else -1                  # paying more on a buy / getting less on a sell is worse
        bid, ask = (tick.bid, tick.ask) if tick is not None else ("", "")
        spread = round((tick.ask - tick.bid) / pip, 2) if tick is not None else ""
        row = (f"{datetime.now():%Y-%m-%d %H:%M:%S}", self.symbol, what, volume, bid, ask,
               requested, filled, round(sign * (filled - requested) / pip, 2), spread)
        new = not self.fills.exists()
        self.fills.parent.mkdir(parents=True, exist_ok=True)
        with self.fills.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(FILL_FIELDS)
            w.writerow(row)

    def open(self, direction: int, units: int, stop: float | None, take: float | None) -> None:
        lots = self.to_lots(units)
        if lots <= 0:
            self.log(f"見送り: 計算した数量 {units} 通貨が最小ロット未満です")
            return
        tick = self.mt5.symbol_info_tick(self.symbol)
        price = tick.ask if direction > 0 else tick.bid
        digits = self.info.digits
        self._send({
            "volume": lots,
            "type": self.mt5.ORDER_TYPE_BUY if direction > 0 else self.mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": round(price - direction * stop, digits) if stop else 0.0,
            "tp": round(price + direction * take, digits) if take else 0.0,
        }, "新規買い" if direction > 0 else "新規売り")

    def close(self, reason: str = "signal") -> None:
        for p in self._mine():
            tick = self.mt5.symbol_info_tick(self.symbol)
            buy = p.type == self.mt5.POSITION_TYPE_BUY
            self._send({
                "volume": p.volume,
                "type": self.mt5.ORDER_TYPE_SELL if buy else self.mt5.ORDER_TYPE_BUY,
                "price": tick.bid if buy else tick.ask,
                "position": p.ticket,
            }, f"決済 ({reason})")
            self._known.pop(p.ticket, None)

    def check_server_exits(self) -> None:
        """Log and record positions the server closed since the last check (stop / target hit)."""
        current = {p.ticket: p for p in self._mine()}
        for ticket, p in self._known.items():
            if ticket in current:
                continue
            deals = self.mt5.history_deals_get(position=ticket) or ()
            for d in deals:
                if d.entry != getattr(self.mt5, "DEAL_ENTRY_OUT", 1):
                    continue
                if d.reason == getattr(self.mt5, "DEAL_REASON_SL", 4) and p.sl:
                    what, requested = "損切り (MT5)", p.sl
                elif d.reason == getattr(self.mt5, "DEAL_REASON_TP", 5) and p.tp:
                    what, requested = "利確 (MT5)", p.tp
                else:
                    what, requested = "決済 (MT5側)", d.price
                self.log(f"{what}: {d.volume} lot @ {d.price}  損益 {d.profit:+,.0f}")
                self._record_fill(what, p.type != self.mt5.POSITION_TYPE_BUY, d.volume, requested, d.price)
        self._known = current


def live_trades(mt5: Any, symbol: str, since: datetime, magic: int = MAGIC) -> list[Trade]:
    """This bot's closed trades from the account history (times are broker server time)."""
    def server_time(d: Any) -> datetime:
        return datetime.fromtimestamp(int(d.time), timezone.utc).replace(tzinfo=None)

    deals = mt5.history_deals_get(datetime(2000, 1, 1), datetime.now() + timedelta(days=2)) or ()
    by_pos: dict[int, list[Any]] = {}
    for d in deals:
        if d.symbol == symbol and d.magic == magic:
            by_pos.setdefault(d.position_id, []).append(d)
    out_entry = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    reasons = {getattr(mt5, "DEAL_REASON_SL", 4): "stop", getattr(mt5, "DEAL_REASON_TP", 5): "take"}
    trades = []
    for ds in by_pos.values():
        ins = [d for d in ds if d.entry != out_entry]
        outs = [d for d in ds if d.entry == out_entry]
        if not ins or not outs or server_time(ins[0]) < since:
            continue
        first, last = ins[0], outs[-1]
        contract = mt5.symbol_info(symbol).trade_contract_size
        trades.append(Trade(
            direction=1 if first.type == mt5.ORDER_TYPE_BUY else -1,
            units=int(round(first.volume * contract)),
            entry_time=server_time(first), entry_price=first.price,
            exit_time=server_time(last), exit_price=last.price,
            pnl=sum(d.profit for d in outs), reason=reasons.get(last.reason, "signal"),
        ))
    return sorted(trades, key=lambda t: t.entry_time)


def keep_awake(on: bool) -> bool:
    """Ask Windows not to idle-sleep while the bot runs (the display may still turn off).

    Only a request held by this process: no power setting is changed, and it ends
    with the process. Closing a laptop lid or a manual sleep still stops the bot.
    """
    try:
        import ctypes
        es_continuous, es_system_required = 0x80000000, 0x00000001
        flags = es_continuous | (es_system_required if on else 0)
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def run_live(
    mt5: Any,
    symbol: str,
    timeframe: str,
    strategy: Strategy,
    risk: RiskConfig,
    history: int = 1000,
    poll: float = 5.0,
    allow_real: bool = False,
    once: bool = False,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    fills: str | Path | None = None,
    stay_awake: bool = False,
    relink: Callable[[], bool] | None = None,
    magic: int = MAGIC,
) -> None:
    """Evaluate the strategy each time a new bar closes, until Ctrl+C or the drawdown halt."""
    if not is_demo(mt5) and not allow_real:
        raise MT5Error("リアル口座です。安全のため停止しました (どうしても動かす場合のみ --allow-real)")
    broker = MT5Broker(mt5, symbol, magic=magic, log=log, fills=fills)
    risk.lot_step = broker.unit_step
    guard = DrawdownGuard(risk.max_drawdown_pct)
    log(account_summary(mt5))
    log(f"{strategy.describe()}  {symbol} {timeframe}  開始 (Ctrl+C で停止。ポジションはそのまま残ります)")
    if magic != MAGIC:
        log(f"注文の目印 (マジックナンバー) {magic}")
    if strategy.name == "carry":
        log(f"業者のスワップ (MT5 の表示値): 買い {getattr(broker.info, 'swap_long', '?')} / "
            f"売り {getattr(broker.info, 'swap_short', '?')}  ※ 受け取れる側と carry の方向が合っているか確認してください")
    if stay_awake:
        log("動作中は PC をスリープさせません" if keep_awake(True)
            else "[注意] スリープ抑止を設定できませんでした。PC がスリープすると止まります")
    try:
        _loop(mt5, symbol, timeframe, strategy, risk, broker, guard, history, poll, once, log, sleep,
              relink or (lambda: reconnect(mt5)), allow_real)
    finally:
        if stay_awake:
            keep_awake(False)


RECONNECT_AFTER = 3          # consecutive failed polls before re-initializing the terminal link
MAX_BACKOFF = 60.0           # seconds between retries while MT5 is unreachable


def reconnect(mt5: Any, terminal: str | None = None) -> bool:
    try:
        mt5.shutdown()
    except Exception:  # noqa: BLE001 - a dead link may fail to shut down; we re-initialize anyway
        pass
    return bool(mt5.initialize(path=terminal) if terminal else mt5.initialize())


def _loop(mt5: Any, symbol: str, timeframe: str, strategy: Strategy, risk: RiskConfig, broker: MT5Broker,
          guard: DrawdownGuard, history: int, poll: float, once: bool,
          log: Callable[[str], None], sleep: Callable[[float], None],
          relink: Callable[[], bool], allow_real: bool) -> None:
    """Poll for closed bars. Errors (MT5 restarting, a dropped connection) are logged and
    retried with backoff instead of ending the run; after a few in a row the link is re-initialized."""
    last_seen: datetime | None = None
    failures = 0
    while True:
        try:
            broker.check_server_exits()
            bars = fetch_bars(mt5, symbol, timeframe, history)
            if bars[-1].time != last_seen:
                if guard.update(broker.equity()):
                    log(f"有効証拠金が開始後の最高値から {risk.max_drawdown_pct}% 減ったため、全決済して停止します")
                    broker.close("halt")
                    return
                before = broker.position()
                try:
                    step(broker, strategy, bars, len(bars) - 1, risk)
                except MT5Error as exc:
                    log(f"[注文エラー] {exc}")
                last_seen = bars[-1].time
                after = broker.position()
                state = "ノーポジ" if after is None else f"{'買い' if after.direction > 0 else '売り'} {after.units:,}通貨"
                log(f"{last_seen} 確定 終値 {bars[-1].close}  → {state}" + ("" if before == after else " (変更)"))
            if failures:
                log(f"[復旧] MT5 との通信が戻りました ({failures} 回失敗のあと)")
            failures = 0
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:  # noqa: BLE001 - keep the bot alive; the stop order is on the server anyway
            failures += 1
            log(f"[接続エラー] {type(exc).__name__}: {exc}  ({failures} 回目)")
            if failures % RECONNECT_AFTER == 0:
                ok = relink()
                log("MT5 に再接続しました" if ok else f"MT5 に再接続できません: {mt5.last_error()}")
                if ok and not allow_real and not is_demo(mt5):
                    raise MT5Error("再接続先がリアル口座です。安全のため停止しました") from exc
            if once:
                raise
            sleep(min(poll * 2 ** min(failures, 6), MAX_BACKOFF))
            continue
        if once:
            return
        sleep(poll)

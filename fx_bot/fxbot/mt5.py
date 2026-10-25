"""MetaTrader 5 connection: history export and a live Broker.

Needs the MT5 terminal running on the same Windows PC and
`pip install MetaTrader5`. The module object is injected so tests can
pass a fake; real callers use `connect()`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from .backtest import step
from .broker import Broker, Position
from .data import Bar
from .risk import DrawdownGuard, RiskConfig
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


class MT5Broker(Broker):
    """Market orders with server-side SL/TP. Only sees positions carrying our magic number."""

    def __init__(self, mt5: Any, symbol: str, magic: int = MAGIC, deviation: int = 20,
                 log: Callable[[str], None] = print) -> None:
        self.mt5 = mt5
        self.symbol = symbol
        self.magic = magic
        self.deviation = deviation
        self.log = log
        self.info = _symbol(mt5, symbol)
        self.contract = self.info.trade_contract_size

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
        result = self.mt5.order_send(request)
        if result is None or result.retcode != self.mt5.TRADE_RETCODE_DONE:
            detail = f"{result.retcode} {result.comment}" if result is not None else str(self.mt5.last_error())
            raise MT5Error(f"{what} に失敗: {detail}")
        self.log(f"{what}: {request['volume']} lot @ {result.price}")

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
) -> None:
    """Evaluate the strategy each time a new bar closes, until Ctrl+C or the drawdown halt."""
    if not is_demo(mt5) and not allow_real:
        raise MT5Error("リアル口座です。安全のため停止しました (どうしても動かす場合のみ --allow-real)")
    broker = MT5Broker(mt5, symbol, log=log)
    risk.lot_step = broker.unit_step
    guard = DrawdownGuard(risk.max_drawdown_pct)
    log(account_summary(mt5))
    log(f"{strategy.describe()}  {symbol} {timeframe}  開始 (Ctrl+C で停止。ポジションはそのまま残ります)")

    last_seen: datetime | None = None
    while True:
        bars = fetch_bars(mt5, symbol, timeframe, history)
        if bars[-1].time != last_seen:
            last_seen = bars[-1].time
            if guard.update(broker.equity()):
                log(f"有効証拠金が開始後の最高値から {risk.max_drawdown_pct}% 減ったため、全決済して停止します")
                broker.close("halt")
                return
            before = broker.position()
            try:
                step(broker, strategy, bars, len(bars) - 1, risk)
            except MT5Error as exc:
                log(f"[注文エラー] {exc}")
            after = broker.position()
            state = "ノーポジ" if after is None else f"{'買い' if after.direction > 0 else '売り'} {after.units:,}通貨"
            log(f"{last_seen} 確定 終値 {bars[-1].close}  → {state}" + ("" if before == after else " (変更)"))
        if once:
            return
        sleep(poll)

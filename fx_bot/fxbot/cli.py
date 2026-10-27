"""Command line: sample / strategies / backtest / optimize / fetch / live / compare."""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from . import backtest, data, metrics, strategy, swap
from .mt5 import MAGIC, TIMEFRAMES, MT5Error
from .risk import RiskConfig, pip_size


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv", required=True, help="価格データ (time,open,high,low,close / MT5エクスポート形式)")
    p.add_argument("--symbol", default="USDJPY", help="通貨ペア (pipサイズの判定に使用)")
    p.add_argument("--spread", type=float, default=0.3, help="スプレッド (pips)")
    p.add_argument("--slippage", type=float, default=0.0, help="成行・損切りの約定が不利にずれる幅 (pips)")
    p.add_argument("--equity", type=float, default=1_000_000, help="初期資金 (口座通貨)")
    p.add_argument("--swap", action="store_true",
                   help="政策金利表から推定したスワップを損益に入れる (carry では常に入れる)")
    p.add_argument("--swap-cut", type=float, default=1.0, help="スワップから業者が取る分 (年率%%、買い売りとも)")
    _trading(p)


def _trading(p: argparse.ArgumentParser) -> None:
    p.add_argument("--strategy", default="ma_cross", choices=sorted(strategy.STRATEGIES))
    p.add_argument("--risk", type=float, default=1.0, help="1取引で許容する損失 (資金の%%)")
    p.add_argument("--leverage", type=float, default=25.0, help="最大レバレッジ")
    p.add_argument("--max-dd", type=float, default=20.0, help="この%%を超えて資金が減ったら停止")
    p.add_argument("--quote-rate", type=float, default=1.0,
                   help="決済通貨→口座通貨のレート (例: EURUSD を円口座なら USDJPY のレート)")


def _risk(args: argparse.Namespace) -> RiskConfig:
    return RiskConfig(risk_pct=args.risk, max_leverage=args.leverage,
                      max_drawdown_pct=args.max_dd, quote_to_account=args.quote_rate)


def _uses_swap(args: argparse.Namespace) -> bool:
    return args.swap or args.strategy == "carry"


def _run(args: argparse.Namespace, bars: list[data.Bar], params: dict[str, float]) -> backtest.Result:
    strat = strategy.build(args.strategy, params, args.symbol)
    rates = swap.estimator(args.symbol, args.swap_cut) if _uses_swap(args) else None
    return backtest.run(bars, strat, _risk(args), args.equity,
                        args.spread * pip_size(args.symbol), args.slippage * pip_size(args.symbol), rates)


def _pad(text: str, width: int) -> str:
    """ljust that counts full-width characters as two columns."""
    used = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(width - used, 1)


def _print_summary(stats: dict[str, float]) -> None:
    for key, label in metrics.LABELS.items():
        v = stats[key]
        text = f"{v:,.0f}" if key in ("final_equity", "avg_win", "avg_loss", "expectancy") else (
            f"{v:,.2f}" if isinstance(v, float) else str(v))
        print(f"  {_pad(label, 24)}{text}")


def cmd_sample(args: argparse.Namespace) -> int:
    bars = data.synthetic(n=args.bars, seed=args.seed, start=args.start)
    data.write_csv(args.out, bars)
    print(f"合成データを {len(bars)} 本書き出しました: {args.out}")
    print("  ※ ランダムな値です。配線確認用で、ここでの成績に意味はありません。")
    return 0


def cmd_strategies(args: argparse.Namespace) -> int:
    for name, cls in strategy.STRATEGIES.items():
        defaults = ",".join(f"{k}={v}" for k, v in cls.params.items())
        print(f"{name:<10} {cls.summary}")
        print(f"{'':<10} 既定値: {defaults}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    bars = data.load_csv(args.csv)
    result = _run(args, bars, strategy.parse_params(args.params))
    print(f"{result.strategy}  {args.symbol}  {bars[0].time} 〜 {bars[-1].time}  ({len(bars)}本)")
    if result.halted_at:
        print(f"  !! 最大ドローダウン {args.max_dd}% に達したため {result.halted_at} で停止しました")
    _print_summary(metrics.summarize(result))
    if _uses_swap(args):
        total = sum(t.swap for t in result.trades)
        print(f"  {_pad('うちスワップ(推定)', 24)}{total:,.0f}  (業者の取り分 年{args.swap_cut}% を引いた値)")
    if args.trades:
        path = Path(args.trades)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["direction", "units", "entry_time", "entry_price", "exit_time", "exit_price", "pnl", "reason",
                        "swap"])
            for t in result.trades:
                w.writerow(["long" if t.direction > 0 else "short", t.units, t.entry_time, round(t.entry_price, 6),
                            t.exit_time, round(t.exit_price, 6), round(t.pnl, 2), t.reason, round(t.swap, 2)])
        print(f"  取引履歴: {path}")
    return 0


def cmd_optimize(args: argparse.Namespace) -> int:
    """Grid search on the first part of the data, then re-test the best on the rest."""
    bars = data.load_csv(args.csv)
    cut = int(len(bars) * args.split)
    train, test = bars[:cut], bars[cut:]
    grid: dict[str, list[float]] = {}
    for item in args.grid:
        key, _, values = item.partition("=")
        grid[key] = [float(v) for v in values.split(",")]
    keys = list(grid)
    rows = []
    for combo in itertools.product(*grid.values()):
        params = dict(zip(keys, combo))
        if args.strategy == "ma_cross" and params.get("fast", 0) >= params.get("slow", float("inf")):
            continue
        stats = metrics.summarize(_run(args, train, params))
        rows.append((params, stats))
    rows.sort(key=lambda r: r[1]["return_pct"], reverse=True)

    print(f"学習期間 {train[0].time} 〜 {train[-1].time} / 検証期間 {test[0].time} 〜 {test[-1].time}")
    print(f"{'パラメータ':<28}{'学習 損益%':>11}{'学習 DD%':>10}{'検証 損益%':>11}{'検証 DD%':>10}{'検証 取引':>9}")
    for params, stats in rows[:args.top]:
        oos = metrics.summarize(_run(args, test, params))
        label = ",".join(f"{k}={v:g}" for k, v in params.items())
        print(f"{label:<28}{stats['return_pct']:>11.2f}{stats['max_drawdown_pct']:>10.2f}"
              f"{oos['return_pct']:>11.2f}{oos['max_drawdown_pct']:>10.2f}{oos['trades']:>9}")
    print("  ※ 学習で良くても検証で崩れるものは過剰最適化の疑いが強いです。")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from . import mt5 as mt5link

    mt5 = mt5link.connect(args.terminal)
    try:
        bars = mt5link.fetch_bars(mt5, args.symbol, args.timeframe, args.bars)
    finally:
        mt5.shutdown()
    out = args.out or f"data/{args.symbol}_{args.timeframe}.csv"
    data.write_csv(out, bars)
    print(f"{args.symbol} {args.timeframe} を {len(bars)} 本保存しました: {out}  ({bars[0].time} 〜 {bars[-1].time}, サーバー時刻)")
    if len(bars) < args.bars:
        print("  ※ 要求より少ない場合は MT5 の ツール→オプション→チャート「チャートの最大バー数」を増やしてください")
    return 0


NOTIFY_KEYS = ("新規", "決済", "損切り", "利確", "エラー", "停止", "再接続", "復旧", "注意", "日報", "再開")


def _notify(url: str, text: str) -> None:
    """POST one line to a push service such as ntfy.sh. Runs in a thread; failures are ignored."""
    import threading
    import urllib.request

    def send() -> None:
        try:
            urllib.request.urlopen(urllib.request.Request(url, data=text.encode("utf-8"), method="POST"), timeout=10)
        except Exception:  # noqa: BLE001 - a missed notification must never stop trading
            pass

    threading.Thread(target=send, daemon=True).start()


def _live_logger(log_dir: str | None, notify_url: str | None):
    """Console line + data/live_YYYYMMDD.log line; trade/error lines also pushed to `notify_url`."""
    def log(msg: str) -> None:
        now = datetime.now()
        line = f"[{now:%m-%d %H:%M:%S}] {msg}"
        print(line, flush=True)
        if log_dir:
            path = Path(log_dir) / f"live_{now:%Y%m%d}.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if notify_url and any(k in msg for k in NOTIFY_KEYS):
            _notify(notify_url, msg)
    return log


def _pinger(url: str | None, every: float = 300.0):
    """GET `url` at most every `every` seconds (a dead-man's switch such as healthchecks.io)."""
    if not url:
        return None
    import time
    last = [0.0]

    def ping() -> None:
        if time.monotonic() - last[0] >= every:
            last[0] = time.monotonic()
            _notify(url, "")
    return ping


def cmd_watch(args: argparse.Namespace) -> int:
    from .watch import run_watch

    log = _live_logger(args.log_dir or None, args.notify)
    try:
        run_watch(args.dir, args.stale, args.interval, log, once=args.once)
    except KeyboardInterrupt:
        print("見張りを止めました。")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    import time

    from . import mt5 as mt5link

    strat = strategy.build(args.strategy, strategy.parse_params(args.params), args.symbol)
    log = _live_logger(args.log_dir or None, args.notify)
    while True:
        try:
            mt5 = mt5link.connect(args.terminal)
            break
        except MT5Error as exc:
            if args.once:
                raise
            log(f"[接続エラー] {exc}  60秒後にもう一度試します")
            time.sleep(60)
    state = args.state if args.state is not None else str(Path(args.log_dir or "data") / f"state_{args.symbol}_{args.magic}.json")
    try:
        mt5link.run_live(mt5, args.symbol, args.timeframe, strat, _risk(args),
                         history=args.history, poll=args.poll, allow_real=args.allow_real, once=args.once,
                         log=log,
                         fills=args.fills if args.fills is not None else f"data/fills_{args.symbol}.csv",
                         stay_awake=not args.once, relink=lambda: mt5link.reconnect(mt5, args.terminal),
                         magic=args.magic, limits=mt5link.LossLimit(args.max_day_loss, args.max_week_loss),
                         state=state or None, heartbeat=_pinger(args.heartbeat_url))
    except KeyboardInterrupt:
        print("停止しました。保有中のポジションは MT5 上にそのまま残っています (損切り注文は有効)。")
    finally:
        mt5.shutdown()
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from . import compare
    from . import mt5 as mt5link

    since = datetime.strptime(args.since, "%Y-%m-%d")
    strat = strategy.build(args.strategy, strategy.parse_params(args.params), args.symbol)
    mt5 = mt5link.connect(args.terminal)
    try:
        bars = mt5link.fetch_bars(mt5, args.symbol, args.timeframe, args.history)
        live = mt5link.live_trades(mt5, args.symbol, since, args.magic)
    finally:
        mt5.shutdown()
    pip = pip_size(args.symbol)
    result = backtest.run(bars, strat, _risk(args), args.equity, args.spread * pip, args.slippage * pip)
    test = [t for t in result.trades if t.entry_time >= since and t.reason != "end"]
    pairs = compare.match(live, test)

    print(f"{strat.describe()}  {args.symbol} {args.timeframe}  {since:%Y-%m-%d} 以降 (サーバー時刻)")
    print(f"バックテストの前提: スプレッド {args.spread} pips / 滑り {args.slippage} pips\n")
    print(f"{'エントリー':<17}{'方向':<4}{'実 入→出':>22}{'BT 入→出':>22}{'入り差':>8}{'出口差':>8}{'実pips':>8}{'BTpips':>8}  決済")
    for p in pairs:
        lt, bt = p.live, p.test
        side = "買い" if (lt or bt).direction > 0 else "売り"
        fmt = lambda t: f"{t.entry_price:.3f}→{t.exit_price:.3f}" if t else "なし"  # noqa: E731
        num = lambda v: f"{v:+.1f}" if v is not None else "-"  # noqa: E731
        print(f"{p.time:%m-%d %H:%M}      {side:<4}{fmt(lt):>22}{fmt(bt):>22}{num(p.entry_gap(pip)):>8}"
              f"{num(p.exit_gap(pip)):>8}{num(compare.pips(lt, pip) if lt else None):>8}"
              f"{num(compare.pips(bt, pip) if bt else None):>8}  {(lt or bt).reason}")
    both = [p for p in pairs if p.live and p.test]
    print(f"\n一致 {len(both)} 件 / 実だけ {sum(p.test is None for p in pairs)} 件 / バックテストだけ {sum(p.live is None for p in pairs)} 件")
    if both:
        avg = lambda xs: sum(xs) / len(xs)  # noqa: E731
        print(f"入りの差 平均 {avg([p.entry_gap(pip) for p in both]):+.2f} pips / "
              f"出口の差 平均 {avg([p.exit_gap(pip) for p in both]):+.2f} pips (プラス = 実際の方が不利)")
    if any(p.live is None or p.test is None for p in pairs):
        print("※ 片方だけの取引は、判断のずれ（データ・時刻・起動していなかった時間）を疑ってください")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="run.py", description="FX 自動売買 検証基盤")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sample", help="配線確認用の合成データを作る")
    p.add_argument("--out", default="data/sample_usdjpy_h1.csv")
    p.add_argument("--bars", type=int, default=5000)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--start", type=float, default=150.0)
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("strategies", help="使える戦略とパラメータの一覧")
    p.set_defaults(func=cmd_strategies)

    p = sub.add_parser("backtest", help="1つの設定でバックテスト")
    _common(p)
    p.add_argument("--params", help="例: fast=20,slow=80,sl_atr=2")
    p.add_argument("--trades", help="取引履歴をCSVで保存するパス")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("optimize", help="パラメータ総当たり + 期間外検証")
    _common(p)
    p.add_argument("--grid", nargs="+", required=True, help="例: fast=10,20,30 slow=50,100")
    p.add_argument("--split", type=float, default=0.7, help="学習に使う割合 (残りで検証)")
    p.add_argument("--top", type=int, default=10)
    p.set_defaults(func=cmd_optimize)

    def _mt5(p: argparse.ArgumentParser) -> None:
        p.add_argument("--symbol", default="USDJPY", help="MT5 上の銘柄名 (業者により USDJPY- など)")
        p.add_argument("--timeframe", default="H1", choices=TIMEFRAMES)
        p.add_argument("--terminal", help="terminal64.exe のパス (自動で見つからない時だけ)")

    def _magic(p: argparse.ArgumentParser) -> None:
        p.add_argument("--magic", type=int, default=MAGIC,
                       help=f"注文の目印 (既定 {MAGIC})。同じ口座で別の戦略を動かす時は戦略ごとに変える")

    p = sub.add_parser("fetch", help="MT5 から過去データをCSVに保存")
    _mt5(p)
    p.add_argument("--bars", type=int, default=50_000)
    p.add_argument("--out", help="保存先 (既定: data/<銘柄>_<時間足>.csv)")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("live", help="MT5 デモ口座で自動売買")
    _mt5(p)
    _magic(p)
    _trading(p)
    p.add_argument("--params", help="例: fast=20,slow=80,sl_atr=2")
    p.add_argument("--history", type=int, default=1000, help="判断に使う足の本数")
    p.add_argument("--poll", type=float, default=5.0, help="新しい足の確認間隔 (秒)")
    p.add_argument("--once", action="store_true", help="1回だけ判断して終了 (動作確認用)")
    p.add_argument("--allow-real", action="store_true", help="リアル口座でも動かす (非推奨)")
    p.add_argument("--fills", help="約定記録CSV (既定: data/fills_<銘柄>.csv、\"\" で記録しない)")
    p.add_argument("--log-dir", default="data", help="動作ログの保存先 (live_YYYYMMDD.log。\"\" で保存しない)")
    p.add_argument("--notify", help="売買・エラーを送る通知URL (例: https://ntfy.sh/<自分だけのトピック名>)。既定は送らない")
    p.add_argument("--max-day-loss", type=float, default=0.0,
                   help="この目印の1日の損失が残高のこの%%に達したら決済し、翌日(サーバー時刻)まで新規を止める (0 で無効)")
    p.add_argument("--max-week-loss", type=float, default=0.0, help="同じく1週間 (月曜始まり) の上限%% (0 で無効)")
    p.add_argument("--state", help="状態ファイル (既定: <log-dir>/state_<銘柄>_<目印>.json、\"\" で書かない)。watch と再起動時の照合に使う")
    p.add_argument("--heartbeat-url", help="5分おきにアクセスするURL (healthchecks.io など。途絶えたら先方が知らせる)")
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("watch", help="live の状態ファイルを見張り、更新が止まったボットを知らせる")
    p.add_argument("--dir", default="data", help="state_*.json を探すフォルダ (下の階層も見る)")
    p.add_argument("--stale", type=float, default=10.0, help="この分数更新がなければ停止の疑いとする")
    p.add_argument("--interval", type=float, default=60.0, help="確認の間隔 (秒)")
    p.add_argument("--once", action="store_true", help="一覧を1回出して終了")
    p.add_argument("--log-dir", default="data/watch", help="見張りのログの保存先")
    p.add_argument("--notify", help="停止の疑い・復旧を送る通知URL")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("compare", help="デモ/実口座の取引を同じ期間のバックテストと1件ずつ照合")
    _mt5(p)
    _magic(p)
    _trading(p)
    p.add_argument("--params", help="live と同じパラメータ")
    p.add_argument("--since", required=True, help="この日以降の取引を比べる (YYYY-MM-DD、サーバー時刻)")
    p.add_argument("--history", type=int, default=3000, help="バックテストに使う足の本数 (指標の助走込み)")
    p.add_argument("--spread", type=float, default=0.3, help="バックテストのスプレッド (pips)")
    p.add_argument("--slippage", type=float, default=0.0, help="バックテストの滑り (pips)")
    p.add_argument("--equity", type=float, default=100_000, help="バックテストの初期資金")
    p.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, MT5Error) as exc:
        print(f"[エラー] {exc}", file=sys.stderr)
        return 1

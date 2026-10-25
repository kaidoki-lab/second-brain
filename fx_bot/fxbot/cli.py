"""Command line: sample / strategies / backtest / optimize / fetch / live."""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from . import backtest, data, metrics, strategy
from .mt5 import TIMEFRAMES, MT5Error
from .risk import RiskConfig, pip_size


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--csv", required=True, help="価格データ (time,open,high,low,close / MT5エクスポート形式)")
    p.add_argument("--symbol", default="USDJPY", help="通貨ペア (pipサイズの判定に使用)")
    p.add_argument("--spread", type=float, default=0.3, help="スプレッド (pips)")
    p.add_argument("--equity", type=float, default=1_000_000, help="初期資金 (口座通貨)")
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


def _run(args: argparse.Namespace, bars: list[data.Bar], params: dict[str, float]) -> backtest.Result:
    strat = strategy.build(args.strategy, params)
    return backtest.run(bars, strat, _risk(args), args.equity, args.spread * pip_size(args.symbol))


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
    if args.trades:
        path = Path(args.trades)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["direction", "units", "entry_time", "entry_price", "exit_time", "exit_price", "pnl", "reason"])
            for t in result.trades:
                w.writerow(["long" if t.direction > 0 else "short", t.units, t.entry_time, round(t.entry_price, 6),
                            t.exit_time, round(t.exit_price, 6), round(t.pnl, 2), t.reason])
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


def cmd_live(args: argparse.Namespace) -> int:
    from . import mt5 as mt5link

    strat = strategy.build(args.strategy, strategy.parse_params(args.params))
    mt5 = mt5link.connect(args.terminal)
    try:
        mt5link.run_live(mt5, args.symbol, args.timeframe, strat, _risk(args),
                         history=args.history, poll=args.poll, allow_real=args.allow_real, once=args.once,
                         log=lambda msg: print(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True))
    except KeyboardInterrupt:
        print("停止しました。保有中のポジションは MT5 上にそのまま残っています (損切り注文は有効)。")
    finally:
        mt5.shutdown()
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

    p = sub.add_parser("fetch", help="MT5 から過去データをCSVに保存")
    _mt5(p)
    p.add_argument("--bars", type=int, default=50_000)
    p.add_argument("--out", help="保存先 (既定: data/<銘柄>_<時間足>.csv)")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("live", help="MT5 デモ口座で自動売買")
    _mt5(p)
    _trading(p)
    p.add_argument("--params", help="例: fast=20,slow=80,sl_atr=2")
    p.add_argument("--history", type=int, default=1000, help="判断に使う足の本数")
    p.add_argument("--poll", type=float, default=5.0, help="新しい足の確認間隔 (秒)")
    p.add_argument("--once", action="store_true", help="1回だけ判断して終了 (動作確認用)")
    p.add_argument("--allow-real", action="store_true", help="リアル口座でも動かす (非推奨)")
    p.set_defaults(func=cmd_live)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, MT5Error) as exc:
        print(f"[エラー] {exc}", file=sys.stderr)
        return 1

"""Summary statistics for a backtest result."""

from __future__ import annotations

from .backtest import Result


def max_drawdown_pct(curve: list[tuple[object, float]]) -> float:
    peak, worst = 0.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            worst = max(worst, (peak - eq) / peak * 100)
    return worst


def summarize(result: Result) -> dict[str, float]:
    pnls = [t.pnl for t in result.trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    streak = longest = 0
    for p in pnls:
        streak = streak + 1 if p <= 0 else 0
        longest = max(longest, streak)
    gross_loss = -sum(losses)
    return {
        "final_equity": result.final_equity,
        "return_pct": (result.final_equity / result.initial_equity - 1) * 100,
        "max_drawdown_pct": max_drawdown_pct(result.equity_curve),
        "trades": len(pnls),
        "win_rate_pct": len(wins) / len(pnls) * 100 if pnls else 0.0,
        "profit_factor": sum(wins) / gross_loss if gross_loss else float("inf") if wins else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "expectancy": sum(pnls) / len(pnls) if pnls else 0.0,
        "max_losing_streak": longest,
    }


LABELS = {
    "final_equity": "最終資産",
    "return_pct": "損益率 %",
    "max_drawdown_pct": "最大ドローダウン %",
    "trades": "取引回数",
    "win_rate_pct": "勝率 %",
    "profit_factor": "プロフィットファクター",
    "avg_win": "平均利益",
    "avg_loss": "平均損失",
    "expectancy": "1取引の期待値",
    "max_losing_streak": "最大連敗",
}

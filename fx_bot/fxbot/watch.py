"""Watch the state files that `live` rewrites every few seconds and report the bots that went quiet.

A bot that crashed, hung or lost MT5 stops updating its file; one stopped on purpose
(Ctrl+C, drawdown halt) marks it `stopped`. This catches a dead bot while the PC is up;
a dead PC needs an outside check (`live --heartbeat-url`).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable


def scan(root: str | Path) -> dict[Path, dict]:
    out = {}
    for path in sorted(Path(root).rglob("state_*.json")):
        try:
            out[path] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                     # half-written or locked; the next scan reads it
    return out


def label(s: dict) -> str:
    return f"{s.get('symbol')} {s.get('timeframe')} (目印 {s.get('magic')})"


def status(s: dict, now: datetime, stale_min: float) -> str:
    """'ok' / 'stopped' (on purpose) / 'stale' (should be running but is not updating)."""
    if s.get("stopped"):
        return "stopped"
    age = (now - datetime.fromisoformat(s["updated"])).total_seconds() / 60
    return "stale" if age > stale_min else "ok"


def run_watch(root: str | Path, stale_min: float, interval: float, log: Callable[[str], None],
              once: bool = False, now: Callable[[], datetime] = datetime.now,
              sleep: Callable[[float], None] = time.sleep) -> None:
    last: dict[Path, str] = {}
    first = True
    while True:
        t = now()
        states = scan(root)
        if first:
            log(f"{root} の {len(states)} 本を見張ります（{stale_min:g} 分更新がなければ知らせます）")
        for path, s in states.items():
            st = status(s, t, stale_min)
            prev = last.get(path)
            if first or once:
                mark = {"ok": "動作中", "stopped": "停止済み", "stale": "応答なし"}[st]
                log(f"  {label(s)}  {mark}  最終更新 {s['updated']}  {s.get('strategy', '')[:40]}")
            if st == "stale" and prev != "stale" and not first:
                log(f"[停止の疑い] {label(s)} が {stale_min:g} 分以上更新されていません（最終 {s['updated']}）")
            elif st == "stale" and first:
                log(f"[停止の疑い] {label(s)} は最終 {s['updated']} から更新されていません")
            elif st == "ok" and prev == "stale":
                log(f"[復旧] {label(s)} の更新が戻りました")
            elif st == "stopped" and prev == "ok":
                log(f"[注意] {label(s)} は停止しました（Ctrl+C か停止ライン）")
            last[path] = st
        first = False
        if once:
            return
        sleep(interval)

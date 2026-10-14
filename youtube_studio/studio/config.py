"""設定の読み込み。

`channel.json`（リポジトリに入る既定値）の上に `channel.local.json`（自分の
チャンネル用・リポジトリに入らない）を重ねる。`update.bat` で更新しても
自分の設定は消えない。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[1]
DEFAULT_FILE = "channel.json"
LOCAL_FILE = "channel.local.json"


class ConfigError(Exception):
    """設定が足りない・壊れている。画面にそのまま出す文言を持つ。"""


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def _read(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name} の書式が壊れています（{exc.lineno}行目）") from exc


def load(base: Path = BASE) -> dict[str, Any]:
    cfg = _read(base / DEFAULT_FILE)
    local = base / LOCAL_FILE
    if local.exists():
        cfg = merge(cfg, _read(local))
    cfg["_base"] = str(base)
    return cfg


def save_local(cfg_patch: dict[str, Any], base: Path = BASE) -> Path:
    """`channel.local.json` に差分を重ねて書く（既存の値は残る）。"""
    local = base / LOCAL_FILE
    current = _read(local) if local.exists() else {}
    local.write_text(json.dumps(merge(current, cfg_patch), ensure_ascii=False, indent=2)
                     + "\n", encoding="utf-8")
    return local


def path(cfg: dict[str, Any], value: str) -> Path:
    """設定の相対パスを youtube_studio/ 基準で解決する。"""
    p = Path(value).expanduser()
    return p if p.is_absolute() else Path(cfg["_base"]) / p


def require_channel(cfg: dict[str, Any]) -> None:
    ch = cfg["channel"]
    missing = [label for key, label in (("theme", "テーマ"), ("audience", "誰に向けたか"))
               if not str(ch.get(key, "")).strip()]
    if missing:
        raise ConfigError(
            "チャンネルの" + "・".join(missing) + "が未設定です。"
            " channel.local.json に書くか、`python run.py setup` で設定してください。")

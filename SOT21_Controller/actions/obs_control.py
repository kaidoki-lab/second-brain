"""OBS Studio (OBS group).

Launching only needs the exe path. Recording needs obs-websocket: enable it in
OBS (Tools -> WebSocket Server Settings), then fill in config.obs.websocket and
`pip install obsws-python`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from . import ActionError, Result, action


def _client(ctx):
    settings = ctx.config.get("obs", {}).get("websocket", {})
    if not settings.get("enabled"):
        raise ActionError("OBS WebSocket が無効です。config.json の "
                          "obs.websocket.enabled を true にしてください")
    try:
        import obsws_python
    except ImportError as exc:
        raise ActionError("obsws-python が未インストールです "
                          "(pip install obsws-python)") from exc
    try:
        return obsws_python.ReqClient(
            host=settings.get("host", "127.0.0.1"),
            port=int(settings.get("port", 4455)),
            password=settings.get("password", ""),
            timeout=5)
    except Exception as exc:  # library raises its own connection errors
        raise ActionError(f"OBSへ接続できません: {exc}") from exc


@action("obs_start", "OBS起動", "OBS")
def obs_start(ctx, params: dict[str, Any]) -> Result:
    obs = ctx.config.get("obs", {})
    exe = obs.get("exe_path", "")
    if not exe:
        raise ActionError("config.json の obs.exe_path を設定してください")
    if not Path(exe).exists():
        raise ActionError(f"OBSが見つかりません: {exe}")
    try:
        subprocess.Popen([exe], cwd=obs.get("cwd") or str(Path(exe).parent))
    except OSError as exc:
        raise ActionError(f"OBSの起動に失敗しました: {exc}") from exc
    return Result(True, "OBSを起動しました", exe)


@action("obs_record_start", "録画開始", "OBS")
def obs_record_start(ctx, params: dict[str, Any]) -> Result:
    client = _client(ctx)
    try:
        client.start_record()
    except Exception as exc:
        raise ActionError(f"録画開始に失敗しました: {exc}") from exc
    return Result(True, "録画を開始しました")


@action("obs_record_stop", "録画停止", "OBS", confirm=True)
def obs_record_stop(ctx, params: dict[str, Any]) -> Result:
    client = _client(ctx)
    try:
        response = client.stop_record()
    except Exception as exc:
        raise ActionError(f"録画停止に失敗しました: {exc}") from exc
    path = getattr(response, "output_path", "") or ""
    return Result(True, "録画を停止しました", path)


@action("obs_status", "OBS状態", "OBS")
def obs_status(ctx, params: dict[str, Any]) -> Result:
    client = _client(ctx)
    try:
        status = client.get_record_status()
    except Exception as exc:
        raise ActionError(f"OBS状態を取得できません: {exc}") from exc
    active = bool(getattr(status, "output_active", False))
    timecode = getattr(status, "output_timecode", "") or ""
    return Result(True, "録画中 " + timecode if active else "停止中", timecode,
                  {"recording": active, "timecode": timecode})

"""SECOND BRAIN integration (SECOND BRAIN group).

The tablet becomes a window onto the shared brain: read the project's current
position, pull a role-specific context to paste into any AI chat, list the
handoff index, and mark the current phase complete — all against the same
HTTP API the AIs use, so the tablet and the models never disagree.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import ActionError, Result, action

TIMEOUT = 6


def _settings(ctx) -> dict[str, Any]:
    brain = ctx.config.get("brain", {})
    if not brain.get("enabled", True):
        raise ActionError("config.json の brain.enabled が false です")
    if not brain.get("url"):
        raise ActionError("config.json の brain.url を設定してください")
    return brain


def request(ctx, path: str, method: str = "GET",
            payload: dict[str, Any] | None = None) -> tuple[int, str]:
    brain = _settings(ctx)
    url = brain["url"].rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if brain.get("api_key"):
        req.add_header("Authorization", "Bearer " + brain["api_key"])
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        if exc.code == 401:
            raise ActionError("第二の脳が認証を拒否しました。config.json の "
                              "brain.api_key を確認してください") from exc
        raise ActionError(f"第二の脳がエラーを返しました ({exc.code}): {body[:300]}") \
            from exc
    except urllib.error.URLError as exc:
        raise ActionError("第二の脳へ接続できません "
                          f"({brain['url']}): {exc.reason}") from exc


def _project(ctx, params: dict[str, Any]) -> str:
    project = params.get("project") or _settings(ctx).get("project")
    if not project:
        raise ActionError("config.json の brain.project を設定してください")
    return str(project)


@action("brain_status", "企画の現在地", "SECOND BRAIN")
def brain_status(ctx, params: dict[str, Any]) -> Result:
    project = _project(ctx, params)
    _, body = request(ctx, f"/project/{urllib.parse.quote(project)}/current")
    headline = ""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "CURRENT_PHASE" and index + 1 < len(lines):
            headline = lines[index + 1].strip()
    return Result(True, headline or f"{project} 現在地", body.strip(),
                  {"project": project})


@action("brain_context", "コンテキスト取得", "SECOND BRAIN",
        params={"role": "progress"})
def brain_context(ctx, params: dict[str, Any]) -> Result:
    project = _project(ctx, params)
    role = params.get("role", "progress")
    query = urllib.parse.urlencode({"project": project})
    _, body = request(ctx, f"/context/{urllib.parse.quote(role)}?{query}")
    approx = len(body) // 3
    return Result(True, f"{role} コンテキスト取得 (約{approx} tokens)", body.strip(),
                  {"role": role, "project": project})


@action("brain_handoffs", "ハンドオフ確認", "SECOND BRAIN")
def brain_handoffs(ctx, params: dict[str, Any]) -> Result:
    project = _project(ctx, params)
    _, body = request(ctx, f"/handoffs/{urllib.parse.quote(project)}?status=ACTIVE")
    try:
        handoffs = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ActionError("ハンドオフ応答を解釈できません") from exc
    lines = [f"{h['id']:<10} {h.get('owner', ''):<10} "
             f"{'OK  ' if h.get('file_exists') else 'MISS'} {h['file_path']}"
             for h in handoffs]
    missing = sum(1 for h in handoffs if not h.get("file_exists"))
    message = f"ハンドオフ {len(handoffs)}件"
    if missing:
        message += f" / ファイル未検出 {missing}件"
    return Result(missing == 0, message, "\n".join(lines) or "(なし)",
                  {"count": len(handoffs), "missing": missing})


@action("brain_phase_complete", "現フェーズ完了", "SECOND BRAIN", confirm=True)
def brain_phase_complete(ctx, params: dict[str, Any]) -> Result:
    """Mark the current phase COMPLETE — the one write the panel performs."""
    project = _project(ctx, params)
    _, body = request(ctx, f"/project/{urllib.parse.quote(project)}/current"
                           "?format=json")
    state = (json.loads(body) or {}).get("state")
    if not state:
        raise ActionError(f"{project} に現在フェーズがありません")
    phase = state["phase"]
    if state["status"] == "COMPLETE":
        return Result(True, f"{phase} は既に COMPLETE です", "")
    _, written = request(ctx, "/api/state", "POST", {
        "project": project, "phase": phase, "status": "COMPLETE",
        "owner": state.get("owner", ""), "actor": "sot21"})
    return Result(True, f"{phase} を COMPLETE にしました", written.strip())


@action("brain_open", "第二の脳を開く", "SECOND BRAIN")
def brain_open(ctx, params: dict[str, Any]) -> Result:
    brain = _settings(ctx)
    status, body = request(ctx, "/api/health")
    health = json.loads(body) if status == 200 else {}
    return Result(True, "第二の脳 稼働中",
                  f"{brain['url']}\nprojects: {health.get('projects')} / "
                  f"agents: {health.get('agents')}",
                  {"url": brain["url"], "health": health})


@action("brain_serve", "第二の脳を起動", "SECOND BRAIN", confirm=True)
def brain_serve(ctx, params: dict[str, Any]) -> Result:
    """Start the brain server on this PC when it is not running yet."""
    brain = _settings(ctx)
    launch = brain.get("launch") or {}
    if not launch.get("program"):
        raise ActionError("config.json の brain.launch.program を設定してください")
    try:
        request(ctx, "/api/health")
        return Result(True, "第二の脳は既に稼働中です", brain["url"])
    except ActionError:
        pass
    from .run_command import build_argv
    argv = build_argv(ctx, launch)
    try:
        subprocess.Popen(argv, cwd=str(ctx.base_dir))
    except OSError as exc:
        raise ActionError(f"起動に失敗しました: {exc}") from exc
    return Result(True, "第二の脳を起動しました", " ".join(argv))

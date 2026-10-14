"""第二の脳とのつなぎ（任意。channel.json の brain.enabled）。

- 企画・台本を書く前に、第二の脳の確定事実を読む（AIに作り話をさせない）
- 公開した動画を FACT として第二の脳へ残す（他のAIもチャンネルの現状を知れる）

第二の脳が止まっていても動画づくりは止めない。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


def _request(cfg: dict[str, Any], method: str, path: str,
             payload: dict[str, Any] | None = None) -> dict[str, Any]:
    b = cfg["brain"]
    headers = {"Content-Type": "application/json"}
    if b.get("api_key"):
        headers["Authorization"] = "Bearer " + b["api_key"]
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(b["url"].rstrip("/") + path, data=data, headers=headers,
                                 method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def context(cfg: dict[str, Any]) -> str:
    b = cfg.get("brain", {})
    if not b.get("enabled"):
        return ""
    q = urllib.parse.urlencode({"role": b.get("role", "design"), "project": b["project"]})
    try:
        return str(_request(cfg, "GET", f"/api/context?{q}").get("text", ""))
    except (OSError, ValueError):
        return ""


def record_published(cfg: dict[str, Any], title: str, url: str) -> bool:
    b = cfg.get("brain", {})
    if not b.get("enabled"):
        return False
    try:
        _request(cfg, "POST", "/api/fact", {
            "project": b["project"], "body": f"動画を公開した: {title} {url}",
            "key": "youtube_published", "tags": ["youtube"], "source": url,
            "actor": "youtube_studio"})
        return True
    except (OSError, ValueError):
        return False

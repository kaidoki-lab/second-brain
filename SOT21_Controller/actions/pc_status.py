"""Main PC / sub PC health (SYSTEM group)."""

from __future__ import annotations

import platform
import shutil
import time
from typing import Any

from . import Result, action
from .network_control import ping_host, tcp_probe

try:
    import psutil
except ImportError:  # psutil is in requirements.txt; degrade instead of crash
    psutil = None


def main_pc_metrics(config: dict[str, Any]) -> dict[str, Any]:
    """CPU / RAM / DISK for the machine this server runs on."""
    disk_path = config.get("main_pc", {}).get("disk") or "/"
    metrics: dict[str, Any] = {"host": platform.node(), "online": True}
    if psutil is None:
        metrics.update({"cpu": None, "memory": None, "disk": None,
                        "note": "psutil 未インストール"})
        return metrics
    metrics["cpu"] = round(psutil.cpu_percent(interval=0.2))
    metrics["memory"] = round(psutil.virtual_memory().percent)
    try:
        usage = shutil.disk_usage(disk_path)
    except OSError:
        usage = shutil.disk_usage("/")
    metrics["disk"] = round(usage.used / usage.total * 100)
    metrics["disk_free_gb"] = round(usage.free / (1024 ** 3), 1)
    metrics["uptime_h"] = round((time.time() - psutil.boot_time()) / 3600, 1)
    return metrics


def sub_pc_state(config: dict[str, Any]) -> dict[str, Any]:
    """Reachability of the second machine: ping first, TCP as the tie-breaker."""
    sub = config.get("sub_pc", {})
    host = sub.get("ip", "")
    if not host:
        return {"online": False, "note": "sub_pc.ip 未設定"}
    reachable, detail = ping_host(host, timeout=1)
    if not reachable and sub.get("port"):
        reachable, detail = tcp_probe(host, int(sub["port"]), timeout=1)
    return {"online": reachable, "host": host, "note": detail}


def snapshot(config: dict[str, Any]) -> dict[str, Any]:
    """The payload behind GET /api/status."""
    main = main_pc_metrics(config)
    sub = sub_pc_state(config)
    return {
        "main_pc": bool(main.get("online")),
        "sub_pc": bool(sub.get("online")),
        "cpu": main.get("cpu"),
        "memory": main.get("memory"),
        "disk": main.get("disk"),
        "disk_free_gb": main.get("disk_free_gb"),
        "uptime_h": main.get("uptime_h"),
        "main_pc_name": config.get("main_pc", {}).get("name", "MAIN PC"),
        "sub_pc_name": config.get("sub_pc", {}).get("name", "SUB PC"),
        "main_pc_detail": main,
        "sub_pc_detail": sub,
    }


@action("status_main", "メインPC状態確認", "SYSTEM")
def status_main(ctx, params: dict[str, Any]) -> Result:
    metrics = main_pc_metrics(ctx.config)
    detail = "\n".join([
        f"HOST     {metrics.get('host')}",
        f"CPU      {metrics.get('cpu')}%",
        f"RAM      {metrics.get('memory')}%",
        f"DISK     {metrics.get('disk')}%  (空き {metrics.get('disk_free_gb')} GB)",
        f"UPTIME   {metrics.get('uptime_h')} h",
    ])
    return Result(True, "メインPC 正常", detail, metrics)


@action("status_sub", "サブPC状態確認", "SYSTEM")
def status_sub(ctx, params: dict[str, Any]) -> Result:
    state = sub_pc_state(ctx.config)
    name = ctx.config.get("sub_pc", {}).get("name", "SUB PC")
    if state["online"]:
        return Result(True, f"{name} ONLINE", state.get("note", ""), state)
    return Result(False, f"{name} OFFLINE", state.get("note", ""), state)


@action("status_refresh", "状態更新", "SYSTEM")
def status_refresh(ctx, params: dict[str, Any]) -> Result:
    data = snapshot(ctx.config)
    return Result(True, "状態を更新しました",
                  f"CPU {data['cpu']}%  RAM {data['memory']}%  DISK {data['disk']}%",
                  data)

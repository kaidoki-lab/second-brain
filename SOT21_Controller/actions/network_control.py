"""Ping, TCP probe and Wake-on-LAN (PC CONTROL group)."""

from __future__ import annotations

import platform
import re
import socket
import subprocess
from typing import Any

from . import ActionError, Result, action

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")
HOST_RE = re.compile(r"^[A-Za-z0-9._\-]{1,255}$")


def ping_host(host: str, timeout: int = 1) -> tuple[bool, str]:
    """One ICMP echo. Host is validated: it goes into a subprocess argv."""
    if not HOST_RE.match(host or ""):
        return False, f"不正なホスト名: {host}"
    windows = platform.system() == "Windows"
    count_flag = "-n" if windows else "-c"
    wait_flag = "-w" if windows else "-W"
    wait_value = str(timeout * 1000) if windows else str(timeout)
    cmd = ["ping", count_flag, "1", wait_flag, wait_value, host]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=timeout + 4)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, f"ping 失敗: {exc}"
    ok = completed.returncode == 0
    return ok, ("応答あり" if ok else "応答なし")


def tcp_probe(host: str, port: int, timeout: int = 1) -> tuple[bool, str]:
    if not HOST_RE.match(host or ""):
        return False, f"不正なホスト名: {host}"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"TCP {port} 接続OK"
    except OSError as exc:
        return False, f"TCP {port} 接続不可 ({exc.__class__.__name__})"


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255",
                      port: int = 9) -> None:
    if not MAC_RE.match(mac or ""):
        raise ActionError(f"MACアドレスが不正です: {mac or '(未設定)'}")
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    packet = b"\xff" * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (broadcast, port))


@action("sub_pc_wol", "サブPC Wake-on-LAN", "PC CONTROL", confirm=True)
def sub_pc_wol(ctx, params: dict[str, Any]) -> Result:
    sub = ctx.config.get("sub_pc", {})
    mac = sub.get("mac", "")
    if mac in ("", "00:00:00:00:00:00"):
        raise ActionError("config.json の sub_pc.mac を設定してください")
    send_magic_packet(mac, sub.get("broadcast", "255.255.255.255"))
    return Result(True, "Wake-on-LAN を送信しました",
                  f"MAC {mac} / broadcast {sub.get('broadcast')}")


@action("sub_pc_ping", "サブPC接続確認", "PC CONTROL")
def sub_pc_ping(ctx, params: dict[str, Any]) -> Result:
    sub = ctx.config.get("sub_pc", {})
    host = sub.get("ip", "")
    if not host:
        raise ActionError("config.json の sub_pc.ip を設定してください")
    ok, detail = ping_host(host, timeout=1)
    if not ok and sub.get("port"):
        ok, detail = tcp_probe(host, int(sub["port"]), timeout=1)
    name = sub.get("name", "SUB PC")
    return Result(ok, f"{name} {'ONLINE' if ok else 'OFFLINE'}", f"{host}: {detail}")

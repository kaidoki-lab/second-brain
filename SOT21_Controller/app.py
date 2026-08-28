"""SOT21 LAN CONTROLLER — メインPC上で動く操作盤サーバー。

    python app.py            -> http://<このPCのIPv4>:5000

タブレット(SOT21)側はブラウザで開くだけ。重い処理は全てこのPC側で動く。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

import actions
from actions import ActionError, Result
from actions.pc_status import snapshot

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "logs" / "controller.log"

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "0.0.0.0", "port": 5000},
    "security": {"lan_only": True,
                 "allow_networks": ["127.0.0.0/8", "192.168.0.0/16",
                                    "10.0.0.0/8", "172.16.0.0/12"]},
    "main_pc": {"name": "MAIN PC"},
    "sub_pc": {"name": "SUB PC"},
    "commands": {},
    "folders": {},
    "obs": {},
    "brain": {"enabled": False},
}


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """config.json を読み、欠けたキーは既定値で補う。"""
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"config.json を読めません: {exc}") from exc
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


@dataclass
class Context:
    """アクションへ渡す実行文脈。"""
    config: dict[str, Any]
    base_dir: Path
    logger: logging.Logger


def build_logger(log_path: Path = LOG_PATH) -> logging.Logger:
    logger = logging.getLogger("sot21")
    logger.setLevel(logging.INFO)
    for existing in list(logger.handlers):   # avoid leaking file handles when
        existing.close()                     # an app is rebuilt (tests, reload)
        logger.removeHandler(existing)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-5s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    logger.addHandler(console)
    return logger


def allowed_networks(config: dict[str, Any]) -> list[ipaddress.IPv4Network]:
    networks = []
    for raw in config.get("security", {}).get("allow_networks", []):
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError:
            continue
    return networks


def is_allowed(remote: str, config: dict[str, Any]) -> bool:
    """LAN内のプライベートIPのみ許可する。"""
    if not config.get("security", {}).get("lan_only", True):
        return True
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_loopback:
        return True
    if not (address.is_private or address.is_link_local):
        return False
    networks = allowed_networks(config)
    return any(address in network for network in networks) if networks else True


def local_ipv4() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def register_brain_buttons(config: dict[str, Any]) -> None:
    """設定された役割ごとにコンテキスト取得ボタンを生やす。"""
    brain = config.get("brain", {})
    if not brain.get("enabled"):
        return
    for role in brain.get("roles", []):
        actions.alias(f"brain_context_{role}", f"{role.upper()} コンテキスト",
                      "SECOND BRAIN", "brain_context", {"role": role})


def create_app(config: dict[str, Any] | None = None,
               log_path: Path = LOG_PATH) -> Flask:
    config = config if config is not None else load_config()
    actions.load()
    register_brain_buttons(config)
    logger = build_logger(log_path)
    ctx = Context(config, BASE_DIR, logger)

    app = Flask(__name__)
    app.config["CTX"] = ctx

    def log_action(action_name: str, success: bool, message: str) -> None:
        logger.log(logging.INFO if success else logging.ERROR,
                   "%s | %s | %s | %s", request.remote_addr or "-", action_name,
                   "SUCCESS" if success else "FAILURE", message.replace("\n", " / "))

    @app.before_request
    def restrict_to_lan():
        remote = request.remote_addr or ""
        if is_allowed(remote, ctx.config):
            return None
        logger.warning("%s | %s | BLOCKED | LAN外からの接続", remote, request.path)
        return jsonify({"success": False,
                        "message": "LAN外からのアクセスは許可されていません"}), 403

    @app.get("/")
    def index():
        return render_template(
            "index.html", catalog=actions.catalog(),
            main_name=ctx.config.get("main_pc", {}).get("name", "MAIN PC"),
            sub_name=ctx.config.get("sub_pc", {}).get("name", "SUB PC"))

    @app.get("/api/status")
    def api_status():
        return jsonify(snapshot(ctx.config))

    @app.get("/api/actions")
    def api_actions():
        return jsonify(actions.catalog())

    @app.post("/api/action")
    def api_action():
        payload = request.get_json(silent=True) or {}
        name = str(payload.get("action", "")).strip()
        params = payload.get("params") or {}
        if not name:
            log_action("(none)", False, "action が空です")
            return jsonify({"success": False, "message": "action が指定されていません"}), 400
        if not isinstance(params, dict):
            return jsonify({"success": False, "message": "params が不正です"}), 400
        try:
            result: Result = actions.run(name, params, ctx)
        except ActionError as exc:
            log_action(name, False, str(exc))
            return jsonify({"success": False, "message": str(exc)}), 200
        except Exception as exc:  # unexpected: log the type, keep the panel alive
            logger.exception("%s | %s | FAILURE | %s", request.remote_addr, name, exc)
            return jsonify({"success": False,
                            "message": f"内部エラー: {exc.__class__.__name__}"}), 500
        log_action(name, result.success, result.message)
        return jsonify(result.as_dict())

    logger.info("- | startup | SUCCESS | actions=%d lan_only=%s",
                len(actions.REGISTRY),
                ctx.config.get("security", {}).get("lan_only", True))
    return app


def main() -> None:
    config = load_config()
    app = create_app(config)
    host = config["server"].get("host", "0.0.0.0")
    port = int(config["server"].get("port", 5000))
    print("=" * 52)
    print(" SOT21 HOME CONTROL")
    print(f"   このPC : http://127.0.0.1:{port}")
    print(f"   SOT21  : http://{local_ipv4()}:{port}")
    print("   停止   : Ctrl+C")
    print("=" * 52)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

"""HTTP server (stdlib only, spec section 5).

    http://127.0.0.1:8765    local
    http://<PC IP>:8765      LAN (API key required)
"""

from __future__ import annotations

import ipaddress
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .app import App
from .config import Config
from .http_util import Request

MAX_BODY = 1 << 20  # 1 MiB: the brain stores meaning, not transcripts.


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "SecondBrain"
    app: App

    def _dispatch(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, b"payload too large", "text/plain; charset=utf-8", {})
            return
        body = self.rfile.read(length) if length else b""
        request = Request.make(self.command, self.path, dict(self.headers), body)
        response = self.app.handle(request)
        self._send(response.status, response.body, response.content_type,
                   response.headers)

    def _send(self, status: int, body: bytes, content_type: str,
              headers: dict[str, str]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_GET = do_POST = do_PUT = do_DELETE = _dispatch

    def log_message(self, fmt: str, *args) -> None:  # quieter default log
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def local_ips() -> list[str]:
    """Best-effort list of LAN addresses to print at startup."""
    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ips.add(sock.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    out = []
    for ip in sorted(ips):
        try:
            if ipaddress.ip_address(ip).is_private:
                out.append(ip)
        except ValueError:
            continue
    return out


def port_is_free(host: str, port: int) -> bool:
    """そのポートで待ち受けできるかを実際に試す。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str, preferred: int, attempts: int = 40) -> int:
    """希望のポートが他のアプリに使われていたら、その次の空きを探す。

    別の企画のサーバーが同じポートを使っていても起動できるようにするため。
    """
    for offset in range(attempts):
        candidate = preferred + offset
        if candidate > 65535:
            break
        if port_is_free(host, candidate):
            return candidate
    raise SystemExit(
        f"{preferred} から {preferred + attempts - 1} まで、空いているポートが"
        "見つかりませんでした。--port で別の番号を指定してください。")


def build_server(app: App, config: Config) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"app": app})
    port = config.port
    if port:                      # 0 は「OSに任せる」なのでそのまま使う
        port = find_free_port(config.host, port)
    server = ThreadingHTTPServer((config.host, port), handler)
    server.daemon_threads = True
    return server


def serve(app: App, config: Config, open_browser: bool = False) -> None:
    if not config.is_loopback and not config.api_key:
        raise SystemExit(
            f"APIキーなしで {config.host} を公開することはできません。\n"
            "SECOND_BRAIN_API_KEY を設定するか、--api-key を渡すか、"
            "127.0.0.1 で起動してください。")
    server = build_server(app, config)
    port = server.server_address[1]
    print("=" * 52)
    print("  第二の脳が起動しました")
    print("=" * 52)
    if config.port and port != config.port:
        print(f"  ※ {config.port} 番は他のアプリが使用中だったため、"
              f"{port} 番で起動しました")
    print(f"  このPCで開く : http://127.0.0.1:{port}")
    for ip in local_ips():
        print(f"  LAN内で開く  : http://{ip}:{port}")
    print("  認証         : " + ("APIキーが必要" if config.api_key
                                  else "なし（このPCからのみ）"))
    print(f"  データ       : {config.db_path}")
    print("  終了するには この画面で Ctrl + C")
    print("=" * 52)
    write_url_file(config, port)
    if open_browser:
        # サーバーが listen し始めてから開く（起動直後だと接続拒否になる）。
        threading.Timer(1.0, webbrowser.open,
                        [f"http://127.0.0.1:{port}"]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました")
    finally:
        server.shutdown()
        server.server_close()


def url_file_path(config: Config) -> Path:
    """いま動いているアドレスを書き出す場所（DBと同じフォルダ）。"""
    return Path(config.db_path).expanduser().parent / "server_url.txt"


def write_url_file(config: Config, port: int) -> None:
    """ポートが変わっても他のツールが接続先を見つけられるように記録する。"""
    try:
        path = url_file_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"http://127.0.0.1:{port}\n", encoding="utf-8")
    except OSError:
        pass          # 書けなくても本体の動作には影響しない


def serve_in_thread(app: App, config: Config) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Used by the tests: a real socket server on a background thread."""
    server = build_server(app, config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread

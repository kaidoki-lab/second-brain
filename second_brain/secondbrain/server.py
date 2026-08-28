"""HTTP server (stdlib only, spec section 5).

    http://127.0.0.1:8765    local
    http://<PC IP>:8765      LAN (API key required)
"""

from __future__ import annotations

import ipaddress
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


def build_server(app: App, config: Config) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"app": app})
    server = ThreadingHTTPServer((config.host, config.port), handler)
    server.daemon_threads = True
    return server


def serve(app: App, config: Config) -> None:
    if not config.is_loopback and not config.api_key:
        raise SystemExit(
            "refusing to bind %s without an API key.\n"
            "Set SECOND_BRAIN_API_KEY, pass --api-key, or bind 127.0.0.1."
            % config.host)
    server = build_server(app, config)
    port = server.server_address[1]
    print(f"SECOND BRAIN  db={config.db_path}")
    print(f"  local   http://127.0.0.1:{port}")
    for ip in local_ips():
        print(f"  lan     http://{ip}:{port}")
    print("  auth    " + ("API key required" if config.api_key else "off (loopback)"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.shutdown()
        server.server_close()


def serve_in_thread(app: App, config: Config) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Used by the tests: a real socket server on a background thread."""
    server = build_server(app, config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread

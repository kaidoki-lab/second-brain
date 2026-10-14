"""YouTube Data API v3: 認証・投稿・サムネイル・再生数の取得。

外部ライブラリは使わず urllib だけで動かす。

注意（Google の規約）:
  審査（API監査）を通っていない Google Cloud プロジェクトから API で投稿した
  動画は、強制的に「非公開」になり公開に切り替えられない。そのため既定は
  ``youtube.upload = "manual"``（承認画面に出る内容を YouTube Studio へ貼る）。
  監査を通したら ``"api"`` に変えると、承認ボタンだけで予約投稿まで進む。
  再生数の取得（読み取り）は監査なしで使える。
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .config import path as cfg_path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.readonly"]

Transport = Callable[[str, str, dict[str, str], "bytes | BinaryIO | None"],
                     "tuple[int, dict[str, str], bytes]"]


class YouTubeError(Exception):
    pass


def _urllib_transport(method: str, url: str, headers: dict[str, str],
                      data: bytes | BinaryIO | None) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


def _form(data: dict[str, str]) -> bytes:
    return urllib.parse.urlencode(data).encode("utf-8")


class YouTube:
    def __init__(self, cfg: dict[str, Any], transport: Transport | None = None,
                 clock: Callable[[], float] = time.time):
        y = cfg["youtube"]
        self.cfg = cfg
        self.secret_file = cfg_path(cfg, y.get("client_secret", "secrets/client_secret.json"))
        self.token_file = cfg_path(cfg, y.get("token", "secrets/token.json"))
        self.api_key = y.get("api_key", "")
        self.channel_id = y.get("channel_id", "")
        self.transport = transport or _urllib_transport
        self.clock = clock

    # ---------------------------------------------------------- 認証

    def client(self) -> dict[str, str]:
        if not self.secret_file.exists():
            raise YouTubeError(
                f"{self.secret_file} がありません。Google Cloud で「デスクトップアプリ」の"
                "OAuthクライアントを作り、JSONをこの名前で保存してください（README参照）")
        data = json.loads(self.secret_file.read_text(encoding="utf-8"))
        return data.get("installed") or data.get("web") or data

    def has_token(self) -> bool:
        return self.token_file.exists()

    def authorize(self, open_browser: bool = True) -> dict[str, Any]:
        """ブラウザで許可をもらい、トークンを保存する（初回だけ）。"""
        client = self.client()
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(16)
        received: dict[str, str] = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                qs = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
                received.update(qs)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("許可を受け取りました。この画面は閉じてください。".encode("utf-8"))

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        redirect = f"http://127.0.0.1:{server.server_port}"
        url = AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": client["client_id"], "redirect_uri": redirect,
            "response_type": "code", "scope": " ".join(SCOPES), "access_type": "offline",
            "prompt": "consent", "state": state, "code_challenge": challenge,
            "code_challenge_method": "S256"})
        print("ブラウザで YouTube チャンネルの Google アカウントを選び、許可してください。")
        print("開かない場合はこのアドレスを開いてください:\n" + url)
        if open_browser:
            webbrowser.open(url)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        thread.join(timeout=600)
        server.server_close()
        if received.get("state") != state or "code" not in received:
            raise YouTubeError("許可が得られませんでした: " + received.get("error", "時間切れ"))
        token = self._token_request({
            "code": received["code"], "client_id": client["client_id"],
            "client_secret": client.get("client_secret", ""), "redirect_uri": redirect,
            "grant_type": "authorization_code", "code_verifier": verifier})
        self._save_token(token)
        return token

    def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        status, _, body = self.transport(
            "POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, _form(form))
        data = json.loads(body or b"{}")
        if status != 200:
            raise YouTubeError(f"認証に失敗しました: {data.get('error_description') or data}")
        data["expires_at"] = self.clock() + int(data.get("expires_in", 3600)) - 60
        return data

    def _save_token(self, token: dict[str, Any]) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps(token, indent=2), encoding="utf-8")

    def access_token(self) -> str:
        if not self.token_file.exists():
            raise YouTubeError("YouTube の認証がまだです。`python run.py auth` を実行してください")
        token = json.loads(self.token_file.read_text(encoding="utf-8"))
        if token.get("expires_at", 0) > self.clock():
            return token["access_token"]
        client = self.client()
        fresh = self._token_request({
            "client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
            "refresh_token": token["refresh_token"], "grant_type": "refresh_token"})
        fresh.setdefault("refresh_token", token["refresh_token"])
        self._save_token(fresh)
        return fresh["access_token"]

    # ---------------------------------------------------------- 呼び出し

    def _call(self, method: str, url: str, data: bytes | BinaryIO | None = None,
              headers: dict[str, str] | None = None, auth: bool = True
              ) -> tuple[dict[str, str], dict[str, Any]]:
        h = dict(headers or {})
        if auth:
            h["Authorization"] = "Bearer " + self.access_token()
        status, rh, body = self.transport(method, url, h, data)
        payload = json.loads(body) if body and body.strip().startswith(b"{") else {}
        if status >= 400:
            msg = payload.get("error", {}).get("message", "") if isinstance(
                payload.get("error"), dict) else str(payload)
            raise YouTubeError(f"YouTube API エラー（{status}）: {msg}")
        return rh, payload

    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        use_key = self.api_key and not self.has_token()
        if use_key:
            params = {**params, "key": self.api_key}
        return self._call("GET", f"{API}/{endpoint}?" + urllib.parse.urlencode(params),
                          auth=not use_key)[1]

    # ---------------------------------------------------------- 投稿

    def upload(self, video: Path, meta: dict[str, Any], publish_at: str = "") -> str:
        """再開可能アップロードで投稿し、動画IDを返す。

        publish_at（ISO 8601）を渡すと非公開で上げて、その時刻に自動公開する。
        """
        y = self.cfg["youtube"]
        status: dict[str, Any] = {
            "privacyStatus": "private" if publish_at else y.get("privacy", "public"),
            "selfDeclaredMadeForKids": bool(y.get("made_for_kids", False)),
            "containsSyntheticMedia": bool(y.get("synthetic_media", False)),
        }
        if publish_at:
            status["publishAt"] = publish_at
        body = json.dumps({
            "snippet": {"title": meta["title"][:100], "description": meta["description"][:5000],
                        "tags": meta.get("tags", []),
                        "categoryId": str(y.get("category_id", "27")),
                        "defaultLanguage": "ja", "defaultAudioLanguage": "ja"},
            "status": status}).encode("utf-8")
        size = video.stat().st_size
        headers, _ = self._call(
            "POST", f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status", body,
            {"Content-Type": "application/json; charset=UTF-8",
             "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
        location = headers.get("location")
        if not location:
            raise YouTubeError("アップロード先が返ってきませんでした")
        with video.open("rb") as fh:
            _, result = self._call("PUT", location, fh,
                                   {"Content-Type": "video/mp4", "Content-Length": str(size)})
        if not result.get("id"):
            raise YouTubeError("アップロードの結果に動画IDがありません")
        return result["id"]

    def set_thumbnail(self, video_id: str, image: Path) -> None:
        """カスタムサムネイル（チャンネルの電話番号確認が済んでいる必要がある）。"""
        self._call("POST", f"{UPLOAD}/thumbnails/set?videoId={video_id}", image.read_bytes(),
                   {"Content-Type": "image/png"})

    # ---------------------------------------------------------- 再生数

    def channel_videos(self, limit: int = 50) -> list[dict[str, Any]]:
        """チャンネルの動画と再生数・高評価数・コメント数。"""
        params = {"part": "contentDetails"}
        if self.has_token():
            params["mine"] = "true"
        elif self.channel_id:
            params["id"] = self.channel_id
        else:
            raise YouTubeError("再生数を読むには `run.py auth` か、youtube.api_key と"
                               " youtube.channel_id の設定が必要です")
        items = self._get("channels", params).get("items", [])
        if not items:
            raise YouTubeError("チャンネルが見つかりません")
        uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
        listing = self._get("playlistItems", {"part": "contentDetails", "playlistId": uploads,
                                              "maxResults": str(min(limit, 50))})
        ids = [i["contentDetails"]["videoId"] for i in listing.get("items", [])]
        if not ids:
            return []
        videos = self._get("videos", {"part": "snippet,statistics", "id": ",".join(ids)})
        out = []
        for v in videos.get("items", []):
            st = v.get("statistics", {})
            out.append({"id": v["id"], "title": v["snippet"]["title"],
                        "published_at": v["snippet"].get("publishedAt", ""),
                        "views": int(st.get("viewCount", 0)),
                        "likes": int(st.get("likeCount", 0)),
                        "comments": int(st.get("commentCount", 0))})
        return out

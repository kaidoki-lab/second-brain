"""確認画面（スマホ・SOT21 のブラウザから開く）。

    /                一覧（確認待ち・投稿待ち・公開済み）
    /ep/<id>         動画を見て、タイトル等を直して 承認 / 見送り
    /media/<id>/<f>  動画・サムネ（シーク用に Range 対応）

標準ライブラリの http.server だけで動く。既定では同じLANからしか開けない。
"""

from __future__ import annotations

import html
import ipaddress
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .episode import (APPROVED, IN_PROGRESS, LABELS, PUBLISHED, REJECTED, REVIEW,
                      Episode)
from . import cast
from .pipeline import Studio

MEDIA = {"long.mp4": "video/mp4", "short.mp4": "video/mp4", "thumbnail.png": "image/png"}

CSS = """
:root{color-scheme:light dark;--bg:#f8fafc;--fg:#0f172a;--card:#fff;--line:#e2e8f0;
--muted:#64748b;--accent:#ca8a04;--ok:#15803d;--ng:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#0f172a;--fg:#f1f5f9;--card:#1e293b;
--line:#334155;--muted:#94a3b8;--accent:#facc15;--ok:#4ade80;--ng:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.6 system-ui,-apple-system,"Hiragino Sans","Yu Gothic UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0 16px}h2{font-size:17px;margin:24px 0 8px}
a{color:inherit}.card{background:var(--card);border:1px solid var(--line);
border-radius:12px;padding:14px;margin:10px 0}
.badge{display:inline-block;font-size:12px;padding:2px 8px;border-radius:99px;
border:1px solid var(--line);color:var(--muted)}
.muted{color:var(--muted);font-size:14px}video,img{width:100%;border-radius:8px;
background:#000}.vert{max-width:320px}
label{display:block;font-weight:600;margin:12px 0 4px}
input,textarea{width:100%;font:inherit;padding:10px;border-radius:8px;
border:1px solid var(--line);background:var(--bg);color:var(--fg)}
textarea{min-height:140px}
button{font:inherit;font-weight:700;padding:14px 18px;border-radius:10px;border:0;
min-height:52px;cursor:pointer;width:100%;margin-top:12px}
.ok{background:var(--ok);color:#fff}.ng{background:transparent;color:var(--ng);
border:2px solid var(--ng)}.copy{background:var(--line);color:var(--fg);
width:auto;min-height:40px;padding:6px 12px;margin:4px 0}
ul.checks li{margin:4px 0}.err{color:var(--ng)}
.row{display:flex;gap:10px;align-items:center;justify-content:space-between}
"""

COPY_JS = """
document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{
const t=document.getElementById(b.dataset.copy);navigator.clipboard.writeText(t.value)
.then(()=>{b.textContent='コピーしました'})});
"""


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{CSS}</style></head>"
            f"<body><main>{body}</main><script>{COPY_JS}</script></body></html>"
            ).encode("utf-8")


def _title(ep: Episode) -> str:
    return (ep.data.get("final") or {}).get("title") or (
        ep.data.get("script") or {}).get("title") or ep.data["topic"]["title"]


def index_html(studio: Studio) -> bytes:
    cfg = studio.cfg
    groups = [
        ("確認待ち（見て判断してください）", (REVIEW,)),
        ("承認済み・YouTubeへの投稿待ち", (APPROVED,)),
        ("制作中・企画", IN_PROGRESS),
        ("公開済み", (PUBLISHED,)),
        ("見送り", (REJECTED,)),
    ]
    episodes = studio.library.all()
    body = [f"<h1>{esc(cfg['channel'].get('name') or 'YouTube STUDIO')}</h1>"]
    memory = studio.library.memory()
    if memory.get("stats_at"):
        total = sum(s.get("views", 0) for s in memory["stats"].values())
        body.append(f"<p class='muted'>総再生 {total:,} 回・{len(memory['stats'])}本"
                    f"（{esc(memory['stats_at'][:16])} 時点）</p>")
    if cast.enabled(cfg):
        rows = cast.report(cfg, episodes, memory.get("stats", {}))
        body.append("<h2>キャラ別の反応（平均再生の多い順）</h2><div class='card'><table>"
                    "<tr><th>キャラ</th><th>公開</th><th>平均再生</th><th>コメント</th></tr>"
                    + "".join(f"<tr><td>{esc(r['name'])}</td><td>{r['published']}</td>"
                              f"<td>{r['avg_views']:,}</td><td>{r['comments']:,}</td></tr>"
                              for r in rows) + "</table></div>")
    for label, statuses in groups:
        items = [ep for ep in reversed(episodes) if ep.status in statuses]
        if not items:
            continue
        body.append(f"<h2>{esc(label)}（{len(items)}）</h2>")
        for ep in items[:30]:
            err = f"<div class='err'>止まった理由: {esc(ep.data['error'])}</div>" \
                if ep.data.get("error") else ""
            body.append(
                f"<a href='/ep/{esc(ep.id)}'><div class='card'><div class='row'>"
                f"<strong>{esc(_title(ep))}</strong>"
                f"<span class='badge'>{esc(LABELS.get(ep.status, ep.status))}</span></div>"
                f"<div class='muted'>{esc(ep.id)}</div>{err}</div></a>")
    if len(body) == 1:
        body.append("<p>まだ動画がありません。<code>python run.py auto</code> で1本目を作ります。</p>")
    return page("YouTube STUDIO", "".join(body))


def quiz_html(script: dict[str, Any]) -> str:
    """答えと出典（承認する人だけが見る。動画には答えは出ない）。"""
    rows = "".join(
        f"<li><strong>{esc(i['letter'])}{'（ウソ）' if i['lie'] else ''}</strong> "
        f"{esc(i['text'])}<br><span class='muted'>{esc(i['explain'])}"
        f"{'／出典: ' + esc(i['source']) if i.get('source') else ''}</span></li>"
        for i in script.get("items", []))
    out = f"<h2>答え: {esc(script.get('answer', ''))}</h2><ul class='checks'>{rows}</ul>"
    r = script.get("recap")
    if r:
        got = ("コメント未取得（答えだけ発表）" if r.get("correct") is None
               else f"回答{r['answers']}人・正解{r['correct']}人")
        out += (f"<div class='card'><strong>冒頭の答え合わせ</strong>（{esc(got)}）<br>"
                f"{esc(r['text'])}</div>")
    return out


def episode_html(studio: Studio, ep: Episode, message: str = "") -> bytes:
    script = ep.data.get("script") or {}
    final = ep.data.get("final") or {}
    body = ["<p><a href='/'>← 一覧へ</a></p>",
            f"<h1>{esc(_title(ep))}</h1>",
            f"<span class='badge'>{esc(LABELS.get(ep.status, ep.status))}</span>"]
    if message:
        body.append(f"<div class='card'>{esc(message)}</div>")
    if ep.data.get("cast"):
        try:
            who = cast.member(studio.cfg, ep.data["cast"]).get("name", ep.data["cast"])
        except cast.CastError:
            who = ep.data["cast"]
        body.append(f" <span class='badge'>出演: {esc(who)}</span>")
    if script.get("format") == "quiz":
        body.append(quiz_html(script))
    outputs = ep.data.get("outputs", [])
    if "long.mp4" in outputs:
        mins = ep.data.get("long_seconds", 0) / 60
        body.append(f"<h2>本編（約{mins:.1f}分）</h2>"
                    f"<video controls preload='metadata' src='/media/{esc(ep.id)}/long.mp4'"
                    f" poster='/media/{esc(ep.id)}/thumbnail.png'></video>"
                    f"<p><a href='/media/{esc(ep.id)}/long.mp4' download>本編をダウンロード</a></p>")
    if "short.mp4" in outputs:
        body.append(f"<h2>ショート</h2><video class='vert' controls preload='metadata'"
                    f" src='/media/{esc(ep.id)}/short.mp4'></video>"
                    f"<p><a href='/media/{esc(ep.id)}/short.mp4' download>ショートをダウンロード</a></p>")
    if "thumbnail.png" in outputs:
        body.append(f"<h2>サムネイル</h2><img alt='' src='/media/{esc(ep.id)}/thumbnail.png'>"
                    f"<p><a href='/media/{esc(ep.id)}/thumbnail.png' download>サムネをダウンロード</a></p>")
    if script.get("checks"):
        body.append("<h2>公開前に確かめてください（AIが事実確認を求めた点）</h2><ul class='checks'>"
                    + "".join(f"<li>{esc(c)}</li>" for c in script["checks"]) + "</ul>")

    eid = esc(ep.id)
    if ep.status == REVIEW:
        options = [script.get("title", "")] + script.get("title_options", [])
        hint = " / ".join(esc(o) for o in options[1:] if o)
        api = studio.cfg["youtube"].get("upload") == "api"
        body.append(f"""
<form method='post' action='/ep/{eid}/approve'>
<label>タイトル</label><input name='title' value='{esc(final.get('title', ''))}'>
{f"<div class='muted'>別案: {hint}</div>" if hint else ""}
<label>概要欄</label><textarea name='description'>{esc(final.get('description', ''))}</textarea>
<label>タグ（カンマ区切り）</label><input name='tags' value='{esc(', '.join(final.get('tags', [])))}'>
<label>公開日時</label><input type='datetime-local' name='publish_at'
 value='{esc(studio.next_slot()[:16])}'>
<button class='ok'>{'承認して予約投稿する' if api else '承認する（このあとYouTube Studioへ貼る）'}</button>
</form>
<form method='post' action='/ep/{eid}/reject'>
<label>見送る理由（次の台本づくりに活かします）</label>
<input name='reason' placeholder='例: 前置きが長い／数字の根拠が弱い／このテーマは需要がない'>
<button class='ng'>見送る</button></form>""")
    elif ep.status == APPROVED and studio.cfg["youtube"].get("upload") == "api":
        if ep.data.get("error"):
            body.append(f"<p class='err'>{esc(ep.data['error'])}</p>")
        body.append(f"<form method='post' action='/ep/{eid}/upload'>"
                    f"<button class='ok'>もう一度投稿する</button></form>")
    elif ep.status == APPROVED:
        body.append(f"""
<h2>YouTube Studio に貼る内容</h2>
<p class='muted'>YouTube Studio で動画（ショートだけの回はショート）をアップロードし、下をコピーして貼ってください。
公開日時 {esc(final.get('publish_at', ''))} で予約するのがおすすめです。</p>
<label>タイトル</label><input id='t' readonly value='{esc(final.get('title', ''))}'>
<button class='copy' data-copy='t'>コピー</button>
<label>概要欄</label><textarea id='d' readonly>{esc(final.get('description', ''))}</textarea>
<button class='copy' data-copy='d'>コピー</button>
<label>タグ</label><input id='g' readonly value='{esc(', '.join(final.get('tags', [])))}'>
<button class='copy' data-copy='g'>コピー</button>
<form method='post' action='/ep/{eid}/published'>
<label>投稿した動画のURL</label><input name='url' placeholder='https://youtu.be/...' required>
<button class='ok'>投稿したので記録する</button></form>""")
    elif ep.status == PUBLISHED:
        pub = ep.data.get("published", {})
        url = pub.get("url", "")
        body.append(f"<div class='card'>公開: <a href='{esc(url)}'>{esc(url)}</a></div>")
        if pub.get("thumbnail_error"):
            body.append(f"<p class='err'>サムネの設定に失敗: {esc(pub['thumbnail_error'])}</p>")
    elif ep.status == REJECTED:
        body.append(f"<div class='card'>見送り理由: {esc(ep.data.get('reject_reason', ''))}</div>")

    if script.get("sections"):
        sections = "".join(
            f"<h3>{esc(s['heading'])}</h3><p>{esc(s['narration'])}</p>"
            for s in script.get("sections", []))
        body.append(f"<h2>台本</h2><details><summary>開く</summary>"
                    f"<p><strong>冒頭</strong> {esc(script.get('hook', ''))}</p>{sections}"
                    f"<p><strong>まとめ</strong> {esc(script.get('outro', ''))}</p></details>")
    return page(_title(ep), "".join(body))


class Handler(BaseHTTPRequestHandler):
    studio: Studio
    allow: list[ipaddress._BaseNetwork] = []

    def log_message(self, *args: Any) -> None:
        pass

    def _allowed(self) -> bool:
        if not self.allow:
            return True
        ip = ipaddress.ip_address(self.client_address[0])
        return any(ip in net for net in self.allow)

    def _send(self, status: int, body: bytes, ctype: str = "text/html; charset=utf-8",
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _redirect(self, to: str) -> None:
        self.send_response(303)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _episode(self, ep_id: str) -> Episode | None:
        try:
            return self.studio.library.get(ep_id)
        except KeyError:
            self._send(404, page("見つかりません", "<p>その動画は見つかりません。<a href='/'>一覧へ</a></p>"))
            return None

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        if not self._allowed():
            return self._send(403, b"forbidden", "text/plain")
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            return self._send(200, index_html(self.studio))
        m = re.fullmatch(r"/ep/([A-Za-z0-9_\-]+)", path)
        if m:
            ep = self._episode(m.group(1))
            if ep:
                self._send(200, episode_html(self.studio, ep))
            return None
        m = re.fullmatch(r"/media/([A-Za-z0-9_\-]+)/([A-Za-z0-9_.]+)", path)
        if m and m.group(2) in MEDIA:
            ep = self._episode(m.group(1))
            if ep:
                self._media(ep, m.group(2))
            return None
        return self._send(404, page("見つかりません", "<p><a href='/'>一覧へ</a></p>"))

    def _media(self, ep: Episode, name: str) -> None:
        f = ep.file(name)
        if not f.exists():
            return self._send(404, b"not found", "text/plain")
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        status = 200
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = int(rng.group(2)) if rng.group(2) else end
            else:
                start = max(0, size - int(rng.group(2)))
            end = min(end, size - 1)
            if start > end:
                return self._send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", MEDIA[name])
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return None
        with f.open("rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(1 << 16, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                left -= len(chunk)
        return None

    def do_POST(self) -> None:  # noqa: N802
        if not self._allowed():
            return self._send(403, b"forbidden", "text/plain")
        m = re.fullmatch(r"/ep/([A-Za-z0-9_\-]+)/(approve|reject|published|upload)", self.path)
        if not m:
            return self._send(404, b"not found", "text/plain")
        length = int(self.headers.get("Content-Length", 0) or 0)
        form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode("utf-8"),
                                           keep_blank_values=True))
        ep_id, act = m.groups()
        try:
            if act == "approve":
                tags = [t for t in re.split(r"[,、]", form.get("tags", ""))]
                self.studio.approve(ep_id, form.get("title", ""), form.get("description", ""),
                                    tags, form.get("publish_at", ""))
            elif act == "reject":
                self.studio.reject(ep_id, form.get("reason", ""))
            elif act == "upload":
                self.studio.upload(self.studio.library.get(ep_id))
            else:
                self.studio.mark_published(ep_id, form.get("url", ""))
        except KeyError:
            return self._send(404, page("見つかりません", "<p><a href='/'>一覧へ</a></p>"))
        except Exception as exc:  # 画面に理由を出して、もう一度押せるようにする
            ep = self._episode(ep_id)
            if ep:
                self._send(400, episode_html(self.studio, ep, f"できませんでした: {exc}"))
            return None
        return self._redirect(f"/ep/{ep_id}")


def make_server(studio: Studio, host: str | None = None, port: int | None = None
                ) -> ThreadingHTTPServer:
    r = studio.cfg["review"]
    allow: list[Any] = []
    if r.get("lan_only", True):
        allow = [ipaddress.ip_network(n) for n in
                 ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128")]
    handler = type("BoundHandler", (Handler,), {"studio": studio, "allow": allow})
    return ThreadingHTTPServer((host or r.get("host", "0.0.0.0"),
                                port if port is not None else int(r.get("port", 8950))), handler)


"""コマンド。ふだん使うのは3つだけ:

    python run.py setup     最初に1回。チャンネルのテーマ等を設定する
    python run.py auto      毎日1回（タスクスケジューラから自動）。1本作って確認待ちへ
    python run.py review    確認画面を開く（スマホからも見られる）
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import urllib.request
import webbrowser
from typing import Any

from . import config
from .episode import LABELS
from .pipeline import Studio


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="run.py", description="YouTube チャンネル運営の自動化")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="チャンネルのテーマ等を対話で設定する")
    sub.add_parser("check", help="必要なもの（AI・VOICEVOX・ffmpeg・フォント）がそろっているか")
    sp = sub.add_parser("plan", help="企画を足す")
    sp.add_argument("-n", type=int, default=0)
    sm = sub.add_parser("make", help="動画を作って確認待ちにする")
    sm.add_argument("-n", type=int, default=1)
    sub.add_parser("auto", help="再生数の取り込み → 企画 → 1本作る（毎日の自動実行用）")
    sr = sub.add_parser("review", help="確認画面を開く")
    sr.add_argument("--open", action="store_true", help="ブラウザを開く")
    sr.add_argument("--port", type=int)
    sub.add_parser("list", help="動画の一覧")
    sa = sub.add_parser("approve", help="承認する")
    sa.add_argument("id")
    sj = sub.add_parser("reject", help="見送る")
    sj.add_argument("id")
    sj.add_argument("reason", nargs="?", default="")
    sub.add_parser("auth", help="YouTube の認証（初回だけ）")
    sub.add_parser("stats", help="再生数を取り込む")
    return p


def ask(label: str, current: str) -> str:
    shown = f"（いま: {current}）" if current else ""
    value = input(f"{label}{shown}\n> ").strip()
    return value or current


def setup(cfg: dict[str, Any]) -> int:
    ch = cfg["channel"]
    print("チャンネルのことを教えてください。空のまま Enter で今の値を残します。\n")
    patch = {"channel": {
        "name": ask("チャンネル名", ch.get("name", "")),
        "url": ask("チャンネルのURL", ch.get("url", "")),
        "theme": ask("テーマ（何を扱うチャンネルか）", ch.get("theme", "")),
        "audience": ask("誰に向けたチャンネルか（例: 30代で副業を始めたい会社員）",
                        ch.get("audience", "")),
        "promise": ask("見た人が得られるもの（例: 10分で手順が分かり今日から試せる）",
                       ch.get("promise", "")),
    }}
    backend = ask("台本を書くAI（ollama=手元のローカルAI・無料 / claude=Claude API・高品質）",
                  cfg["writer"].get("backend", "ollama"))
    patch["writer"] = {"backend": "claude" if backend.lower().startswith("c") else "ollama"}
    saved = config.save_local(patch)
    print(f"\n保存しました: {saved}\n次は `python run.py check` で準備を確かめてください。")
    return 0


def check(cfg: dict[str, Any]) -> int:
    from .render import RenderError, find_font
    from .voice import VoiceError, make_voice

    ok = True

    def line(good: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(("[OK] " if good else "[NG] ") + label + (f" — {detail}" if detail else ""))

    try:
        config.require_channel(cfg)
        line(True, "チャンネル設定", cfg["channel"]["theme"])
    except config.ConfigError as exc:
        line(False, "チャンネル設定", str(exc))
    line(bool(shutil.which("ffmpeg")), "ffmpeg", "" if shutil.which("ffmpeg")
         else "setup.bat で入れるか、ffmpeg をPATHに通してください")
    try:
        line(True, "日本語フォント", find_font(cfg["render"].get("font", "")))
    except RenderError as exc:
        line(False, "日本語フォント", str(exc))
    try:
        make_voice(cfg).synth("テスト")
        line(True, "VOICEVOX")
    except VoiceError as exc:
        line(False, "VOICEVOX", str(exc))
    w = cfg["writer"]
    if w.get("backend") == "claude":
        line(bool(os.environ.get("ANTHROPIC_API_KEY")), "Claude APIキー",
             "" if os.environ.get("ANTHROPIC_API_KEY") else "環境変数 ANTHROPIC_API_KEY を設定してください")
    else:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(w["ollama_url"].rstrip("/") + "/api/tags", timeout=5) as r:
                names = [m["name"] for m in json.loads(r.read()).get("models", [])]
            model = w.get("ollama_model", "")
            has = any(n == model or n.split(":")[0] == model for n in names)
            line(has, "ローカルAI（Ollama）", model if has else
                 f"{model} がありません。入っているモデル: {', '.join(names) or 'なし'}")
        except OSError as exc:
            line(False, "ローカルAI（Ollama）", f"起動していません（{exc}）")
    y = cfg["youtube"]
    studio = Studio(cfg)
    line(True, "YouTube への投稿方法", "承認画面から手動で貼る（manual）" if y.get("upload") != "api"
         else "承認ボタンでAPI投稿（api）")
    print("[--] 再生数の取り込み: " + ("設定済み" if studio.youtube_ready(y)
                                    else "未設定（`python run.py auth` で有効になります）"))
    print("\nすべて OK なら `python run.py auto` で1本目を作れます。" if ok
          else "\n[NG] の項目を直してから進めてください。")
    return 0 if ok else 1


def lan_address() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 9))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        cfg = config.load()
        if args.cmd == "setup":
            return setup(cfg)
        if args.cmd == "check":
            return check(cfg)
        studio = Studio(cfg)
        if args.cmd == "plan":
            for ep in studio.plan(args.n or None):
                print("企画:", ep.data["topic"]["title"])
        elif args.cmd == "make":
            for ep in studio.make(args.n):
                print("確認待ちに追加:", ep.data["script"]["title"])
        elif args.cmd == "auto":
            for line in studio.auto():
                print(line)
        elif args.cmd == "list":
            for ep in studio.library:
                title = (ep.data.get("script") or {}).get("title") or ep.data["topic"]["title"]
                print(f"{LABELS.get(ep.status, ep.status):<10} {ep.id}  {title}")
        elif args.cmd == "approve":
            ep = studio.approve(args.id)
            print(LABELS[ep.status], ep.data.get("published", {}).get("url", ""))
        elif args.cmd == "reject":
            studio.reject(args.id, args.reason)
            print("見送りました")
        elif args.cmd == "auth":
            studio.youtube.authorize()
            print("認証できました。再生数の取り込みが使えます。")
        elif args.cmd == "stats":
            print(f"{studio.refresh_stats()}本の再生数を取り込みました")
        elif args.cmd == "review":
            from .review import make_server
            server = make_server(studio, port=args.port)
            port = server.server_address[1]
            print(f"確認画面: http://127.0.0.1:{port}")
            print(f"スマホ・SOT21から: http://{lan_address()}:{port}")
            print("止めるときはこの画面を閉じるか Ctrl+C")
            if args.open:
                webbrowser.open(f"http://127.0.0.1:{port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    except Exception as exc:  # 黒い画面に読める理由を出して終わる
        print(f"[エラー] {exc}", file=sys.stderr)
        return 1

"""Command line entry point.

    python run.py init                 brain を作成し既定ロールを投入
    python run.py seed                 SYNAPTIC GROVE のサンプルを投入
    python run.py serve [--host --port --api-key]
    python run.py mcp                  MCP server (stdio)
    python run.py context <role> [--project] [--budget]
    python run.py index --project P --dir DIR [--pattern *.md]
    python run.py verify [--project P]
    python run.py export [--out brain.md]
    python run.py key                  API キーを生成して表示
    python run.py grow [--base M]      第二の脳を焼き込んでローカルAIを育てる
    python run.py ask "質問" [--project]  ローカルAIに第二の脳を前提に聞く
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import auth, server as server_module
from .app import App, render_brain_markdown
from .config import Config
from .context import ContextRouter
from .defaults import install_defaults, seed_demo
from .store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="second-brain",
                                     description="SECOND BRAIN — 複数AIの中央管理層")
    parser.add_argument("--db", help="brain.db のパス (既定: ~/.second_brain/brain.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="DB作成と既定ロール投入")
    sub.add_parser("seed", help="サンプルプロジェクト投入")
    sub.add_parser("key", help="APIキーを生成")

    serve = sub.add_parser("serve", help="Webサーバー起動")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--api-key")
    serve.add_argument("--budget", type=int, help="context のトークン上限")
    serve.add_argument("--open", action="store_true",
                       help="起動後にブラウザを自動で開く")

    sub.add_parser("mcp", help="MCP server (stdio) 起動")

    ctx = sub.add_parser("context", help="役割別コンテキストを表示")
    ctx.add_argument("role")
    ctx.add_argument("--project")
    ctx.add_argument("--budget", type=int, default=2000)

    scan = sub.add_parser("scan", help="ファイル名で自動検出して一括登録（本文は読まない）")
    scan.add_argument("--project", required=True)
    scan.add_argument("--dir", required=True)
    scan.add_argument("--keywords", default="ハンドオフ,handoff",
                      help="ファイル名に含まれる語（カンマ区切り）")
    scan.add_argument("--owner", default="")

    load = sub.add_parser("load", help="テキストファイルから企画・私についてを一括投入")
    load.add_argument("--file", required=True)
    load.add_argument("--fallback", default="",
                      help="PROJECT行の前に書かれた分の行き先（省略時は取り込まない）")

    index = sub.add_parser("index", help="既存ハンドオフを索引に登録（本文は読まない）")
    index.add_argument("--project", required=True)
    index.add_argument("--dir", required=True)
    index.add_argument("--pattern", default="*.md")
    index.add_argument("--owner", default="")
    index.add_argument("--recursive", action="store_true")

    verify = sub.add_parser("verify", help="索引したファイルの存在確認")
    verify.add_argument("--project")

    export = sub.add_parser("export", help="brain.md を書き出す")
    export.add_argument("--out")

    grow = sub.add_parser("grow", help="第二の脳を焼き込んでローカルAI（Ollama）を育てる")
    grow.add_argument("--base", help="育てる元のモデル（例: qwen2.5:7b）。次回から省略可")
    grow.add_argument("--name", help="育てたモデルの名前（既定: second-brain）")
    grow.add_argument("--url", help="Ollama の場所（既定: http://127.0.0.1:11434）")
    grow.add_argument("--modelfile", help="Modelfile を書き出すだけ（Ollamaへは送らない）")

    ask = sub.add_parser("ask", help="ローカルAIに第二の脳を前提に質問する")
    ask.add_argument("message")
    ask.add_argument("--project")
    ask.add_argument("--role", default="local")
    return parser


def index_directory(store: Store, project: str, directory: str, pattern: str,
                    owner: str = "", recursive: bool = False) -> list[str]:
    """Register every matching file as a handoff. Bodies are never read."""
    root = Path(directory).expanduser()
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    files = sorted(root.rglob(pattern) if recursive else root.glob(pattern))
    registered = []
    for path in files:
        if not path.is_file():
            continue
        handoff_id = path.stem
        store.upsert_handoff(handoff_id, project, str(path), title=path.stem,
                             phase=path.stem.split("_")[0], owner=owner,
                             actor="cli")
        registered.append(handoff_id)
    return registered


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.from_env()
    if args.db:
        config.db_path = Path(args.db).expanduser()
    store = Store.open(config.db_path)
    install_defaults(store)

    if args.command == "init":
        print(f"initialised {config.db_path}")
        print("role profiles: " + ", ".join(p["id"] for p in store.list_role_profiles()))
        return 0

    if args.command == "seed":
        pid = seed_demo(store)
        print(f"seeded project: {pid}")
        return 0

    if args.command == "key":
        key = auth.generate_key()
        print(key)
        print("\n使い方:\n  set SECOND_BRAIN_API_KEY=" + key
              + "\n  python run.py serve --host 0.0.0.0")
        return 0

    if args.command == "serve":
        config.host = args.host or config.host
        config.port = args.port or config.port
        config.api_key = args.api_key or config.api_key
        config.token_budget = args.budget or config.token_budget
        server_module.serve(App(store, config), config, open_browser=args.open)
        return 0

    if args.command == "mcp":
        from .mcp_server import MCPServer
        MCPServer(store, config.token_budget).run()
        return 0

    if args.command == "context":
        result = ContextRouter(store, args.budget).build(args.role, args.project)
        print(result["text"])
        print(f"\n--- ≈{result['token_estimate']} tokens "
              f"(budget {result['token_budget']})", file=sys.stderr)
        return 0

    if args.command == "load":
        from .intake import apply_bulk, parse_bulk
        path = Path(args.file).expanduser()
        if not path.is_file():
            print(f"ファイルが見つかりません: {path}")
            return 1
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "cp932"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", "replace")

        bulk = parse_bulk(text)
        result = apply_bulk(store, bulk, actor="load",
                            unassigned_project=args.fallback)
        print(f"取り込みました: {path.name}")
        if result["profile"]:
            print(f"  私について  {result['profile']} 件")
        for entry in result["projects"]:
            counts = "、".join(f"{k} {v}" for k, v in entry["written"].items() if v)
            print(f"  {entry['name']}  {counts or '（変更なし）'}")
        print(f"合計 {result['total']} 件")
        unknown = sum(len(p["parsed"]["unknown"]) for p in bulk["projects"])
        if unknown:
            print(f"※ 読み取れなかった行が {unknown} 行あります")
        return 0

    if args.command == "scan":
        from .scan import import_handoffs
        keywords = tuple(k.strip() for k in args.keywords.split(",") if k.strip())
        store.upsert_project(args.project, args.project, actor="cli")
        result = import_handoffs(store, args.project, args.dir, keywords,
                                 owner=args.owner, actor="cli")
        if result.get("error"):
            print(result["error"])
            return 1
        print(f"新規 {len(result['added'])} 件 / 登録済み {len(result['already'])} 件"
              f" / 調べたファイル {result['scanned']} 件 ({result['seconds']}秒)")
        for handoff in result["added"]:
            print(f"  {handoff['id']}  {handoff['file_path']}")
        return 0

    if args.command == "index":
        registered = index_directory(store, args.project, args.dir, args.pattern,
                                     args.owner, args.recursive)
        print(f"indexed {len(registered)} handoff(s): " + ", ".join(registered))
        return 0

    if args.command == "verify":
        result = store.verify_handoffs(args.project)
        print(f"checked {result['checked']} handoff(s)")
        if result["missing"]:
            print("MISSING: " + ", ".join(result["missing"]))
        return 1 if result["missing"] else 0

    if args.command == "export":
        markdown = render_brain_markdown(store)
        if args.out:
            Path(args.out).write_text(markdown, encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(markdown)
        return 0

    if args.command == "grow":
        return _grow(store, args)

    if args.command == "ask":
        from .local_ai import LocalAI, LocalAIError, converse
        try:
            history = converse(LocalAI.from_store(store),
                               ContextRouter(store, config.token_budget), [],
                               args.message, args.role, args.project)
        except LocalAIError as exc:
            print(exc)
            return 1
        print(history[-1]["content"])
        return 0

    return 1


def _grow(store: Store, args: argparse.Namespace) -> int:
    from . import local_ai
    settings = local_ai.load_settings(store)
    settings.base_model = args.base or settings.base_model
    settings.name = args.name or settings.name
    settings.url = args.url or settings.url
    local_ai.save_settings(store, settings)

    persona = local_ai.build_persona(store)
    if args.modelfile:
        base = settings.base_model or "qwen2.5:7b"
        Path(args.modelfile).write_text(local_ai.modelfile(base, persona),
                                        encoding="utf-8")
        print(f"書き出しました: {args.modelfile}")
        print(f"  ollama create {settings.name} -f {args.modelfile}")
        return 0

    ai = local_ai.LocalAI(settings)
    if not settings.base_model:
        status = ai.status()
        print("育てる元のモデルを --base で指定してください。")
        if status["models"]:
            print("  入っているモデル: " + ", ".join(status["models"]))
        elif status["error"]:
            print("  " + status["error"])
        return 1
    print(f"{settings.base_model} に第二の脳を焼き込んでいます…")
    try:
        entry = local_ai.grow(ai, store)
    except local_ai.LocalAIError as exc:
        print(exc)
        return 1
    log = local_ai.growth_log(store)
    print(f"育ちました: {entry['name']}（{len(log)} 回目）")
    print(f"  私について {entry['profile']} / 企画 {entry['projects']} / "
          f"確定事項 {entry['decisions']} / 事実 {entry['facts']}"
          f"（約 {entry['tokens']} トークン）")
    print(f"  話しかける: ollama run {entry['name']}")
    return 0

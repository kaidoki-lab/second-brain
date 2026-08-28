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

    sub.add_parser("mcp", help="MCP server (stdio) 起動")

    ctx = sub.add_parser("context", help="役割別コンテキストを表示")
    ctx.add_argument("role")
    ctx.add_argument("--project")
    ctx.add_argument("--budget", type=int, default=2000)

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
        server_module.serve(App(store, config), config)
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

    return 1

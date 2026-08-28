"""MCP server over stdio (spec PHASE 8).

Exposes the brain to ChatGPT / Claude / Codex / Gemini through one tool set so
every model reads and writes the same source of truth:

    get_project_state, get_context, get_decisions, get_handoffs,
    get_dependencies, write_decision, update_state, write_handoff,
    write_relation, list_projects

Speaks JSON-RPC 2.0 line-delimited on stdin/stdout — no dependencies.
"""

from __future__ import annotations

import json
import sys
from typing import Any, IO

from .context import ContextRouter
from .store import Invalid, NotFound, Store

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "second-brain", "version": "1.0.0"}


def _text(value: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": value}]}


def _json(value: Any) -> dict[str, Any]:
    return _text(json.dumps(value, ensure_ascii=False, indent=2))


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_projects",
        "description": "登録済みプロジェクトの一覧。",
        "inputSchema": {"type": "object", "properties": {
            "status": {"type": "string", "description": "ACTIVE などで絞り込む"}}},
    },
    {
        "name": "get_project_state",
        "description": "プロジェクトの現在地（現フェーズ、状態、担当、依存、LOCKED決定）。",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}}, "required": ["project"]},
    },
    {
        "name": "get_context",
        "description": "役割別に圧縮したコンテキストを取得する。役割ごとに見える情報が異なる。",
        "inputSchema": {"type": "object", "properties": {
            "role": {"type": "string",
                     "description": "role profile id か agent id (progress/design/builder/critic/explorer)"},
            "project": {"type": "string"},
            "budget": {"type": "integer", "description": "上限トークン(既定2000)"}},
            "required": ["role"]},
    },
    {
        "name": "get_decisions",
        "description": "決定事項の一覧。status で LOCKED / PROPOSED を絞り込める。",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}, "status": {"type": "string"}},
            "required": ["project"]},
    },
    {
        "name": "get_handoffs",
        "description": "ハンドオフ索引（本文は含まない。file_path を参照すること）。",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}, "status": {"type": "string"}},
            "required": ["project"]},
    },
    {
        "name": "get_dependencies",
        "description": "ノード（フェーズ等）の依存関係を取得する。",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"},
            "node": {"type": "string", "description": "省略時は現フェーズ"}},
            "required": ["project"]},
    },
    {
        "name": "write_decision",
        "description": "決定事項を保存する。会話ではなく結論だけを書くこと。",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}, "title": {"type": "string"},
            "body": {"type": "string"},
            "status": {"type": "string", "enum": ["LOCKED", "PROPOSED", "SUPERSEDED"]},
            "phase": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "actor": {"type": "string"}},
            "required": ["project", "title"]},
    },
    {
        "name": "update_state",
        "description": "現在フェーズと進行状態を更新する。",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}, "phase": {"type": "string"},
            "status": {"type": "string"}, "owner": {"type": "string"},
            "note": {"type": "string"},
            "deliverables": {"type": "array", "items": {"type": "string"}},
            "actor": {"type": "string"}},
            "required": ["project", "phase"]},
    },
    {
        "name": "write_handoff",
        "description": "既存ファイルをハンドオフとして索引する（本文はコピーしない）。",
        "inputSchema": {"type": "object", "properties": {
            "id": {"type": "string"}, "project": {"type": "string"},
            "file_path": {"type": "string"}, "title": {"type": "string"},
            "phase": {"type": "string"}, "owner": {"type": "string"},
            "status": {"type": "string"}, "actor": {"type": "string"}},
            "required": ["id", "project", "file_path"]},
    },
    {
        "name": "write_relation",
        "description": "情報同士を接続する (例: GR-02 depends_on GR-01)。",
        "inputSchema": {"type": "object", "properties": {
            "project": {"type": "string"}, "src": {"type": "string"},
            "rel": {"type": "string"}, "dst": {"type": "string"},
            "actor": {"type": "string"}},
            "required": ["project", "src", "rel", "dst"]},
    },
]


class MCPServer:
    def __init__(self, store: Store, budget: int = 2000):
        self.store = store
        self.router = ContextRouter(store, budget)

    # ------------------------------------------------------------ dispatch

    def call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        store = self.store
        if name == "list_projects":
            return _json(store.list_projects(args.get("status")))
        if name == "get_project_state":
            pid = args["project"]
            overview = store.project_overview(pid)
            state = overview["state"]
            head = state["phase"].split()[0] if state else ""
            return _json({
                "project": overview["project"],
                "current_phase": state["phase"] if state else None,
                "status": state["status"] if state else None,
                "owner": state["owner"] if state else None,
                "deliverables": state["deliverables"] if state else [],
                "phases": overview["phases"],
                "dependencies": store.dependencies_of(pid, head) if head else [],
                "locked_decisions": [d["id"] + " " + d["title"]
                                     for d in store.list_decisions(pid, "LOCKED")],
            })
        if name == "get_context":
            result = self.router.build(args["role"], args.get("project"),
                                       args.get("budget"))
            return _text(result["text"])
        if name == "get_decisions":
            store.require_project(args["project"])
            return _json(store.list_decisions(args["project"], args.get("status")))
        if name == "get_handoffs":
            store.require_project(args["project"])
            return _json(store.list_handoffs(args["project"], args.get("status")))
        if name == "get_dependencies":
            pid = args["project"]
            node = args.get("node")
            if not node:
                state = store.current_state(pid)
                node = state["phase"].split()[0] if state else ""
            return _json({"node": node,
                          "depends_on": store.dependencies_of(pid, node),
                          "required_by": store.dependents_of(pid, node)})
        if name == "write_decision":
            return _json(store.add_decision(
                args["project"], args["title"], args.get("body", ""),
                args.get("status", "LOCKED"), args.get("phase", ""),
                _str_list(args.get("tags")), args.get("id"),
                actor=args.get("actor", "mcp")))
        if name == "update_state":
            return _json(store.set_state(
                args["project"], args["phase"], args.get("status", "IN_PROGRESS"),
                args.get("owner", ""), args.get("note", ""),
                _str_list(args.get("deliverables")), actor=args.get("actor", "mcp")))
        if name == "write_handoff":
            return _json(store.upsert_handoff(
                args["id"], args["project"], args["file_path"],
                args.get("title", ""), args.get("phase", ""), args.get("owner", ""),
                args.get("status", "ACTIVE"), actor=args.get("actor", "mcp")))
        if name == "write_relation":
            return _json(store.add_relation(
                args["project"], args["src"], args["rel"], args["dst"],
                actor=args.get("actor", "mcp")))
        raise NotFound(f"unknown tool: {name}")

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            return self._ok(msg_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            })
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return self._ok(msg_id, {})
        if method == "tools/list":
            return self._ok(msg_id, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            try:
                return self._ok(msg_id, self.call_tool(name, args))
            except KeyError as exc:
                return self._ok(msg_id, {**_text(f"missing argument: {exc}"),
                                         "isError": True})
            except (NotFound, Invalid) as exc:
                return self._ok(msg_id, {**_text(str(exc)), "isError": True})
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"unknown method: {method}"}}

    @staticmethod
    def _ok(msg_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    # --------------------------------------------------------------- stdio

    def run(self, stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle(message)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()

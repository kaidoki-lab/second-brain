"""フォルダを走査して、ハンドオフらしいファイルを索引に取り込む。

方針は本体と同じ: **中身は一切読まない**。見るのはファイル名とパスだけで、
実ファイルは移動もリネームもしない。索引に載るのは参照だけ。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterable

from .store import Store, path_exists

#: ファイル名に含まれていたら「ハンドオフ」とみなす語（大文字小文字は無視）。
DEFAULT_KEYWORDS = ("ハンドオフ", "handoff", "hand_off", "hand-off")

#: 走査しても意味がなく、時間だけ食うフォルダ。
SKIP_DIRS = {
    "windows", "program files", "program files (x86)", "programdata",
    "appdata", "$recycle.bin", "system volume information", "node_modules",
    ".git", ".svn", "__pycache__", "venv", ".venv", "site-packages",
    "temp", "tmp", "cache",
}

#: 暴走防止（ネットワークドライブや C:\ 直下を指定された場合の保険）。
MAX_FILES_SCANNED = 300_000
MAX_SECONDS = 120


def matches(name: str, keywords: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def find_files(root: str | Path, keywords: Iterable[str] = DEFAULT_KEYWORDS,
               recursive: bool = True, extensions: Iterable[str] | None = None,
               max_files: int = MAX_FILES_SCANNED,
               max_seconds: int = MAX_SECONDS) -> dict[str, Any]:
    """ファイル名に keywords を含むファイルを集める。中身は開かない。"""
    root_path = Path(root).expanduser()
    if not root_path.is_dir():
        return {"error": f"フォルダが見つかりません: {root}", "files": [],
                "scanned": 0, "seconds": 0.0, "stopped": False}

    started = time.monotonic()
    exts = {e.lower() if e.startswith(".") else "." + e.lower()
            for e in (extensions or [])}
    found: list[Path] = []
    scanned = 0
    stopped = False

    stack = [root_path]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue          # 権限のないフォルダは黙って飛ばす
        for entry in entries:
            if time.monotonic() - started > max_seconds or scanned >= max_files:
                stopped = True
                stack.clear()
                break
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                if recursive and entry.name.lower() not in SKIP_DIRS \
                        and not entry.name.startswith("."):
                    stack.append(entry)
                continue
            scanned += 1
            if exts and entry.suffix.lower() not in exts:
                continue
            if matches(entry.name, keywords):
                found.append(entry)

    found.sort(key=lambda p: str(p).lower())
    return {"files": found, "scanned": scanned, "stopped": stopped,
            "seconds": round(time.monotonic() - started, 1), "error": ""}


def guess_phase(name: str) -> str:
    """`GR-02_ハンドオフ.md` のような名前から工程IDらしき先頭を拾う。"""
    stem = Path(name).stem
    for separator in ("_", "-", " ", "　"):
        head = stem.split(separator)[0]
        if head and head != stem and any(ch.isdigit() for ch in head):
            return head
    return ""


def import_handoffs(store: Store, project_id: str, root: str | Path,
                    keywords: Iterable[str] = DEFAULT_KEYWORDS,
                    recursive: bool = True, owner: str = "",
                    extensions: Iterable[str] | None = None,
                    actor: str = "scan") -> dict[str, Any]:
    """走査してヒットしたファイルを索引へ登録する。

    同じパスが既に登録済みなら二重登録せず、存在フラグだけ更新する。
    """
    store.require_project(project_id)
    result = find_files(root, keywords, recursive, extensions)
    if result["error"]:
        return {**result, "added": [], "already": [], "files": []}

    added: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    for path in result["files"]:
        file_path = str(path)
        existing = store.get_handoff_by_path(file_path)
        if existing:
            store.upsert_handoff(existing["id"], existing["project_id"],
                                 file_path, title=existing["title"],
                                 phase=existing["phase"], owner=existing["owner"],
                                 status=existing["status"], actor=actor)
            already.append(store.get_handoff(existing["id"]))  # type: ignore[arg-type]
            continue
        handoff = store.upsert_handoff(
            store.next_handoff_id(), project_id, file_path,
            title=path.stem, phase=guess_phase(path.name), owner=owner,
            actor=actor)
        added.append(handoff)

    return {
        "added": added,
        "already": already,
        "scanned": result["scanned"],
        "seconds": result["seconds"],
        "stopped": result["stopped"],
        "error": "",
        "files": [str(p) for p in result["files"]],
    }

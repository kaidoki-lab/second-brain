"""Folder inspection (FILE group).

Read-only: count, size, newest entries and free space. Nothing here deletes,
moves or serves file contents to the tablet.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from . import ActionError, Result, action

NEWEST = 5


def inspect(folder: str) -> dict[str, Any]:
    root = Path(folder)
    if not root.is_dir():
        raise ActionError(f"フォルダが見つかりません: {folder}")
    files = [p for p in root.iterdir() if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    newest = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:NEWEST]
    usage = shutil.disk_usage(str(root))
    return {
        "path": str(root),
        "files": len(files),
        "folders": sum(1 for p in root.iterdir() if p.is_dir()),
        "size_mb": round(total / (1024 ** 2), 1),
        "free_gb": round(usage.free / (1024 ** 3), 1),
        "newest": [{"name": p.name,
                    "size_mb": round(p.stat().st_size / (1024 ** 2), 2),
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime)
                    .strftime("%Y-%m-%d %H:%M")} for p in newest],
    }


def check_folder(ctx, key: str, label: str) -> Result:
    folder = ctx.config.get("folders", {}).get(key)
    if not folder:
        raise ActionError(f"config.json の folders.{key} を設定してください")
    info = inspect(folder)
    lines = [f"PATH   {info['path']}",
             f"FILES  {info['files']} 件 / {info['folders']} フォルダ",
             f"SIZE   {info['size_mb']} MB",
             f"FREE   {info['free_gb']} GB", ""]
    lines += [f"{f['mtime']}  {f['size_mb']:>8} MB  {f['name']}"
              for f in info["newest"]] or ["(ファイルなし)"]
    return Result(True, f"{label} {info['files']}件 / 空き {info['free_gb']}GB",
                  "\n".join(lines), info)


@action("file_share", "共有フォルダ確認", "FILE", params={"folder": "share"})
def file_share(ctx, params: dict[str, Any]) -> Result:
    return check_folder(ctx, params.get("folder", "share"), "共有フォルダ")


@action("file_output", "Output確認", "FILE", params={"folder": "output"})
def file_output(ctx, params: dict[str, Any]) -> Result:
    return check_folder(ctx, params.get("folder", "output"), "Output")


@action("file_render", "Render確認", "FILE", params={"folder": "render"})
def file_render(ctx, params: dict[str, Any]) -> Result:
    return check_folder(ctx, params.get("folder", "render"), "Render")

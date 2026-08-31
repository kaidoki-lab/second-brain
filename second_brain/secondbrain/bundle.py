"""ハンドオフ本文を読み出して、AIに渡す「統合パック」を組み立てる。

読むのはこの瞬間だけで、本文をDBへ保存はしない（保存するのは、AIが出した
工程と決定事項だけ）。第二の脳を文章置き場にしないための線引き。
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from .store import Store

#: そのまま文字として読める拡張子。
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".log", ".csv", ".tsv", ".json",
                 ".yaml", ".yml", ".ini", ".rst", ""}
#: 中身を取り出せる Word 形式（zip + XML なので標準ライブラリだけで読める）。
DOCX_SUFFIXES = {".docx"}
#: 1ファイルあたりの上限。長すぎるハンドオフで全体が溢れるのを防ぐ。
PER_FILE_CHARS = 12_000
#: パック全体の上限（おおよそ 40,000〜60,000 トークン相当）。
TOTAL_CHARS = 120_000

ENCODINGS = ("utf-8-sig", "utf-8", "cp932", "shift_jis", "euc_jp")

HEADER = """以下は同じ企画のハンドオフ一式です。すべて読んだうえで、次を出力してください。

1. 工程表（着手順に並べ、依存関係が分かるように）
2. すでに確定していること（決定事項）
3. まだ決まっていないこと・矛盾している点

出力は必ず次の形式のみで、説明文は付けないでください。

PHASE: 工程名 | 状態(未着手/作業中/完了/停止中) | 担当 | 成果物をセミコロン区切り
DECISION: 決まったこと | 補足
FACT: 前提や制約 | タグをカンマ区切り
DEPENDS: 後の工程 -> 先に必要な工程
OPEN: まだ決まっていないこと

---
"""


def read_docx(path: Path, limit: int) -> str:
    """.docx から本文テキストだけを取り出す（段落単位）。"""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return text[:limit]


def read_file(file_path: str, limit: int = PER_FILE_CHARS) -> tuple[str, str]:
    """(本文, 読めなかった理由) を返す。読めれば理由は空。"""
    path = Path(file_path)
    if not path.exists():
        return "", "ファイルが見つかりません"
    suffix = path.suffix.lower()
    try:
        if suffix in DOCX_SUFFIXES:
            return read_docx(path, limit), ""
        if suffix not in TEXT_SUFFIXES:
            return "", f"{suffix or '拡張子なし'} は本文を読み取れません"
        raw = path.read_bytes()[: limit * 4]
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        return "", f"読み込めません（{exc.__class__.__name__}）"
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)[:limit], ""
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")[:limit], "文字コードを推定できませんでした"


def build_bundle(store: Store, project_id: str, handoff_ids: list[str] | None = None,
                 per_file: int = PER_FILE_CHARS, total: int = TOTAL_CHARS,
                 header: str = HEADER) -> dict[str, Any]:
    """選んだハンドオフの本文を1つの文章にまとめる（DBには保存しない）。"""
    project = store.require_project(project_id)
    handoffs = store.list_handoffs(project_id)
    if handoff_ids:
        wanted = set(handoff_ids)
        handoffs = [h for h in handoffs if h["id"] in wanted]

    parts = [header, f"企画: {project['name']}", ""]
    included: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    used = sum(len(p) for p in parts)
    truncated = False

    for handoff in handoffs:
        text, problem = read_file(handoff["file_path"], per_file)
        if problem and not text:
            skipped.append({"id": handoff["id"], "title": handoff["title"],
                            "path": handoff["file_path"], "reason": problem})
            continue
        block = (f"\n===== {handoff['title']} "
                 f"({handoff['phase'] or '工程不明'}) =====\n"
                 f"場所: {handoff['file_path']}\n\n{text.strip()}\n")
        if used + len(block) > total:
            truncated = True
            skipped.append({"id": handoff["id"], "title": handoff["title"],
                            "path": handoff["file_path"],
                            "reason": "全体の上限を超えるため今回は除外"})
            continue
        parts.append(block)
        used += len(block)
        included.append({**handoff, "chars": len(text), "note": problem})

    text = "\n".join(parts)
    return {
        "project": project,
        "text": text,
        "included": included,
        "skipped": skipped,
        "chars": len(text),
        "approx_tokens": len(text) // 2,
        "truncated": truncated,
        "candidates": len(handoffs),
    }

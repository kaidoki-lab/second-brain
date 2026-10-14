"""1本の動画＝1つのフォルダ。状態は episode.json に持つ。

    episodes/<id>/
      episode.json     状態・企画・台本・公開情報
      voice/           文ごとの音声（long_000.wav, short_000.wav …）
      timeline.json    文ごとの表示内容と長さ
      long.mp4 short.mp4 thumbnail.png

状態は前にしか進まない:

    PLANNED → SCRIPTED → VOICED → REVIEW → APPROVED → PUBLISHED
                                      └→ REJECTED（理由は次の台本へ活かす）

途中で失敗しても、次の実行はそのフォルダの続きから再開する。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PLANNED = "PLANNED"
SCRIPTED = "SCRIPTED"
VOICED = "VOICED"
REVIEW = "REVIEW"
APPROVED = "APPROVED"
PUBLISHED = "PUBLISHED"
REJECTED = "REJECTED"

LABELS = {
    PLANNED: "企画のみ", SCRIPTED: "台本あり", VOICED: "音声あり",
    REVIEW: "確認待ち", APPROVED: "承認済み（投稿待ち）",
    PUBLISHED: "公開済み", REJECTED: "見送り",
}
#: 自動で先へ進めてよい状態（承認より手前）。
IN_PROGRESS = (PLANNED, SCRIPTED, VOICED)

MEMORY_FILE = "_memory.json"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slug(text: str, limit: int = 24) -> str:
    """フォルダ名・URLに使うので英数字だけにする（日本語タイトルなら "ep"）。"""
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s[:limit] or "ep"


class Episode:
    def __init__(self, folder: Path, data: dict[str, Any]):
        self.folder = folder
        self.data = data

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def status(self) -> str:
        return self.data["status"]

    def file(self, name: str) -> Path:
        return self.folder / name

    def set(self, status: str | None = None, **fields: Any) -> "Episode":
        if status:
            self.data["status"] = status
            self.data.setdefault("history", []).append({"status": status, "at": now()})
        self.data.update(fields)
        self.save()
        return self

    def save(self) -> None:
        tmp = self.folder / "episode.json.tmp"
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.folder / "episode.json")


class Library:
    """episodes/ フォルダ全体。"""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, topic: dict[str, Any]) -> Episode:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = f"{stamp}-{slug(topic.get('title', ''))}"
        ep_id, n = base, 1
        while (self.root / ep_id).exists():
            n += 1
            ep_id = f"{base}-{n}"
        folder = self.root / ep_id
        folder.mkdir()
        ep = Episode(folder, {"id": ep_id, "status": PLANNED, "created_at": now(),
                              "topic": topic, "history": [{"status": PLANNED, "at": now()}]})
        ep.save()
        return ep

    def get(self, ep_id: str) -> Episode:
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", ep_id or ""):
            raise KeyError(ep_id)
        folder = self.root / ep_id
        meta = folder / "episode.json"
        if not meta.exists():
            raise KeyError(ep_id)
        return Episode(folder, json.loads(meta.read_text(encoding="utf-8")))

    def all(self) -> list[Episode]:
        out = []
        for meta in sorted(self.root.glob("*/episode.json")):
            out.append(Episode(meta.parent, json.loads(meta.read_text(encoding="utf-8"))))
        return out

    def by_status(self, *statuses: str) -> list[Episode]:
        return [ep for ep in self.all() if ep.status in statuses]

    def __iter__(self) -> Iterator[Episode]:
        return iter(self.all())

    # ---------------------------------------------------------- 学び
    # チャンネルが育つための記憶。見送り理由と再生数を次の企画・台本に渡す。

    def memory(self) -> dict[str, Any]:
        f = self.root / MEMORY_FILE
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        return {"feedback": [], "stats": {}, "stats_at": ""}

    def save_memory(self, memory: dict[str, Any]) -> None:
        (self.root / MEMORY_FILE).write_text(
            json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_feedback(self, text: str, episode_id: str = "") -> None:
        text = text.strip()
        if not text:
            return
        memory = self.memory()
        memory["feedback"].append({"text": text, "episode": episode_id, "at": now()})
        memory["feedback"] = memory["feedback"][-30:]
        self.save_memory(memory)

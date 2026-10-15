"""出演キャラ（PUPPET-AVATAR のキャラを毎回入れ替えて出す）。

channel.json の ``cast``:

    "cast": {
      "source": "C:/Users/pc/Desktop/PUPPET-AVATAR/characters",
      "members": [
        {"id": "puppet", "name": "腹話術人形", "speaker": 11,
         "credit": "VOICEVOX:玄野武宏", "persona": "司会口調。…", "link": "https://…"}
      ]
    }

- キャラの絵は PUPPET-AVATAR の ``characters/<id>/`` を **読むだけ**（書き込まない）。
  base.png に jaw.png（下あご）を下へずらして重ね、口の3段階の画像を作る。
  作った画像は ``episodes/_cast/<id>/`` に置き、元の絵が変わったときだけ作り直す
- 出演は毎回入れ替える（直前と同じキャラは出さない。出番の少ないキャラから）
- キャラごとの再生数・コメント数を集計して、どのキャラの反応が良いかを見る
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image

from .config import path as cfg_path

#: PUPPET-AVATAR の口の開き（puppet-avatar.js の jawByLevel の最大値。px は表示の高さ 1080 基準）
JAW_FULL_PX = 58.0
DISPLAY_HEIGHT = 1080.0
SPRITE_SIZE = 1024
CACHE = "_cast"


class CastError(Exception):
    pass


def members(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in cfg.get("cast", {}).get("members", []) if m.get("id")]


def enabled(cfg: dict[str, Any]) -> bool:
    return bool(members(cfg))


def member(cfg: dict[str, Any], cast_id: str) -> dict[str, Any]:
    for m in members(cfg):
        if m["id"] == cast_id:
            return m
    raise CastError(f"出演キャラ {cast_id} が channel.json の cast.members にありません")


# ================================================================== 出演の入れ替え

def pick(cfg: dict[str, Any], episodes: list[Any]) -> dict[str, Any]:
    """次の出演キャラ。出番の少ない順、同じ数なら並び順。直前と同じキャラは避ける。"""
    roster = members(cfg)
    if not roster:
        raise CastError("出演キャラが設定されていません（channel.json の cast.members）")
    cast_eps = sorted((ep for ep in episodes if ep.data.get("cast")),
                      key=lambda ep: ep.data.get("cast_at", ""))
    counts = {m["id"]: 0 for m in roster}
    for ep in cast_eps:
        if ep.data["cast"] in counts:
            counts[ep.data["cast"]] += 1
    last = cast_eps[-1].data["cast"] if cast_eps else ""
    choices = [m for m in roster if m["id"] != last] or roster
    return min(choices, key=lambda m: counts[m["id"]])


# ================================================================== 絵

def _source(cfg: dict[str, Any], cast_id: str) -> Path:
    src = cfg.get("cast", {}).get("source", "")
    if not src:
        raise CastError("cast.source（PUPPET-AVATAR の characters フォルダ）が未設定です")
    folder = cfg_path(cfg, src) / cast_id
    if not (folder / "character.json").exists():
        raise CastError(f"キャラが見つかりません: {folder}")
    return folder


def _square(img: Image.Image, size: int) -> Image.Image:
    """縦長の絵を正方形の透明な台紙に、下そろえ・左右中央で置く。"""
    img = img.copy()
    img.thumbnail((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.alpha_composite(img, ((size - img.width) // 2, size - img.height))
    return out


def build_mouths(folder: Path, size: int = SPRITE_SIZE) -> dict[str, Image.Image]:
    """PUPPET-AVATAR のキャラ1体から closed / half / open の3枚を作る。"""
    data = json.loads((folder / "character.json").read_text(encoding="utf-8"))
    layers = data.get("layers", {})
    base = Image.open(folder / layers.get("base", "base.png")).convert("RGBA")
    jaw = Image.open(folder / layers.get("jaw", "jaw.png")).convert("RGBA")
    prop = None
    if layers.get("prop") and (folder / layers["prop"]).exists():
        prop = Image.open(folder / layers["prop"]).convert("RGBA")
    max_open = float(data.get("motion", {}).get("jaw", {}).get("maxOpen", JAW_FULL_PX))
    full = min(max_open, JAW_FULL_PX) * base.height / DISPLAY_HEIGHT
    out = {}
    for name, ratio in (("closed", 0.0), ("half", 0.5), ("open", 1.0)):
        frame = base.copy()
        if jaw.size != base.size:
            jaw = jaw.resize(base.size)
        frame.alpha_composite(jaw, (0, int(round(full * ratio))))
        if prop is not None:
            frame.alpha_composite(prop.resize(base.size) if prop.size != base.size else prop)
        out[name] = _square(frame, size)
    return out


def sprite_dir(cfg: dict[str, Any], cast_id: str) -> Path:
    """口の3段階の画像があるフォルダ（無いか、元の絵が新しければ作り直す）。"""
    src = _source(cfg, cast_id)
    out = cfg_path(cfg, "episodes") / CACHE / cast_id
    newest = max(f.stat().st_mtime for f in src.iterdir() if f.is_file())
    files = [out / f"{n}.png" for n in ("closed", "half", "open")]
    if all(f.exists() and f.stat().st_mtime >= newest for f in files):
        return out
    out.mkdir(parents=True, exist_ok=True)
    for name, img in build_mouths(src).items():
        img.save(out / f"{name}.png")
    return out


def cfg_for(cfg: dict[str, Any], cast_id: str) -> dict[str, Any]:
    """その回の出演キャラの絵と声に差し替えた設定。"""
    m = member(cfg, cast_id)
    out = copy.deepcopy(cfg)
    out.setdefault("avatar", {}).update({"enabled": True,
                                         "dir": str(sprite_dir(cfg, cast_id))})
    if m.get("speaker") is not None:
        out["voice"]["speaker"] = int(m["speaker"])
    if m.get("credit"):
        out["voice"]["credit"] = m["credit"]
    return out


# ================================================================== 反応の集計

VIDEO_ID = re.compile(r"(?:youtu\.be/|/shorts/|[?&]v=)([A-Za-z0-9_-]{11})")


def video_ids(ep: Any) -> list[str]:
    pub = ep.data.get("published") or {}
    ids = [pub[k] for k in ("video_id", "short_id") if pub.get(k)]
    m = VIDEO_ID.search(pub.get("url", ""))
    if m and m.group(1) not in ids:
        ids.append(m.group(1))
    return ids


def report(cfg: dict[str, Any], episodes: list[Any], stats: dict[str, Any]
           ) -> list[dict[str, Any]]:
    """キャラごとの 公開本数・再生数・コメント数（平均再生の多い順）。"""
    rows = {m["id"]: {"id": m["id"], "name": m.get("name", m["id"]), "published": 0,
                      "views": 0, "comments": 0, "likes": 0} for m in members(cfg)}
    for ep in episodes:
        row = rows.get(ep.data.get("cast", ""))
        if row is None or ep.status != "PUBLISHED":
            continue
        row["published"] += 1
        for vid in video_ids(ep):
            s = stats.get(vid) or {}
            row["views"] += int(s.get("views", 0))
            row["comments"] += int(s.get("comments", 0))
            row["likes"] += int(s.get("likes", 0))
    for row in rows.values():
        row["avg_views"] = round(row["views"] / row["published"], 1) if row["published"] else 0
    return sorted(rows.values(), key=lambda r: (-r["avg_views"], -r["published"]))

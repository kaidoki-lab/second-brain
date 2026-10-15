"""パペットアバター（声に合わせて口がパクパク動く・ときどき瞬きする）。

口の開き具合は読み上げ音声の音量から決める（3段階: 閉じ・半開き・全開）。
画像は2通り:

- 自分のアバター: channel.json の ``avatar.dir`` に下の名前でPNG（背景透過）を置く
    closed.png  half.png  open.png              … 口の3段階（必須）
    closed_blink.png half_blink.png open_blink.png … 目を閉じた版（任意。無ければ瞬きしない）
- 置かなければ、内蔵のパペット（靴下パペット風）を自動で描く

動画には「状態が変わった瞬間だけ画像を切り替える」一覧を ffmpeg に渡して重ねるので、
8分の動画でも画像は6枚しか作らない。
"""

from __future__ import annotations

import array
import io
import random
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .config import path as cfg_path

MOUTHS = ("closed", "half", "open")


class AvatarError(Exception):
    pass


# ================================================================== 画像

def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def draw_puppet(mouth: int, blink: bool, size: int, color: str = "#f97316") -> Image.Image:
    """内蔵の靴下パペット。mouth: 0=閉じ 1=半開き 2=全開。

    パペットらしく、口を開くと頭（上あご）が持ち上がる。
    """
    s = 4  # 4倍で描いて縮小し、輪郭をなめらかにする
    W = size * s
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    body = _hex(color)
    dark = tuple(max(0, c - 60) for c in body)
    u = W / 100.0

    lift = (0, 6, 12)[mouth] * u          # 上あごの持ち上がり
    jaw_y = 66 * u                        # 口の線（閉じたとき）

    # 腕（袖）と下あご
    d.rounded_rectangle([22 * u, jaw_y, 78 * u, 100 * u], radius=10 * u, fill=body)
    # 口の中（開いたときだけ見える）
    if mouth:
        d.rounded_rectangle([24 * u, jaw_y - lift - 2 * u, 76 * u, jaw_y + 8 * u],
                            radius=8 * u, fill=(90, 20, 30))
        d.ellipse([38 * u, jaw_y - 2 * u, 62 * u, jaw_y + 8 * u], fill=(225, 90, 110))  # 舌
    # 頭（上あご）
    top = 16 * u - lift
    d.rounded_rectangle([18 * u, top, 82 * u, jaw_y - lift], radius=26 * u, fill=body)
    d.rounded_rectangle([18 * u, jaw_y - lift - 10 * u, 82 * u, jaw_y - lift],
                        radius=6 * u, fill=body)
    # 口の線
    d.line([20 * u, jaw_y - lift, 80 * u, jaw_y - lift], fill=dark, width=int(2 * u))
    # 目（大きなボタン目）
    for cx in (37, 63):
        ex, ey, r = cx * u, 34 * u - lift, 11 * u
        if blink:
            d.arc([ex - r, ey - r * 0.6, ex + r, ey + r * 0.6], 10, 170,
                  fill=(20, 20, 20), width=int(2.4 * u))
        else:
            d.ellipse([ex - r, ey - r, ex + r, ey + r], fill=(255, 255, 255),
                      outline=dark, width=int(1.2 * u))
            pr = r * 0.48
            d.ellipse([ex - pr, ey - pr + 2 * u, ex + pr, ey + pr + 2 * u], fill=(20, 20, 20))
            d.ellipse([ex - pr * 0.35, ey - pr * 0.3, ex + pr * 0.25, ey + pr * 0.3],
                      fill=(255, 255, 255))
    # 鼻
    d.ellipse([46 * u, 44 * u - lift, 54 * u, 50 * u - lift], fill=dark)
    return img.resize((size, size), Image.LANCZOS)


def sprites(cfg: dict[str, Any], size: int) -> dict[tuple[int, bool], Image.Image]:
    """(口の段階, 瞬き中か) → 画像。"""
    a = cfg.get("avatar", {})
    folder = a.get("dir", "")
    if folder:
        base = cfg_path(cfg, folder)
        out: dict[tuple[int, bool], Image.Image] = {}
        for i, name in enumerate(MOUTHS):
            f = base / f"{name}.png"
            if not f.exists():
                raise AvatarError(f"アバター画像がありません: {f}"
                                  "（closed.png / half.png / open.png の3枚が必要です）")
            img = Image.open(f).convert("RGBA")
            img.thumbnail((size, size), Image.LANCZOS)
            out[(i, False)] = img
            blink = base / f"{name}_blink.png"
            if blink.exists():
                b = Image.open(blink).convert("RGBA")
                b.thumbnail((size, size), Image.LANCZOS)
                out[(i, True)] = b
            else:
                out[(i, True)] = img
        return out
    color = a.get("color", "#f97316")
    return {(m, b): draw_puppet(m, b, size, color) for m in range(3) for b in (False, True)}


# ================================================================== 動き

def mouth_track(wav_bytes: bytes, fps: int) -> list[int]:
    """1コマごとの口の段階（0/1/2）。音量の大きさで決める。"""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getsampwidth() != 2:
            raise AvatarError("16bit のWAVだけ扱えます")
        rate, channels = w.getframerate(), w.getnchannels()
        samples = array.array("h", w.readframes(w.getnframes()))
    per = max(1, int(rate * channels / fps))
    levels = []
    for start in range(0, len(samples), per):
        chunk = samples[start:start + per]
        levels.append((sum(x * x for x in chunk[::4]) / max(1, len(chunk[::4]))) ** 0.5)
    loud = sorted(levels)[int(len(levels) * 0.95)] if levels else 0
    if loud <= 0:
        return [0] * len(levels)
    out = []
    for v in levels:
        r = v / loud
        out.append(2 if r > 0.55 else 1 if r > 0.18 else 0)
    # 1コマだけのパクつきはチラつくので、前後とそろえる
    for i in range(1, len(out) - 1):
        if out[i - 1] == out[i + 1] != out[i]:
            out[i] = out[i - 1]
    return out


def blink_track(frames: int, fps: int, seed: int = 7) -> list[bool]:
    rnd = random.Random(seed)
    out = [False] * frames
    t = int(fps * rnd.uniform(1.5, 3.0))
    length = max(1, int(fps * 0.12))
    while t < frames:
        for i in range(t, min(frames, t + length)):
            out[i] = True
        t += int(fps * rnd.uniform(2.5, 5.0))
    return out


def write_stream(cfg: dict[str, Any], narration: bytes, fps: int, size: int,
                 folder: Path) -> Path:
    """アバターの画像と、ffmpeg 用の切り替え一覧（concat）を書き出す。"""
    folder.mkdir(parents=True, exist_ok=True)
    images = sprites(cfg, size)
    names = {}
    for (m, b), img in images.items():
        name = f"avatar_{MOUTHS[m]}{'_blink' if b else ''}.png"
        img.save(folder / name)
        names[(m, b)] = name
    mouths = mouth_track(narration, fps)
    blinks = blink_track(len(mouths), fps)
    listing, run_state, run_len = [], None, 0
    for state in zip(mouths, blinks):
        if state == run_state:
            run_len += 1
            continue
        if run_state is not None:
            listing.append(f"file '{names[run_state]}'\nduration {run_len / fps:.4f}")
        run_state, run_len = state, 1
    if run_state is None:
        run_state, run_len = (0, False), 1
    listing.append(f"file '{names[run_state]}'\nduration {run_len / fps:.4f}")
    listing.append(f"file '{names[run_state]}'")
    out = folder / "avatar.txt"
    out.write_text("\n".join(listing) + "\n", encoding="utf-8")
    return out


def layout(size: tuple[int, int], cfg: dict[str, Any]) -> tuple[int, int, int]:
    """アバターの (大きさ, x, y)。横型は右側、縦型は中央。"""
    w, h = size
    if h > w:   # ショート
        s = int(w * 0.5)   # 見出しと字幕の帯の間に収める
        return s, (w - s) // 2, int(h * 0.30)
    s = int(h * 0.5)
    side = cfg.get("avatar", {}).get("position", "right")
    x = int(w * 0.03) if side == "left" else w - s - int(w * 0.03)
    return s, x, int(h * 0.22)


def enabled(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("avatar", {}).get("enabled", False))

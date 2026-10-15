"""台本と音声から動画を組み立てる（Pillow で画面を描き、ffmpeg でつなぐ）。

画面は「見出し＋要点」のスライドに、いま読んでいる文を字幕として重ねる。
1文ごとに1枚の画像を作り、その文の音声の長さだけ表示する。

- long.mp4      横 1920x1080 の本編
- short.mp4     縦 1080x1920 のショート（60秒以内）
- thumbnail.png 1280x720 のサムネイル
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import avatar
from .config import path as cfg_path
from .voice import concat

GAP = 0.25  # 文と文の間の無音（voice.concat と同じ値）
QUIZ_CARDS_TOP = 240  # クイズ画面の札の上端（幅1080基準。avatar.layout と合わせる）

FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
    r"C:\Windows\Fonts\meiryo.ttc", r"C:\Windows\Fonts\msgothic.ttc",
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


class RenderError(Exception):
    pass


def find_font(configured: str = "") -> str:
    for candidate in [configured] + FONT_CANDIDATES if configured else FONT_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    raise RenderError("日本語フォントが見つかりません。channel.json の render.font に"
                      " .ttf/.ttc のパスを書いてください")


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RenderError("ffmpeg が見つかりません。setup.bat を実行するか、"
                          "ffmpeg をインストールしてPATHを通してください")
    return exe


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
         width: int) -> list[str]:
    """日本語は単語の区切りがないので1文字ずつ詰めて折り返す。"""
    lines, line = [], ""
    for ch in text:
        if draw.textlength(line + ch, font=font) > width and line:
            lines.append(line)
            line = ch.lstrip() if ch == " " else ch
        else:
            line += ch
    if line:
        lines.append(line)
    return lines


class Painter:
    def __init__(self, cfg: dict[str, Any]):
        r = cfg["render"]
        self.font_path = find_font(r.get("font", ""))
        self.bg = _rgb(r.get("background", "#0f172a"))
        self.accent = _rgb(r.get("accent", "#facc15"))
        self.fg = _rgb(r.get("text", "#f8fafc"))
        self.channel = cfg["channel"].get("name", "")
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}

    def font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.font_path, size)
        return self._fonts[size]

    def _block(self, draw, xy, text, size, fill, width, max_lines, spacing=1.35):
        x, y = xy
        font = self.font(size)
        lines = wrap(draw, text, font, width)[:max_lines]
        for line in lines:
            draw.text((x, y), line, font=font, fill=fill)
            y += int(size * spacing)
        return y

    def slide(self, size: tuple[int, int], heading: str, points: list[str],
              caption: str, progress: float, reserve: int = 0,
              reserve_left: bool = False) -> Image.Image:
        """reserve: アバターを置くために空けておく横幅（横型のみ）。"""
        w, h = size
        vertical = h > w
        unit = w / 1920 if not vertical else w / 1080
        img = Image.new("RGB", size, self.bg)
        draw = ImageDraw.Draw(img)
        margin = int(90 * unit)
        x0 = margin + (reserve if reserve_left else 0)
        text_w = w - margin * 2 - reserve
        top = int((260 if vertical else 80) * unit)

        # 見出し
        draw.rectangle([x0, top, x0 + int(14 * unit), top + int(84 * unit)],
                       fill=self.accent)
        y = self._block(draw, (x0 + int(40 * unit), top), heading,
                        int((84 if vertical else 72) * unit), self.fg,
                        text_w - int(40 * unit), 3 if vertical else 2)
        y += int(40 * unit)

        # 要点
        for point in points:
            draw.ellipse([x0 + int(10 * unit), y + int(24 * unit),
                          x0 + int(34 * unit), y + int(48 * unit)], fill=self.accent)
            y = self._block(draw, (x0 + int(60 * unit), y), point, int(56 * unit),
                            self.fg, text_w - int(60 * unit), 2) + int(18 * unit)

        # 字幕（いま読んでいる文）
        if caption:
            cap_size = int((66 if vertical else 54) * unit)
            lines = wrap(draw, caption, self.font(cap_size), w - margin * 2)[:3]
            band_h = int(cap_size * 1.4 * len(lines) + 60 * unit)
            band_top = h - band_h - int((420 if vertical else 40) * unit)
            draw.rectangle([0, band_top, w, band_top + band_h], fill=(0, 0, 0))
            cy = band_top + int(30 * unit)
            for line in lines:
                lw = draw.textlength(line, font=self.font(cap_size))
                draw.text(((w - lw) / 2, cy), line, font=self.font(cap_size), fill=(255, 255, 255))
                cy += int(cap_size * 1.4)

        # 進み具合（下端）とチャンネル名（右上。字幕と重ならない場所）
        draw.rectangle([0, h - int(10 * unit), int(w * progress), h], fill=self.accent)
        if self.channel:
            name_font = self.font(int(30 * unit))
            nw = draw.textlength(self.channel, font=name_font)
            draw.text((w - margin - nw, int(30 * unit)), self.channel,
                      font=name_font, fill=(148, 163, 184))
        return img

    def quiz_slide(self, size: tuple[int, int], heading: str, cards: list[dict[str, str]],
                   caption: str, progress: float, mark: str = "",
                   names: list[str] | None = None) -> Image.Image:
        """「ウソはどれだ」の縦型画面。上に A/B/C の札、真ん中にキャラ、下に字幕。

        mark: 答え合わせで「ウソ」の印をつける記号。アバターは avatar.layout の
        quiz 配置（札と字幕の間）に重なる。
        """
        w, h = size
        unit = w / 1080
        img = Image.new("RGB", size, self.bg)
        draw = ImageDraw.Draw(img)
        margin = int(60 * unit)

        hf = self.font(int(84 * unit))
        hw = draw.textlength(heading, font=hf)
        draw.text(((w - hw) / 2, int(110 * unit)), heading, font=hf, fill=self.accent,
                  stroke_width=int(4 * unit), stroke_fill=(0, 0, 0))

        y = QUIZ_CARDS_TOP * unit
        card_h = int(150 * unit)
        for card in cards:
            lie = card["letter"] == mark
            edge = (239, 68, 68) if lie else self.accent
            draw.rounded_rectangle([margin, y, w - margin, y + card_h], int(24 * unit),
                                   fill=(255, 255, 255), outline=edge, width=int(6 * unit))
            badge = int(100 * unit)
            bx, by = margin + int(24 * unit), y + (card_h - badge) // 2
            draw.ellipse([bx, by, bx + badge, by + badge], fill=edge)
            lf = self.font(int(64 * unit))
            lw = draw.textlength(card["letter"], font=lf)
            draw.text((bx + (badge - lw) / 2, by + int(8 * unit)), card["letter"], font=lf,
                      fill=(255, 255, 255))
            tx = bx + badge + int(28 * unit)
            size_t = int(46 * unit)
            n = len(wrap(draw, card["text"], self.font(size_t),
                         w - margin - tx - int(20 * unit))[:2])
            ty = y + (card_h - int(size_t * 1.3) * n) // 2 - int(4 * unit)
            self._block(draw, (tx, ty), card["text"], size_t,
                        (15, 23, 42), w - margin - tx - int(20 * unit), 2, 1.3)
            if lie:
                sf = self.font(int(56 * unit))
                stamp = "ウソ"
                sw = draw.textlength(stamp, font=sf)
                draw.text((w - margin - sw - int(16 * unit), y - int(40 * unit)), stamp,
                          font=sf, fill=(239, 68, 68), stroke_width=int(5 * unit),
                          stroke_fill=(255, 255, 255))
            y += card_h + int(24 * unit)

        if names:
            line = "正解: " + "・".join(names)
            self._block(draw, (margin, y + int(10 * unit)), line, int(44 * unit),
                        self.fg, w - margin * 2, 2)

        if caption:
            cap_size = int(62 * unit)
            lines = wrap(draw, caption, self.font(cap_size), w - margin * 2)[:3]
            band_h = int(cap_size * 1.4 * len(lines) + 60 * unit)
            band_top = h - band_h - int(150 * unit)
            draw.rectangle([0, band_top, w, band_top + band_h], fill=(0, 0, 0))
            cy = band_top + int(30 * unit)
            for line in lines:
                lw = draw.textlength(line, font=self.font(cap_size))
                draw.text(((w - lw) / 2, cy), line, font=self.font(cap_size),
                          fill=(255, 255, 255))
                cy += int(cap_size * 1.4)

        draw.rectangle([0, h - int(10 * unit), int(w * progress), h], fill=self.accent)
        if self.channel:
            name_font = self.font(int(30 * unit))
            nw = draw.textlength(self.channel, font=name_font)
            draw.text((w - margin - nw, int(40 * unit)), self.channel,
                      font=name_font, fill=(148, 163, 184))
        return img

    def thumbnail(self, text: str, sub: str = "") -> Image.Image:
        w, h = 1280, 720
        img = Image.new("RGB", (w, h), self.bg)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 40, h], fill=self.accent)
        size = 150
        while size > 60:
            lines = wrap(draw, text, self.font(size), w - 160)
            if len(lines) <= 2:
                break
            size -= 10
        lines = wrap(draw, text, self.font(size), w - 160)[:3]
        y = (h - len(lines) * size * 1.2) / 2 - (30 if sub else 0)
        for line in lines:
            # 縁取りで背景に負けないようにする
            draw.text((90, y), line, font=self.font(size), fill=self.fg,
                      stroke_width=8, stroke_fill=(0, 0, 0))
            y += size * 1.2
        if sub:
            draw.text((90, y + 20), sub, font=self.font(48), fill=self.accent,
                      stroke_width=4, stroke_fill=(0, 0, 0))
        return img


# ================================================================== 組み立て

def write_frames(painter: Painter, timeline: list[dict[str, Any]], size: tuple[int, int],
                 folder: Path, reserve: int = 0, reserve_left: bool = False) -> Path:
    """文ごとの画像と、ffmpeg 用の表示時間リストを書き出す。"""
    folder.mkdir(parents=True, exist_ok=True)
    total = sum(t["duration"] + GAP for t in timeline) or 1.0
    elapsed = 0.0
    listing = []
    for i, item in enumerate(timeline):
        elapsed += item["duration"] + GAP
        frame = folder / f"{i:04d}.png"
        if "cards" in item:
            painter.quiz_slide(size, item["heading"], item["cards"], item["text"],
                               elapsed / total, item.get("mark", ""),
                               item.get("names")).save(frame)
        else:
            painter.slide(size, item["heading"], item.get("points", []), item["text"],
                          elapsed / total, reserve, reserve_left).save(frame)
        listing.append(f"file '{frame.name}'\nduration {item['duration'] + GAP:.3f}")
    # concat は最後の1枚の時間を無視するので、最後をもう一度書く
    listing.append(f"file '{frame.name}'")
    concat_list = folder / "frames.txt"
    concat_list.write_text("\n".join(listing) + "\n", encoding="utf-8")
    return concat_list


def render(cfg: dict[str, Any], timeline: list[dict[str, Any]], voice_dir: Path,
           out: Path, size: tuple[int, int], work: Path) -> Path:
    if not timeline:
        raise RenderError("台本が空です")
    ffmpeg = find_ffmpeg()
    painter = Painter(cfg)
    fps = int(cfg["render"].get("fps", 30))
    narration_bytes = concat([(voice_dir / t["audio"]).read_bytes() for t in timeline], GAP)
    narration = work / "narration.wav"

    puppet = avatar.enabled(cfg)
    vertical = size[1] > size[0]
    if puppet:
        a_size, a_x, a_y = avatar.layout(size, cfg)
        left = cfg.get("avatar", {}).get("position", "right") == "left"
        # 横型は文字とアバターが重ならないよう横幅を空ける（縦型は上下で分ける）
        reserve = 0 if vertical else a_size + int(size[0] * 0.03)
        concat_list = write_frames(painter, timeline, size, work, reserve, left)
    else:
        concat_list = write_frames(painter, timeline, size, work)
    narration.write_bytes(narration_bytes)

    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
           "-i", str(concat_list), "-i", str(narration)]
    video = f"[0:v]fps={fps},format=yuv420p[v]"
    next_input = 2
    if puppet:
        stream = avatar.write_stream(cfg, narration_bytes, fps, a_size, work)
        cmd += ["-f", "concat", "-safe", "0", "-i", str(stream)]
        video = (f"[0:v]fps={fps}[bg];[{next_input}:v]fps={fps},format=rgba[av];"
                 f"[bg][av]overlay={a_x}:{a_y}:shortest=1,format=yuv420p[v]")
        next_input += 1
    audio = "[1:a]anull[a]"
    bgm = cfg["render"].get("bgm", "")
    if bgm and cfg_path(cfg, bgm).exists():
        vol = float(cfg["render"].get("bgm_volume", 0.08))
        cmd += ["-stream_loop", "-1", "-i", str(cfg_path(cfg, bgm))]
        audio = (f"[{next_input}:a]volume={vol}[b];"
                 f"[1:a][b]amix=inputs=2:duration=first[a]")
    cmd += ["-filter_complex", f"{video};{audio}", "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError("ffmpeg が失敗しました: " + result.stderr.strip()[-500:])
    return out


def render_thumbnail(cfg: dict[str, Any], text: str, out: Path, sub: str = "") -> Path:
    Painter(cfg).thumbnail(text, sub).save(out)
    return out


def load_timeline(file: Path) -> dict[str, list[dict[str, Any]]]:
    return json.loads(file.read_text(encoding="utf-8"))

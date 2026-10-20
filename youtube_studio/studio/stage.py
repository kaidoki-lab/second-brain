"""「人形劇場」の見た目（クイズ画面の背景・札・判子）。Pillow だけで描く。

    ┌ 幕の上飾り（金のふち）┐
    │幕   演目の題       幕│
    │     A/B/C の札        │
    │   （スポットライト）  │
    │      キャラ           │
    │══════ 舞台 ══════════│
    └  字幕                ┘

背景は大きさごとに1回だけ描いて使い回す（1本の動画で何十枚も描かないように）。
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

IVORY = (246, 238, 222)
INK = (40, 22, 22)
GOLD = (214, 178, 102)
GOLD_LIGHT = (246, 222, 160)
GOLD_DARK = (150, 112, 48)
VELVET = (122, 14, 28)
VELVET_DARK = (52, 4, 12)
STAMP = (196, 30, 36)

SERIF_CANDIDATES = [
    r"C:\Windows\Fonts\NotoSerifJP-VF.ttf", r"C:\Windows\Fonts\BIZ-UDMinchoM.ttc",
    r"C:\Windows\Fonts\yumindb.ttf", r"C:\Windows\Fonts\msmincho.ttc",
    "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSerifCJK-Bold.ttc",
]


def find_serif(configured: str = "") -> str:
    for c in ([configured] if configured else []) + SERIF_CANDIDATES:
        if c and Path(c).exists():
            return c
    return ""


@lru_cache(maxsize=64)
def serif(path: str, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size)
    try:  # 可変フォント（Noto Serif JP）は太さを選ぶ
        font.set_variation_by_name(weight)
    except (OSError, ValueError, AttributeError):
        pass
    return font


def _mix(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    return tuple(int(x + (y - x) * t) for x, y in zip(a, b))


def _glow(size: tuple[int, int], box: tuple[int, int, int, int], color: tuple[int, int, int],
          strength: float) -> Image.Image:
    """box に収まる、ふちのぼけた楕円の光（RGBA）。"""
    w, h = size
    x0, y0, x1, y1 = box
    mask = Image.new("L", (w, h), 0)
    pad_x, pad_y = (x1 - x0) * 0.18, (y1 - y0) * 0.18
    ImageDraw.Draw(mask).ellipse([x0 + pad_x, y0 + pad_y, x1 - pad_x, y1 - pad_y],
                                 fill=int(255 * strength))
    mask = mask.filter(ImageFilter.GaussianBlur(max(1, int(min(x1 - x0, y1 - y0) * 0.16))))
    layer = Image.new("RGBA", (w, h), color + (0,))
    layer.putalpha(mask)
    return layer


def _curtain(w: int, h: int, folds: int, flip: bool) -> Image.Image:
    """ひだのある赤い幕（縦の明暗）。flip で左右反転。"""
    img = Image.new("RGB", (w, h), VELVET)
    d = ImageDraw.Draw(img)
    for x in range(w):
        t = x / max(1, w - 1)
        fold = (math.cos(t * folds * 2 * math.pi) + 1) / 2          # ひだ
        edge = t ** 1.6                                             # 内側ほど暗い
        light = 0.35 + 0.65 * fold * (1 - 0.55 * edge)
        d.line([(x, 0), (x, h)], fill=_mix(VELVET_DARK, (176, 30, 46), light))
    return img.transpose(Image.FLIP_LEFT_RIGHT) if flip else img


@lru_cache(maxsize=4)
def background(w: int, h: int) -> Image.Image:
    unit = w / 1080
    img = Image.new("RGB", (w, h), (18, 8, 12))
    d = ImageDraw.Draw(img)
    # 奥の壁（上ほど暗い）
    for y in range(h):
        d.line([(0, y), (w, y)], fill=_mix((14, 6, 10), (44, 16, 22), (y / h) ** 0.8))
    img = img.convert("RGBA")
    # スポットライト（キャラの位置）と、上から差す光の帯
    img.alpha_composite(_glow((w, h), (int(-0.1 * w), int(0.30 * h), int(1.1 * w),
                                       int(0.86 * h)), (255, 214, 150), 0.42))
    beam = Image.new("L", (w, h), 0)
    ImageDraw.Draw(beam).polygon([(w * 0.40, 0), (w * 0.60, 0), (w * 0.86, h * 0.80),
                                  (w * 0.14, h * 0.80)], fill=34)
    beam = beam.filter(ImageFilter.GaussianBlur(int(40 * unit)))
    light = Image.new("RGBA", (w, h), (255, 230, 180, 0))
    light.putalpha(beam)
    img.alpha_composite(light)
    # 舞台の床
    floor_top = int(h * 0.755)
    fl = ImageDraw.Draw(img)
    for y in range(floor_top, h):
        t = (y - floor_top) / max(1, h - floor_top)
        fl.line([(0, y), (w, y)], fill=_mix((70, 38, 26), (16, 8, 6), t ** 0.7) + (255,))
    fl.line([(0, floor_top), (w, floor_top)], fill=GOLD_DARK + (255,), width=max(1, int(3 * unit)))
    img.alpha_composite(_glow((w, h), (int(0.18 * w), floor_top - int(40 * unit),
                                       int(0.82 * w), floor_top + int(120 * unit)),
                              (255, 200, 140), 0.5))
    # 両脇の幕
    cw = int(118 * unit)
    img.paste(_curtain(cw, h, 3, False), (0, 0))
    img.paste(_curtain(cw, h, 3, True), (w - cw, 0))
    # 上の飾り幕（波形のたれ）と金のふち
    swag_h = int(70 * unit)
    top = Image.new("RGBA", (w, swag_h + int(30 * unit)), (0, 0, 0, 0))
    td = ImageDraw.Draw(top)
    td.rectangle([0, 0, w, swag_h // 2], fill=VELVET_DARK + (255,))
    n = 6
    for i in range(n):
        x0 = i * w / n
        td.chord([x0 - 2, -swag_h, x0 + w / n + 2, swag_h + int(10 * unit)], 0, 180,
                 fill=VELVET + (255,))
        td.arc([x0 - 2, -swag_h, x0 + w / n + 2, swag_h + int(10 * unit)], 0, 180,
               fill=GOLD + (255,), width=max(2, int(5 * unit)))
    img.alpha_composite(top.filter(ImageFilter.SMOOTH), (0, 0))
    # 周辺を少し暗く
    vignette = Image.radial_gradient("L").resize((w, h)).point(lambda v: int(v * 0.55))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dark.putalpha(vignette)
    img.alpha_composite(dark)
    return img.convert("RGB")


def gold_text(img: Image.Image, xy: tuple[float, float], text: str,
              font: ImageFont.FreeTypeFont, shadow: int = 4) -> None:
    """上が明るく下が濃い、金の文字（影つき）。"""
    x, y = int(xy[0]), int(xy[1])
    box = ImageDraw.Draw(img).textbbox((x, y), text, font=font)
    w, h = box[2] - box[0] + 2, box[3] - box[1] + 2
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((x - box[0], y - box[1]), text, font=font, fill=255)
    grad = Image.new("RGB", (w, h))
    gd = ImageDraw.Draw(grad)
    for yy in range(h):
        t = yy / max(1, h - 1)
        gd.line([(0, yy), (w, yy)], fill=_mix(GOLD_LIGHT, GOLD_DARK, t ** 1.2) if t > 0.5
                else _mix((255, 246, 214), GOLD_LIGHT, t * 2))
    if shadow:
        img.paste((0, 0, 0), (box[0] + shadow, box[1] + shadow),
                  mask.point(lambda v: int(v * 0.7)))
    img.paste(grad, (box[0], box[1]), mask)


def ornament(draw: ImageDraw.ImageDraw, cx: float, y: float, half: float, unit: float) -> None:
    """題の下の飾り線 ── ◆ ──"""
    lw = max(1, int(2 * unit))
    r = 7 * unit
    draw.line([(cx - half, y), (cx - r * 2, y)], fill=GOLD, width=lw)
    draw.line([(cx + r * 2, y), (cx + half, y)], fill=GOLD, width=lw)
    draw.polygon([(cx, y - r), (cx + r, y), (cx, y + r), (cx - r, y)], fill=GOLD)


def card(img: Image.Image, box: tuple[int, int, int, int], unit: float,
         lie: bool = False) -> None:
    """象牙色の札（二重の金線。ウソの札はふちを朱に）。"""
    x0, y0, x1, y1 = box
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([x0 + 6 * unit, y0 + 10 * unit, x1 + 6 * unit,
                                              y1 + 10 * unit], int(14 * unit),
                                             fill=(0, 0, 0, 150))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(int(10 * unit))))
    d = ImageDraw.Draw(img)
    edge = STAMP if lie else GOLD
    d.rounded_rectangle(box, int(14 * unit), fill=IVORY + (255,), outline=edge + (255,),
                        width=max(2, int(4 * unit)))
    inset = int(10 * unit)
    d.rounded_rectangle([x0 + inset, y0 + inset, x1 - inset, y1 - inset], int(8 * unit),
                        outline=edge + (255,), width=max(1, int(1.5 * unit)))


def letter_badge(img: Image.Image, cx: float, cy: float, r: float, letter: str,
                 font: ImageFont.FreeTypeFont, lie: bool = False) -> None:
    d = ImageDraw.Draw(img)
    fill = STAMP if lie else VELVET
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill + (255,), outline=GOLD + (255,),
              width=max(2, int(r * 0.08)))
    d.text((cx, cy), letter, font=font, fill=IVORY, anchor="mm")


def stamp(img: Image.Image, center: tuple[float, float], text: str,
          font: ImageFont.FreeTypeFont, r: float) -> None:
    """朱色の丸い判子（少し傾けて押す）。"""
    s = int(r * 2.4)
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = s / 2
    w = max(3, int(r * 0.12))
    d.ellipse([c - r, c - r, c + r, c + r], outline=STAMP + (235,), width=w)
    d.ellipse([c - r * 0.82, c - r * 0.82, c + r * 0.82, c + r * 0.82],
              outline=STAMP + (235,), width=max(1, w // 3))
    d.ellipse([c - r * 0.74, c - r * 0.74, c + r * 0.74, c + r * 0.74], fill=STAMP + (225,))
    d.text((c, c), text, font=font, fill=IVORY + (255,), anchor="mm")
    layer = layer.rotate(-14, resample=Image.BICUBIC)
    img.alpha_composite(layer, (int(center[0] - s / 2), int(center[1] - s / 2)))

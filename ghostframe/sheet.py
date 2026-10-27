"""Render kept frames into a single timestamped contact sheet PNG."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ghostframe.frames import Frame

BG = (18, 18, 20)
FG = (235, 235, 235)
MUTED = (150, 150, 155)
LABEL_BG = (0, 0, 0, 190)


def fmt_ts(t: float) -> str:
    s = int(t)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def render(frames: list[Frame], out: Path, title: str, subtitle: str, cols: int, thumb_w: int) -> Path:
    first = Image.open(frames[0].path)
    thumb_h = round(thumb_w * first.height / first.width)
    cols = max(1, min(cols, len(frames)))
    rows = math.ceil(len(frames) / cols)
    gap, pad, header_h = 8, 16, 64

    width = pad * 2 + cols * thumb_w + (cols - 1) * gap
    height = pad + header_h + rows * thumb_h + (rows - 1) * gap + pad
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)

    title_font, sub_font = _font(24, bold=True), _font(15)
    draw.text((pad, pad), _fit(draw, title, title_font, width - 2 * pad), font=title_font, fill=FG)
    draw.text((pad, pad + 34), _fit(draw, subtitle, sub_font, width - 2 * pad), font=sub_font, fill=MUTED)

    label_font = _font(max(14, thumb_w // 16), bold=True)
    for i, f in enumerate(frames):
        x = pad + (i % cols) * (thumb_w + gap)
        y = pad + header_h + (i // cols) * (thumb_h + gap)
        img = Image.open(f.path).convert("RGB")
        if img.size != (thumb_w, thumb_h):
            img = img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        sheet.paste(img, (x, y))

        # Timestamp badge in the bottom-left corner, plus the frame index for referencing.
        label = f"#{i + 1}  {fmt_ts(f.t)}"
        l, t, r, b = draw.textbbox((0, 0), label, font=label_font)
        bw, bh = r - l + 12, b - t + 8
        badge = Image.new("RGBA", (bw, bh), LABEL_BG)
        ImageDraw.Draw(badge).text((6 - l, 4 - t), label, font=label_font, fill=FG)
        sheet.paste(badge, (x + 6, y + thumb_h - bh - 6), badge)

    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    return out

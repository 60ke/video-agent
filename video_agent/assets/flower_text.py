from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from video_agent.io import sha256_file

FONT_CANDIDATES = (
    Path(os.environ["VIDEO_AGENT_FONT"]) if os.environ.get("VIDEO_AGENT_FONT") else None,
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
)


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if candidate and candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    if shutil.which("fc-match"):
        resolved = subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Sans CJK SC:style=Bold"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout.strip()
        if resolved and Path(resolved).is_file():
            return ImageFont.truetype(resolved, size=size)
    raise FileNotFoundError("no supported Chinese font found for flower-text assets")


def _lines(text: str) -> list[str]:
    parts = [part.strip() for part in text.split("+") if part.strip()]
    if not parts:
        return [text.strip() or "填写必填项"]
    if len(parts) <= 2:
        return [" + ".join(parts)]
    midpoint = (len(parts) + 1) // 2
    return [" + ".join(parts[:midpoint]), " + ".join(parts[midpoint:])]


def _text_layer(size: tuple[int, int], text: str) -> Image.Image:
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    lines = _lines(text)
    font_size = max(42, min(86, round(width * (0.073 if len(text) <= 8 else 0.058))))
    font = _font(font_size)
    spacing = max(8, round(font_size * 0.18))
    stroke = max(3, font_size // 16)
    probe = ImageDraw.Draw(layer)
    boxes = [probe.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines]
    text_width = max(box[2] - box[0] for box in boxes)
    text_height = sum(box[3] - box[1] for box in boxes) + spacing * (len(lines) - 1)
    pad_x = max(28, round(font_size * 0.42))
    pad_y = max(20, round(font_size * 0.30))
    sticker_w = min(width - 48, text_width + pad_x * 2)
    sticker_h = text_height + pad_y * 2
    x = max(24, width - sticker_w - round(width * 0.045))
    y = min(height - sticker_h - 48, max(round(height * 0.60), round(height * 0.69) - sticker_h // 2))

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (x + 10, y + 14, x + sticker_w + 10, y + sticker_h + 14),
        radius=max(22, font_size // 2),
        fill=(0, 0, 0, 150),
    )
    layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(max(8, font_size // 8))))

    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(
        (x, y, x + sticker_w, y + sticker_h),
        radius=max(22, font_size // 2),
        fill=(26, 33, 56, 218),
        outline=(104, 214, 255, 235),
        width=max(3, font_size // 18),
    )
    accent_y = y + sticker_h - max(14, font_size // 5)
    draw.rounded_rectangle(
        (x + pad_x // 2, accent_y, x + sticker_w - pad_x // 2, accent_y + max(8, font_size // 8)),
        radius=max(4, font_size // 16),
        fill=(255, 184, 55, 225),
    )

    cursor_y = y + pad_y
    for index, line in enumerate(lines):
        box = boxes[index]
        line_w = box[2] - box[0]
        line_h = box[3] - box[1]
        tx = x + (sticker_w - line_w) // 2
        fill = (255, 224, 92, 255) if index == 0 else (246, 250, 255, 255)
        draw.text((tx, cursor_y - box[1]), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=(7, 11, 22, 255))
        cursor_y += line_h + spacing

    spark = max(6, font_size // 10)
    for sx, sy in ((x + 12, y - 12), (x + sticker_w - 16, y + 8), (x + sticker_w + 8, y + sticker_h // 2)):
        draw.ellipse((sx - spark, sy - spark, sx + spark, sy + spark), fill=(104, 214, 255, 235))
    return layer


def _composite(base: Image.Image, layer: Image.Image, opacity: float) -> Image.Image:
    overlay = layer.copy()
    if opacity < 1.0:
        overlay.putalpha(overlay.getchannel("A").point(lambda value: round(value * opacity)))
    result = base.copy()
    result.alpha_composite(overlay)
    return result


def build_flower_text_assets(source: Path, output: Path, text: str) -> dict[str, Any]:
    with Image.open(source) as opened:
        base = opened.convert("RGBA")
    layer = _text_layer(base.size, text)
    layer_dir = output.parent / "layers"
    stage_dir = output.parent / "stages"
    layer_dir.mkdir(parents=True, exist_ok=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    base_path = layer_dir / output.name.replace("关键帧", "无花字底图")
    layer_path = layer_dir / output.name.replace("关键帧", "花字透明层")
    stage1_path = stage_dir / output.name.replace("关键帧", "花字阶段1")
    stage2_path = stage_dir / output.name.replace("关键帧", "花字阶段2")

    base.save(base_path)
    layer.save(layer_path)
    _composite(base, layer, 0.55).convert("RGB").save(stage1_path)
    final = _composite(base, layer, 1.0).convert("RGB")
    final.save(stage2_path)
    final.save(output)

    return {
        "callout_base_path": base_path.resolve().as_posix(),
        "callout_base_sha256": sha256_file(base_path),
        "callout_layer_path": layer_path.resolve().as_posix(),
        "callout_layer_sha256": sha256_file(layer_path),
        "flower_text_stage1_path": stage1_path.resolve().as_posix(),
        "flower_text_stage1_sha256": sha256_file(stage1_path),
        "flower_text_stage2_path": stage2_path.resolve().as_posix(),
        "flower_text_stage2_sha256": sha256_file(stage2_path),
        "callout_layer_method": "deterministic_flower_text_overlay_v1",
        "animation_kind": "flower_text_fade_sequence",
        "animation_duration_frames": 18,
        "animation_stage1_opacity": 0.55,
    }

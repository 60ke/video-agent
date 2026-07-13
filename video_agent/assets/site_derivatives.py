from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageFont

from video_agent.io import sha256_file


CANVAS_SIZE = (1080, 1920)
RENDERER_VERSION = "site_callout_renderer_v1"


@dataclass(frozen=True)
class CropTransform:
    left: float
    top: float
    width: float
    height: float

    def map_box(self, box: dict[str, float], source_width: int, source_height: int) -> tuple[int, int, int, int]:
        x0 = box["x"] * source_width
        y0 = box["y"] * source_height
        x1 = (box["x"] + box["w"]) * source_width
        y1 = (box["y"] + box["h"]) * source_height
        scale_x = CANVAS_SIZE[0] / self.width
        scale_y = CANVAS_SIZE[1] / self.height
        return (
            round((x0 - self.left) * scale_x),
            round((y0 - self.top) * scale_y),
            round((x1 - self.left) * scale_x),
            round((y1 - self.top) * scale_y),
        )


def _source_rect(box: dict[str, float], width: int, height: int) -> tuple[float, float, float, float]:
    return (
        box["x"] * width,
        box["y"] * height,
        (box["x"] + box["w"]) * width,
        (box["y"] + box["h"]) * height,
    )


def _union(rects: Iterable[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    values = list(rects)
    if not values:
        raise ValueError("at least one focus rectangle is required")
    return (
        min(rect[0] for rect in values),
        min(rect[1] for rect in values),
        max(rect[2] for rect in values),
        max(rect[3] for rect in values),
    )


def _portrait_crop(
    image: Image.Image,
    focus_boxes: list[dict[str, float]],
    *,
    panel_box: dict[str, float] | None = None,
    padding_scale: float = 0.45,
) -> tuple[Image.Image, CropTransform]:
    rects = [_source_rect(box, image.width, image.height) for box in focus_boxes]
    if panel_box:
        rects.append(_source_rect(panel_box, image.width, image.height))
    left, top, right, bottom = _union(rects)
    focus_width = max(1.0, right - left)
    focus_height = max(1.0, bottom - top)
    pad_x = max(image.width * 0.018, focus_width * padding_scale)
    pad_y = max(image.height * 0.025, focus_height * padding_scale)
    left -= pad_x
    right += pad_x
    top -= pad_y
    bottom += pad_y

    target_ratio = CANVAS_SIZE[0] / CANVAS_SIZE[1]
    crop_width = max(1.0, right - left)
    crop_height = max(1.0, bottom - top)
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    if crop_width / crop_height > target_ratio:
        crop_height = crop_width / target_ratio
    else:
        crop_width = crop_height * target_ratio
    crop_width = min(float(image.width), crop_width)
    crop_height = min(float(image.height), crop_height)
    left = max(0.0, min(image.width - crop_width, center_x - crop_width / 2))
    top = max(0.0, min(image.height - crop_height, center_y - crop_height / 2))
    transform = CropTransform(left=left, top=top, width=crop_width, height=crop_height)
    cropped = image.crop((round(left), round(top), round(left + crop_width), round(top + crop_height)))
    return cropped.resize(CANVAS_SIZE, Image.Resampling.LANCZOS), transform


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        Path(os.environ["VIDEO_AGENT_FONT"]) if os.environ.get("VIDEO_AGENT_FONT") else None,
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    )
    for candidate in candidates:
        if candidate and candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    if shutil.which("fc-match"):
        resolved = subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Sans CJK SC"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).stdout.strip()
        if resolved and Path(resolved).is_file():
            return ImageFont.truetype(resolved, size=size)
    raise FileNotFoundError("no supported Chinese font found for deterministic site callouts")


def _layer_paths(output: Path) -> tuple[Path, Path]:
    layer_dir = output.parent / "layers"
    layer_dir.mkdir(parents=True, exist_ok=True)
    return (
        layer_dir / output.name.replace("关键帧", "无圈底图"),
        layer_dir / output.name.replace("关键帧", "圈选层"),
    )


def generate_feature_entry_keyframe(
    source: Path,
    output: Path,
    target_box: dict[str, float],
    panel_box: dict[str, float] | None,
) -> dict[str, Any]:
    with Image.open(source) as opened:
        original = opened.convert("RGB")
        base, transform = _portrait_crop(original, [target_box], panel_box=panel_box, padding_scale=0.35)
        target = transform.map_box(target_box, original.width, original.height)

    x0, y0, x1, y1 = target
    pad_x = max(26, round((x1 - x0) * 0.35))
    pad_y = max(22, round((y1 - y0) * 0.75))
    ellipse = (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)
    layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.ellipse(ellipse, outline=(238, 45, 45, 255), width=12)
    shifted = (ellipse[0] + 7, ellipse[1] - 5, ellipse[2] + 10, ellipse[3] + 4)
    draw.ellipse(shifted, outline=(255, 78, 62, 235), width=5)
    composed = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")

    output.parent.mkdir(parents=True, exist_ok=True)
    base_path, layer_path = _layer_paths(output)
    base.save(base_path, format="PNG")
    layer.save(layer_path, format="PNG")
    composed.save(output, format="PNG")
    return {
        "callout_base_path": base_path.resolve().as_posix(),
        "callout_base_sha256": sha256_file(base_path),
        "callout_layer_path": layer_path.resolve().as_posix(),
        "callout_layer_sha256": sha256_file(layer_path),
        "callout_layer_method": RENDERER_VERSION,
        "target_output_box": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
    }


def _arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int]) -> None:
    draw.line((*start, *end), fill=(45, 159, 255, 255), width=18)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = max(1.0, (dx * dx + dy * dy) ** 0.5)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = end
    base_x, base_y = end[0] - ux * 46, end[1] - uy * 46
    points = [
        tip,
        (round(base_x + px * 26), round(base_y + py * 26)),
        (round(base_x - px * 26), round(base_y - py * 26)),
    ]
    draw.polygon(points, fill=(45, 159, 255, 255))


def generate_parameter_keyframe(
    source: Path,
    output: Path,
    field_boxes: list[dict[str, float]],
    callout_text: str,
) -> dict[str, Any]:
    if not field_boxes:
        raise ValueError("parameter keyframe requires at least one CDP field box")
    with Image.open(source) as opened:
        original = opened.convert("RGB")
        base, transform = _portrait_crop(original, field_boxes, padding_scale=0.72)
        mapped = [transform.map_box(box, original.width, original.height) for box in field_boxes]

    target_x = round(sum((box[0] + box[2]) / 2 for box in mapped) / len(mapped))
    target_y = round(sum((box[1] + box[3]) / 2 for box in mapped) / len(mapped))
    layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font = _font(72 if len(callout_text) <= 6 else 60)
    text_box = draw.textbbox((0, 0), callout_text, font=font, stroke_width=3)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]

    prefer_top = target_y > CANVAS_SIZE[1] * 0.48
    card_y = 170 if prefer_top else 1450
    card_x = max(52, min(CANVAS_SIZE[0] - text_w - 116, 610 if target_x < CANVAS_SIZE[0] / 2 else 54))
    card = (card_x, card_y, card_x + text_w + 72, card_y + text_h + 54)
    draw.rounded_rectangle(card, radius=28, fill=(255, 222, 61, 238), outline=(20, 28, 42, 255), width=5)
    draw.text(
        (card_x + 36, card_y + 20),
        callout_text,
        font=font,
        fill=(20, 28, 42, 255),
        stroke_width=2,
        stroke_fill=(255, 255, 255, 210),
    )
    arrow_start = (card_x + (card[2] - card_x) // 2, card[3] + 8 if prefer_top else card_y - 8)
    _arrow(draw, arrow_start, (target_x, target_y))

    for x0, y0, x1, y1 in mapped:
        draw.rounded_rectangle((x0 - 10, y0 - 8, x1 + 10, y1 + 8), radius=14, outline=(255, 170, 32, 230), width=5)

    output.parent.mkdir(parents=True, exist_ok=True)
    composed = Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")
    composed.save(output, format="PNG")
    layer_path = output.parent / "layers" / output.name.replace("关键帧", "标注层")
    layer_path.parent.mkdir(parents=True, exist_ok=True)
    layer.save(layer_path, format="PNG")
    return {
        "callout_layer_path": layer_path.resolve().as_posix(),
        "callout_layer_sha256": sha256_file(layer_path),
        "callout_layer_method": RENDERER_VERSION,
        "field_output_boxes": [
            {"x0": x0, "y0": y0, "x1": x1, "y1": y1} for x0, y0, x1, y1 in mapped
        ],
    }

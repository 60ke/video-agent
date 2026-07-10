from __future__ import annotations

import math
from functools import lru_cache
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

EFFECT_NAME = "perspective_push_in"
DEFAULT_DURATION = 1.45
MIN_DURATION = 0.85
_INSTALL_MARKER = "_perspective_push_in_installed"


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def ease_out_cubic(value: float) -> float:
    value = clamp(value)
    return 1.0 - (1.0 - value) ** 3


def _number(params: dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(params.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _rgb(params: dict[str, Any], key: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    value = params.get(key)
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    try:
        return tuple(max(0, min(255, int(channel))) for channel in value)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=16)
def _grid_background_cached(
    width: int,
    height: int,
    spacing: int,
    background: tuple[int, int, int],
    line_color: tuple[int, int, int],
    line_width: int,
) -> Image.Image:
    canvas = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(canvas)
    for x in range(0, width + spacing, spacing):
        draw.line((x, 0, x, height), fill=line_color, width=line_width)
    for y in range(0, height + spacing, spacing):
        draw.line((0, y, width, y), fill=line_color, width=line_width)

    vignette = Image.new("L", (width, height), 0)
    vignette_draw = ImageDraw.Draw(vignette)
    margin_x = max(1, int(width * 0.06))
    margin_y = max(1, int(height * 0.04))
    vignette_draw.ellipse(
        (-margin_x, -margin_y, width + margin_x, height + margin_y),
        fill=210,
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(max(width, height) * 0.16))
    shade = Image.new("RGB", (width, height), (0, 0, 0))
    return Image.composite(canvas, shade, vignette)


def grid_background(size: tuple[int, int], params: dict[str, Any]) -> Image.Image:
    width, height = size
    spacing = int(_number(params, "grid_spacing", 72.0, 32.0, 180.0))
    line_width = int(_number(params, "grid_line_width", 2.0, 1.0, 5.0))
    background = _rgb(params, "background_color", (3, 4, 5))
    line_color = _rgb(params, "grid_color", (38, 42, 46))
    return _grid_background_cached(width, height, spacing, background, line_color, line_width).copy()


def _normalized_crop(base: Image.Image, value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    x = clamp(x)
    y = clamp(y)
    w = clamp(w, 0.01, 1.0)
    h = clamp(h, 0.01, 1.0)
    right = clamp(x + w)
    bottom = clamp(y + h)
    if right <= x or bottom <= y:
        return None
    width, height = base.size
    return (
        int(round(x * width)),
        int(round(y * height)),
        max(int(round(right * width)), int(round(x * width)) + 1),
        max(int(round(bottom * height)), int(round(y * height)) + 1),
    )


def _auto_content_bbox(base: Image.Image, params: dict[str, Any]) -> tuple[int, int, int, int]:
    explicit = _normalized_crop(base, params.get("card_crop"))
    if explicit:
        return explicit

    width, height = base.size
    corner_samples = [
        base.getpixel((0, 0)),
        base.getpixel((width - 1, 0)),
        base.getpixel((0, height - 1)),
        base.getpixel((width - 1, height - 1)),
    ]
    background = tuple(int(sum(pixel[i] for pixel in corner_samples) / len(corner_samples)) for i in range(3))
    diff = ImageChops.difference(base.convert("RGB"), Image.new("RGB", base.size, background))
    threshold = int(_number(params, "content_threshold", 14.0, 2.0, 64.0))
    mask = ImageOps.grayscale(diff).point(lambda value: 255 if value > threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return (0, 0, width, height)

    left, top, right, bottom = bbox
    pad_x = int((right - left) * 0.012)
    pad_y = int((bottom - top) * 0.018)
    left = max(0, left - pad_x)
    top = max(0, top - pad_y)
    right = min(width, right + pad_x)
    bottom = min(height, bottom + pad_y)

    if (right - left) < width * 0.35 or (bottom - top) < height * 0.12:
        return (0, 0, width, height)
    return (left, top, right, bottom)


def _rounded_card(source: Image.Image, params: dict[str, Any]) -> Image.Image:
    radius = int(_number(params, "corner_radius", 28.0, 0.0, 96.0))
    border_width = int(_number(params, "border_width", 3.0, 0.0, 12.0))
    border_color = _rgb(params, "border_color", (222, 238, 244))
    card = source.convert("RGBA")
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=radius, fill=255)
    card.putalpha(mask)
    if border_width > 0:
        ImageDraw.Draw(card, "RGBA").rounded_rectangle(
            (border_width // 2, border_width // 2, card.width - 1 - border_width // 2, card.height - 1 - border_width // 2),
            radius=max(0, radius - border_width // 2),
            outline=border_color + (235,),
            width=border_width,
        )
    return card


def _solve_linear(matrix: list[list[float]], values: list[float]) -> list[float]:
    size = len(values)
    augmented = [list(row) + [float(values[index])] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            raise ValueError("perspective transform is singular")
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) < 1e-12:
                continue
            augmented[row] = [
                augmented[row][item] - factor * augmented[column][item]
                for item in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def _perspective_coefficients(
    destination: list[tuple[float, float]],
    source: list[tuple[float, float]],
) -> tuple[float, float, float, float, float, float, float, float]:
    matrix: list[list[float]] = []
    values: list[float] = []
    for (x, y), (u, v) in zip(destination, source):
        matrix.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y])
        values.append(u)
        matrix.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y])
        values.append(v)
    return tuple(_solve_linear(matrix, values))  # type: ignore[return-value]


def _rotate_points(points: list[tuple[float, float]], angle_degrees: float) -> list[tuple[float, float]]:
    if abs(angle_degrees) < 1e-5:
        return points
    center_x = sum(point[0] for point in points) / len(points)
    center_y = sum(point[1] for point in points) / len(points)
    radians = math.radians(angle_degrees)
    cos_value = math.cos(radians)
    sin_value = math.sin(radians)
    rotated: list[tuple[float, float]] = []
    for x, y in points:
        dx = x - center_x
        dy = y - center_y
        rotated.append((center_x + dx * cos_value - dy * sin_value, center_y + dx * sin_value + dy * cos_value))
    return rotated


def _warp_to_canvas(card: Image.Image, canvas_size: tuple[int, int], destination: list[tuple[float, float]]) -> Image.Image:
    source = [
        (0.0, 0.0),
        (float(card.width - 1), 0.0),
        (float(card.width - 1), float(card.height - 1)),
        (0.0, float(card.height - 1)),
    ]
    coefficients = _perspective_coefficients(destination, source)
    return card.transform(
        canvas_size,
        Image.Transform.PERSPECTIVE,
        coefficients,
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0, 0),
    )


def render_perspective_push_in(base: Image.Image, group_progress: float, params: dict[str, Any]) -> Image.Image:
    width, height = base.size
    settle_at = _number(params, "settle_at", 0.76, 0.35, 1.0)
    progress = ease_out_cubic(clamp(group_progress / settle_at))

    crop = _auto_content_bbox(base.convert("RGB"), params)
    card_source = base.crop(crop).convert("RGB")
    start_width = _number(params, "start_width", 0.72, 0.30, 1.20)
    end_width = _number(params, "end_width", 1.08, 0.45, 1.35)
    card_width = width * (start_width + (end_width - start_width) * progress)
    source_aspect = max(0.20, card_source.width / max(card_source.height, 1))
    card_height = card_width / source_aspect
    max_height = height * _number(params, "max_height", 0.72, 0.30, 0.95)
    if card_height > max_height:
        card_height = max_height
        card_width = card_height * source_aspect

    target_w = max(2, int(round(card_width)))
    target_h = max(2, int(round(card_height)))
    card = _rounded_card(card_source.resize((target_w, target_h), Image.Resampling.LANCZOS), params)

    start_x = _number(params, "start_x", 0.08, -0.30, 0.80)
    end_x = _number(params, "end_x", -0.02, -0.40, 0.80)
    start_y = _number(params, "start_y", 0.22, -0.20, 0.90)
    end_y = _number(params, "end_y", 0.05, -0.30, 0.90)
    left = width * (start_x + (end_x - start_x) * progress)
    top = height * (start_y + (end_y - start_y) * progress)

    start_perspective = _number(params, "start_perspective", 0.14, 0.0, 0.32)
    end_perspective = _number(params, "end_perspective", 0.075, 0.0, 0.28)
    perspective = start_perspective + (end_perspective - start_perspective) * progress
    top_drop = card.height * perspective * 0.55
    bottom_raise = card.height * perspective * 0.45
    destination = [
        (left, top),
        (left + card.width, top + top_drop),
        (left + card.width, top + card.height - bottom_raise),
        (left, top + card.height),
    ]

    start_rotation = _number(params, "start_rotation", 1.8, -12.0, 12.0)
    end_rotation = _number(params, "end_rotation", 0.35, -8.0, 8.0)
    rotation = start_rotation + (end_rotation - start_rotation) * progress
    destination = _rotate_points(destination, rotation)

    layer = _warp_to_canvas(card, base.size, destination)
    opacity = clamp(group_progress / _number(params, "fade_in", 0.12, 0.02, 0.50))
    if opacity < 1.0:
        layer.putalpha(layer.getchannel("A").point(lambda value: int(value * opacity)))

    canvas = grid_background(base.size, params).convert("RGBA")
    alpha = layer.getchannel("A")
    if params.get("shadow", True):
        shadow_offset_x = int(_number(params, "shadow_offset_x", 18.0, -80.0, 120.0))
        shadow_offset_y = int(_number(params, "shadow_offset_y", 24.0, -80.0, 140.0))
        shadow_blur = _number(params, "shadow_blur", 26.0, 0.0, 80.0)
        shadow_alpha = int(_number(params, "shadow_alpha", 125.0, 0.0, 255.0) * opacity)
        shadow_mask = Image.new("L", base.size, 0)
        shadow_mask.paste(alpha, (shadow_offset_x, shadow_offset_y))
        shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(shadow_blur))
        shadow = Image.new("RGBA", base.size, (0, 0, 0, shadow_alpha))
        shadow.putalpha(shadow_mask.point(lambda value: int(value * shadow_alpha / 255)))
        canvas.alpha_composite(shadow)

    glow_alpha = int(_number(params, "glow_alpha", 105.0, 0.0, 255.0) * opacity)
    if glow_alpha > 0:
        glow_blur = _number(params, "glow_blur", 16.0, 0.0, 64.0)
        glow_color = _rgb(params, "glow_color", (205, 238, 248))
        glow_mask = alpha.filter(ImageFilter.GaussianBlur(glow_blur))
        glow = Image.new("RGBA", base.size, glow_color + (glow_alpha,))
        glow.putalpha(glow_mask.point(lambda value: int(value * glow_alpha / 255)))
        canvas.alpha_composite(glow)

    canvas.alpha_composite(layer)
    return canvas.convert("RGB")


def install(registry: Any) -> None:
    if getattr(registry, _INSTALL_MARKER, False):
        return

    registry.EFFECT_NAMES.add(EFFECT_NAME)
    registry.DEFAULT_EFFECT_DURATION[EFFECT_NAME] = DEFAULT_DURATION
    registry.MIN_EFFECT_DURATION[EFFECT_NAME] = MIN_DURATION

    original_render = registry.render_effect_frame
    original_suggested = registry.suggested_effect

    def render_effect_frame(
        base: Image.Image,
        effect: dict[str, Any] | None,
        *,
        group_progress: float,
        group_duration: float,
        aux_assets: dict[str, Image.Image] | None = None,
    ) -> Image.Image:
        if isinstance(effect, dict) and str(effect.get("name") or "") == EFFECT_NAME:
            params = dict(effect.get("params")) if isinstance(effect.get("params"), dict) else {}
            if "settle_at" not in params:
                try:
                    effect_duration = float(effect.get("duration") or DEFAULT_DURATION)
                except (TypeError, ValueError):
                    effect_duration = DEFAULT_DURATION
                params["settle_at"] = clamp(effect_duration / max(group_duration, 0.001), 0.35, 0.90)
            return render_perspective_push_in(base, group_progress, params)
        return original_render(
            base,
            effect,
            group_progress=group_progress,
            group_duration=group_duration,
            aux_assets=aux_assets,
        )

    def suggested_effect(data: Any) -> dict[str, Any] | None:
        step_kind = str(getattr(data, "step_kind", "") or "").lower()
        clip_type = str(getattr(data, "clip_type", "") or "").lower()
        duration = float(getattr(data, "duration", 0.0) or 0.0)
        is_wide_ui = bool(getattr(data, "is_wide_ui", False))
        if clip_type == "image" and duration >= 1.55 and (is_wide_ui or step_kind in {"params", "ui"}):
            return {
                "name": EFFECT_NAME,
                "duration": min(DEFAULT_DURATION, max(MIN_DURATION, duration - 0.55)),
                "params": {
                    "start_width": 0.72,
                    "end_width": 1.08,
                    "start_x": 0.08,
                    "end_x": -0.02,
                    "start_y": 0.22,
                    "end_y": 0.05,
                    "start_perspective": 0.14,
                    "end_perspective": 0.075,
                    "start_rotation": 1.8,
                    "end_rotation": 0.35,
                    "grid_spacing": 72,
                    "corner_radius": 28,
                    "border_width": 3,
                    "shadow": True,
                },
            }
        return original_suggested(data)

    registry.render_effect_frame = render_effect_frame
    registry.suggested_effect = suggested_effect
    setattr(registry, _INSTALL_MARKER, True)

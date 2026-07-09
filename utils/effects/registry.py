from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

EFFECT_NAMES = {
    "drop_bounce",
    "pop_in",
    "zoom_pulse",
    "tile_drop",
    "radial_unfurl",
    "wipe_reveal",
    "scan_overlay",
}
EFFECTS_REQUIRE_AUX = {"scan_overlay"}
DEFAULT_EFFECT_DURATION = {
    "drop_bounce": 0.90,
    "pop_in": 0.70,
    "zoom_pulse": 1.10,
    "tile_drop": 1.10,
    "radial_unfurl": 1.25,
    "wipe_reveal": 0.80,
    "scan_overlay": 1.30,
}
MIN_EFFECT_DURATION = {
    "drop_bounce": 0.70,
    "pop_in": 0.45,
    "zoom_pulse": 0.60,
    "tile_drop": 0.90,
    "radial_unfurl": 1.00,
    "wipe_reveal": 0.55,
    "scan_overlay": 1.00,
}
EFFECT_DURATION_EPSILON = 1e-6


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def smoothstep(value: float) -> float:
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


def ease_out_cubic(value: float) -> float:
    value = clamp(value)
    return 1.0 - (1.0 - value) ** 3


def ease_in_out_cubic(value: float) -> float:
    value = clamp(value)
    if value < 0.5:
        return 4.0 * value * value * value
    return 1.0 - ((-2.0 * value + 2.0) ** 3) / 2.0


def ease_out_back(value: float, s: float = 1.05) -> float:
    value = clamp(value) - 1.0
    return 1.0 + (s + 1.0) * value * value * value + s * value * value


def ease_out_bounce(value: float) -> float:
    value = clamp(value)
    n1 = 7.5625
    d1 = 2.75
    if value < 1.0 / d1:
        return n1 * value * value
    if value < 2.0 / d1:
        value -= 1.5 / d1
        return n1 * value * value + 0.75
    if value < 2.5 / d1:
        value -= 2.25 / d1
        return n1 * value * value + 0.9375
    value -= 2.625 / d1
    return n1 * value * value + 0.984375


def parse_grid(params: dict[str, Any], default: tuple[int, int]) -> tuple[int, int]:
    rows = params.get("rows")
    cols = params.get("cols")
    grid = params.get("grid")
    if isinstance(grid, list) and len(grid) == 2:
        rows = rows if rows is not None else grid[0]
        cols = cols if cols is not None else grid[1]
    try:
        r = int(rows if rows is not None else default[0])
        c = int(cols if cols is not None else default[1])
    except (TypeError, ValueError):
        return default
    return max(1, min(8, r)), max(1, min(8, c))


def normalize_effect_config(raw: Any, *, group_duration: float | None = None) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("effect must be an object")
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    if name not in EFFECT_NAMES:
        raise ValueError(f"effect.name must be one of {sorted(EFFECT_NAMES)}, got: {name!r}")
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    try:
        duration = float(raw.get("duration") or params.get("duration") or DEFAULT_EFFECT_DURATION[name])
    except (TypeError, ValueError):
        duration = DEFAULT_EFFECT_DURATION[name]
    if group_duration is not None and group_duration > 0:
        duration = min(duration, max(0.0, group_duration - 0.55), max(0.0, group_duration * 0.55))
    duration = max(0.0, duration)
    # If the group's safety budget clips the effect to zero, or below the
    # minimum readable effect duration, disable it instead of falling back to
    # the default. Short visual slices should stay as stable stills. Use a
    # small epsilon so exact threshold values are not lost to float rounding.
    if duration <= 0:
        return None
    min_duration = MIN_EFFECT_DURATION[name]
    if duration + EFFECT_DURATION_EPSILON < min_duration:
        return None
    if duration < min_duration:
        duration = min_duration
    effect = {"name": name, "duration": round(duration, 3), "params": dict(params)}
    for key in ("aux_asset_id", "aux_asset_ids", "needs_aux_asset", "aux_asset_kind"):
        if key in raw:
            effect[key] = raw[key]
    if name in EFFECTS_REQUIRE_AUX and "aux_asset_id" not in effect:
        effect["needs_aux_asset"] = True
        effect["aux_asset_kind"] = effect.get("aux_asset_kind") or "highlight_overlay"
    return effect


def effect_requires_aux(name: str) -> bool:
    return name in EFFECTS_REQUIRE_AUX


def effect_aux_asset_ids(effect: dict[str, Any] | None) -> list[str]:
    if not isinstance(effect, dict):
        return []
    values: list[str] = []
    if effect.get("aux_asset_id"):
        values.append(str(effect["aux_asset_id"]))
    if isinstance(effect.get("aux_asset_ids"), list):
        values.extend(str(v) for v in effect["aux_asset_ids"] if str(v).strip())
    return values


def whole_frame_zoom(img: Image.Image, scale: float) -> Image.Image:
    width, height = img.size
    if abs(scale - 1.0) < 1e-4:
        return img
    scaled_w = max(width, int(round(width * scale)))
    scaled_h = max(height, int(round(height * scale)))
    resized = img.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    left = (scaled_w - width) // 2
    top = (scaled_h - height) // 2
    return resized.crop((left, top, left + width, top + height))


def soft_background(source: Image.Image, *, strength: float = 0.35, blur: float = 18.0) -> Image.Image:
    base = source.convert("RGB").filter(ImageFilter.GaussianBlur(blur))
    base = ImageEnhance.Brightness(base).enhance(1.10)
    base = ImageEnhance.Contrast(base).enhance(0.86)
    return Image.blend(Image.new("RGB", source.size, (244, 248, 255)), base, strength)


def paste_transformed(canvas: Image.Image, img: Image.Image, *, scale: float = 1.0, opacity: float = 1.0, offset_x: int = 0, offset_y: int = 0, rotation: float = 0.0, squash_x: float = 1.0, squash_y: float = 1.0) -> None:
    width, height = img.size
    layer = img.convert("RGBA")
    layer_w = max(1, int(round(width * scale * squash_x)))
    layer_h = max(1, int(round(height * scale * squash_y)))
    layer = layer.resize((layer_w, layer_h), Image.Resampling.LANCZOS)
    if abs(rotation) > 0.01:
        layer = layer.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
    if opacity < 1.0:
        layer.putalpha(layer.getchannel("A").point(lambda p: int(p * clamp(opacity))))
    canvas.alpha_composite(layer, ((width - layer.width) // 2 + offset_x, (height - layer.height) // 2 + offset_y))


def _drop_bounce(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    if t >= 0.999:
        return base
    width, height = base.size
    p = ease_out_bounce(t)
    y = int(float(params.get("start_offset_y", -0.72)) * height * (1.0 - p))
    impact = math.exp(-((t - 0.62) / 0.12) ** 2)
    canvas = soft_background(base, strength=0.28, blur=22).convert("RGBA")
    opacity = clamp(t * 1.7)
    if params.get("shadow", True):
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(shadow, "RGBA")
        draw.rounded_rectangle((42, y + 54, width - 42, y + height + 54), radius=24, fill=(0, 0, 0, int(65 * opacity)))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
    paste_transformed(canvas, base, opacity=opacity, offset_y=y, squash_x=1.0 + 0.012 * impact, squash_y=1.0 - 0.030 * impact)
    return canvas.convert("RGB")


def _pop_in(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    if t >= 0.999:
        return base
    start_scale = float(params.get("start_scale", 0.82))
    peak_scale = float(params.get("peak_scale", 1.045))
    peak_at = float(params.get("peak_at", 0.50))
    if t <= peak_at:
        scale = start_scale + (peak_scale - start_scale) * ease_out_cubic(t / max(peak_at, 1e-6))
    else:
        scale = peak_scale + (1.0 - peak_scale) * ease_out_cubic((t - peak_at) / max(1.0 - peak_at, 1e-6))
    canvas = soft_background(base, strength=0.34, blur=18).convert("RGBA")
    paste_transformed(canvas, base, scale=scale, opacity=clamp(t / 0.25))
    return canvas.convert("RGB")


def _zoom_pulse(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    pulse = math.sin(math.pi * clamp(t))
    frame = whole_frame_zoom(base, 1.0 + float(params.get("amount", 0.04)) * pulse)
    return ImageEnhance.Brightness(frame).enhance(1.0 + 0.025 * pulse) if pulse > 0 else frame


def _tile_drop(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    if t >= 0.999:
        return base
    rows, cols = parse_grid(params, (4, 4))
    width, height = base.size
    tile_w = width // cols
    tile_h = height // rows
    canvas = soft_background(base, strength=0.42, blur=16).convert("RGBA")
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * tile_w, r * tile_h
            x1 = width if c == cols - 1 else (c + 1) * tile_w
            y1 = height if r == rows - 1 else (r + 1) * tile_h
            delay = (r + c) / max(1, rows + cols - 2) * float(params.get("stagger", 0.36))
            local = (t - delay) / max(1.0 - delay, 1e-6)
            if local <= 0:
                continue
            tile = base.crop((x0, y0, x1, y1)).convert("RGBA")
            alpha = clamp(local * 1.6)
            if alpha < 1.0:
                tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha)))
            start_y = -tile.height - 60 - ((c * 29) % 80)
            y = int(start_y + (y0 - start_y) * ease_out_back(local, s=float(params.get("bounce", 0.92))))
            canvas.alpha_composite(tile, (x0, y))
    return canvas.convert("RGB")


def _radial_unfurl(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    if t >= 0.999:
        return base
    rows, cols = parse_grid(params, (5, 5))
    width, height = base.size
    tile_w = width // cols
    tile_h = height // rows
    cx, cy = width / 2.0, height / 2.0
    max_dist = max(1.0, math.hypot(cx, cy))
    canvas = soft_background(base, strength=0.48, blur=20).convert("RGBA")
    start_scale = float(params.get("start_scale", 0.30))
    rotation_deg = float(params.get("rotation_deg", 22.0))
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * tile_w, r * tile_h
            x1 = width if c == cols - 1 else (c + 1) * tile_w
            y1 = height if r == rows - 1 else (r + 1) * tile_h
            tile = base.crop((x0, y0, x1, y1)).convert("RGBA")
            tx, ty = x0 + tile.width / 2.0, y0 + tile.height / 2.0
            dx, dy = tx - cx, ty - cy
            dist = math.hypot(dx, dy) / max_dist
            angle = math.atan2(dy, dx)
            delay = 0.04 + dist * float(params.get("stagger", 0.22))
            local = (t - delay) / max(1.0 - delay, 1e-6)
            if local <= 0:
                continue
            p = ease_out_back(local, s=0.82)
            scale = start_scale + (1.0 - start_scale) * clamp(p)
            rot = rotation_deg * (1 if (r + c) % 2 == 0 else -1) * (1.0 - clamp(p))
            sx = int(cx - tile.width / 2 + math.cos(angle + 1.4) * width * 0.055 * (1 + dist))
            sy = int(cy - tile.height / 2 + math.sin(angle + 1.4) * height * 0.055 * (1 + dist))
            x = int(sx + (x0 - sx) * clamp(p))
            y = int(sy + (y0 - sy) * clamp(p))
            tile2 = tile.resize((max(1, int(tile.width * scale)), max(1, int(tile.height * scale))), Image.Resampling.LANCZOS)
            if abs(rot) > 0.01:
                tile2 = tile2.rotate(rot, expand=True, resample=Image.Resampling.BICUBIC)
            alpha = clamp(local * 1.75)
            if alpha < 1.0:
                tile2.putalpha(tile2.getchannel("A").point(lambda v: int(v * alpha)))
            canvas.alpha_composite(tile2, (x + (tile.width - tile2.width) // 2, y + (tile.height - tile2.height) // 2))
    return canvas.convert("RGB")


def _wipe_reveal(base: Image.Image, t: float, params: dict[str, Any]) -> Image.Image:
    if t >= 0.999:
        return base
    width, height = base.size
    direction = str(params.get("direction") or "left_to_right")
    eased = ease_in_out_cubic(t)
    bg = soft_background(base, strength=0.32, blur=20)
    mask = Image.new("L", base.size, 0)
    draw = ImageDraw.Draw(mask)
    if direction == "top_to_bottom":
        pos = int(height * eased)
        draw.rectangle((0, 0, width, pos), fill=255)
        edge = (0, pos, width, pos)
    elif direction == "diagonal":
        pos = int((width + height) * eased)
        draw.polygon([(0, 0), (min(width, pos), 0), (0, min(height, pos))], fill=255)
        edge = (min(width, pos), 0, 0, min(height, pos))
    else:
        pos = int(width * eased)
        draw.rectangle((0, 0, pos, height), fill=255)
        edge = (pos, 0, pos, height)
    feather = int(params.get("feather_px") or max(10, width * 0.018))
    mask = mask.filter(ImageFilter.GaussianBlur(feather))
    frame = Image.composite(base, bg, mask).convert("RGBA")
    if params.get("highlight_edge", True):
        ImageDraw.Draw(frame, "RGBA").line(edge, fill=(90, 220, 255, int(160 * math.sin(math.pi * clamp(t)))), width=4)
    return frame.convert("RGB")


def _procedural_highlight(base: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(base)
    edges = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES))
    edges = edges.point(lambda p: 255 if p > 38 else 0).filter(ImageFilter.GaussianBlur(0.45))
    pale = Image.blend(Image.new("RGB", base.size, (248, 252, 255)), gray.convert("RGB"), 0.18)
    blue = Image.new("RGB", base.size, (10, 98, 220))
    return Image.composite(blue, pale, edges)


def _scan_overlay(base: Image.Image, t: float, params: dict[str, Any], aux: dict[str, Image.Image]) -> Image.Image:
    highlight = aux.get("highlight_overlay") or aux.get("aux") or _procedural_highlight(base)
    if highlight.size != base.size:
        highlight = highlight.resize(base.size, Image.Resampling.LANCZOS)
    width, height = base.size
    center = int(-width * 0.14 + (width * 1.28) * ease_in_out_cubic(t))
    band = int(width * float(params.get("band_width", 0.14)))
    left, right = max(0, center - band), min(width, center + band)
    trail_left = max(0, left - int(width * float(params.get("trail_width", 0.18))))
    mask = Image.new("L", base.size, 0)
    draw = ImageDraw.Draw(mask)
    if trail_left < right:
        draw.rectangle((trail_left, 0, right, height), fill=int(255 * float(params.get("residual_opacity", 0.10))))
    if left < right:
        draw.rectangle((left, 0, right, height), fill=int(255 * float(params.get("overlay_opacity", 0.72))))
    mask = mask.filter(ImageFilter.GaussianBlur(max(8, int(width * 0.015))))
    frame = Image.composite(highlight, base, mask).convert("RGBA")
    if -20 <= center <= width + 20:
        fx = ImageDraw.Draw(frame, "RGBA")
        alpha = int(160 * math.sin(math.pi * clamp(t)))
        fx.rectangle((center - 5, 0, center + 5, height), fill=(80, 205, 255, max(0, int(alpha * 0.22))))
        fx.line((center, 0, center, height), fill=(100, 230, 255, max(0, alpha)), width=2)
    return frame.convert("RGB")


def render_effect_frame(base: Image.Image, effect: dict[str, Any] | None, *, group_progress: float, group_duration: float, aux_assets: dict[str, Image.Image] | None = None) -> Image.Image:
    if not effect:
        return base
    name = str(effect.get("name") or "")
    params = effect.get("params") if isinstance(effect.get("params"), dict) else {}
    duration = float(effect.get("duration") or DEFAULT_EFFECT_DURATION.get(name, 0.8))
    elapsed = clamp(group_progress) * max(group_duration, 0.001)
    if elapsed >= duration:
        return base
    t = clamp(elapsed / max(duration, 0.001))
    if name == "drop_bounce":
        return _drop_bounce(base, t, params)
    if name == "pop_in":
        return _pop_in(base, t, params)
    if name == "zoom_pulse":
        return _zoom_pulse(base, t, params)
    if name == "tile_drop":
        return _tile_drop(base, t, params)
    if name == "radial_unfurl":
        return _radial_unfurl(base, t, params)
    if name == "wipe_reveal":
        return _wipe_reveal(base, t, params)
    if name == "scan_overlay":
        return _scan_overlay(base, t, params, aux_assets or {})
    return base


@dataclass(frozen=True)
class EffectSuggestionInput:
    step_kind: str
    layout: str
    clip_type: str
    duration: float
    is_generated_result: bool = False
    is_wide_ui: bool = False
    visual_intent: str = ""
    material_task: str = ""


def suggested_effect(data: EffectSuggestionInput) -> dict[str, Any] | None:
    if data.duration < 0.85 or data.clip_type != "image":
        return None
    text = " ".join([data.step_kind, data.layout, data.visual_intent, data.material_task]).lower()
    if any(token in text for token in ("解析", "结构", "高亮", "analysis", "blueprint", "scan")) and data.duration >= 1.6:
        return {"name": "scan_overlay", "duration": min(1.3, data.duration - 0.55), "needs_aux_asset": True, "aux_asset_kind": "highlight_overlay", "params": {"band_width": 0.14, "overlay_opacity": 0.72, "residual_opacity": 0.10}}
    if data.step_kind in {"home", "entry"}:
        return {"name": "drop_bounce", "duration": min(0.9, data.duration - 0.55), "params": {"shadow": True}}
    if data.step_kind in {"params", "ui"} or data.is_wide_ui:
        return {"name": "wipe_reveal", "duration": min(0.8, data.duration - 0.55), "params": {"direction": "left_to_right", "highlight_edge": True}}
    if data.step_kind == "result" or data.is_generated_result:
        if data.duration >= 1.8:
            return {"name": "radial_unfurl", "duration": min(1.25, data.duration - 0.65), "params": {"rows": 5, "cols": 5}}
        return {"name": "tile_drop", "duration": min(1.1, data.duration - 0.60), "params": {"rows": 4, "cols": 4}}
    if data.duration >= 1.2:
        return {"name": "pop_in", "duration": min(0.7, data.duration - 0.55), "params": {"start_scale": 0.82, "peak_scale": 1.04}}
    return None

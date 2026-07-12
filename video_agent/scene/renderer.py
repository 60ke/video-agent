from __future__ import annotations

import bisect
import math
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageSequence

from video_agent.compiler.subtitles import fullwidth_units
from video_agent.contracts import CompiledCue, RenderPlan, RenderShot, SubtitleCue
from video_agent.platform import PixelRect, get_profile
from video_agent.scene.easing import ease_out_cubic, smoothstep


FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
    Path("C:/Windows/Fonts/simhei.ttf"),
)


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    raise FileNotFoundError("no supported Chinese font found")


def _fit(image: Image.Image, box: PixelRect, *, fill: bool = False) -> tuple[Image.Image, tuple[int, int]]:
    source = image.convert("RGBA")
    if fill:
        scale = max(box.w / source.width, box.h / source.height)
    else:
        scale = min(box.w / source.width, box.h / source.height)
    size = (max(1, int(round(source.width * scale))), max(1, int(round(source.height * scale))))
    resized = source.resize(size, Image.Resampling.LANCZOS)
    if fill:
        left = max(0, (resized.width - box.w) // 2)
        top = max(0, (resized.height - box.h) // 2)
        resized = resized.crop((left, top, left + box.w, top + box.h))
        return resized, (box.x, box.y)
    return resized, (box.x + (box.w - resized.width) // 2, box.y + (box.h - resized.height) // 2)


def _grid_background(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), (7, 10, 14))
    draw = ImageDraw.Draw(image)
    spacing = 64
    for x in range(0, width + 1, spacing):
        strong = (x // spacing) % 4 == 0
        color = (34, 40, 48) if strong else (22, 27, 33)
        draw.line((x, 0, x, height), fill=color, width=2 if strong else 1)
    for y in range(0, height + 1, spacing):
        strong = (y // spacing) % 4 == 0
        color = (34, 40, 48) if strong else (22, 27, 33)
        draw.line((0, y, width, y), fill=color, width=2 if strong else 1)
    return image


def _rounded_card(image: Image.Image, radius: int = 28) -> Image.Image:
    source = image.convert("RGBA")
    mask = Image.new("L", source.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, source.width - 1, source.height - 1), radius=radius, fill=255)
    source.putalpha(ImageChops.multiply(source.getchannel("A"), mask))
    return source


def _crop_around_anchor(
    image: Image.Image,
    rect: dict[str, float],
    template: str,
    panel_rect: dict[str, float] | None = None,
) -> tuple[Image.Image, dict[str, float]]:
    x, y, w, h = rect["x"], rect["y"], rect["w"], rect["h"]
    if template == "ui_feature_entry":
        context = panel_rect or rect
        context_center_x = context["x"] + context["w"] / 2
        context_center_y = context["y"] + context["h"] / 2
        crop_w = max(0.34, min(0.62, context["w"] * 2.4))
        crop_h = max(0.62, min(0.86, context["h"] * 1.45))
        center_x = context_center_x
        center_y = context_center_y
    elif w >= 0.6:
        crop_w = 1.0
        crop_h = 0.70
        center_x = 0.5
        center_y = min(0.65, max(crop_h / 2, y + h / 2 - 0.10))
    else:
        crop_w = 0.94
        crop_h = 0.64
        center_x = x + w / 2
        center_y = y + h / 2
    left = max(0.0, min(1.0 - crop_w, center_x - crop_w / 2))
    top = max(0.0, min(1.0 - crop_h, center_y - crop_h / 2))
    px = (
        int(round(left * image.width)),
        int(round(top * image.height)),
        int(round((left + crop_w) * image.width)),
        int(round((top + crop_h) * image.height)),
    )
    cropped = image.crop(px)
    local = {
        "x": (x - left) / crop_w,
        "y": (y - top) / crop_h,
        "w": w / crop_w,
        "h": h / crop_h,
    }
    return cropped, local


def _expand_focus(rect: dict[str, float], template: str) -> dict[str, float]:
    center_x = rect["x"] + rect["w"] / 2
    center_y = rect["y"] + rect["h"] / 2
    if template == "ui_params_focus" and rect["w"] < 0.7:
        width = max(0.82, min(0.94, rect["w"] * 2.0 + 0.28))
        height = max(0.13, min(0.24, rect["h"] * 2.5 + 0.08))
    elif template == "ui_params_focus":
        width = min(0.96, rect["w"])
        height = max(0.16, min(0.30, rect["h"] * 1.35))
    else:
        width = max(0.20, min(0.40, rect["w"] * 2.0 + 0.14))
        height = max(0.08, min(0.18, rect["h"] * 1.8 + 0.04))
    x = max(0.0, min(1.0 - width, center_x - width / 2))
    if template == "ui_feature_entry":
        x = max(0.0, min(1.0 - width, x + 0.07))
    y = max(0.0, min(1.0 - height, center_y - height / 2))
    return {"x": x, "y": y, "w": width, "h": height}


def _focus_overlay(card: Image.Image, rect: dict[str, float], progress: float, template: str) -> Image.Image:
    source = card.convert("RGBA")
    focus = _expand_focus(rect, template)
    box = (
        int(round(focus["x"] * source.width)),
        int(round(focus["y"] * source.height)),
        int(round((focus["x"] + focus["w"]) * source.width)),
        int(round((focus["y"] + focus["h"]) * source.height)),
    )
    dimmed = ImageEnhance.Brightness(source.convert("RGB")).enhance(1.0 - 0.42 * smoothstep(progress)).convert("RGBA")
    cutout = Image.new("L", source.size, 0)
    ImageDraw.Draw(cutout).rounded_rectangle(box, radius=18, fill=255)
    source = Image.composite(source, dimmed, cutout)
    overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    alpha = int(round(255 * smoothstep(progress)))
    draw.rounded_rectangle(box, radius=18, outline=(255, 74, 86, alpha), width=7)
    outer = (box[0] - 8, box[1] - 8, box[2] + 8, box[3] + 8)
    draw.rounded_rectangle(outer, radius=22, outline=(255, 190, 80, int(alpha * 0.65)), width=3)
    return Image.alpha_composite(source, overlay)


def _paste_shadow(canvas: Image.Image, card: Image.Image, position: tuple[int, int]) -> None:
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    mask = card.getchannel("A") if card.mode == "RGBA" else Image.new("L", card.size, 255)
    blurred = mask.filter(ImageFilter.GaussianBlur(24))
    layer = Image.new("RGBA", card.size, (0, 0, 0, 150))
    layer.putalpha(blurred)
    shadow.alpha_composite(layer, (position[0] + 8, position[1] + 18))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(card, position)


def _perspective_card(card: Image.Image, width: int, height: int, progress: float) -> Image.Image:
    final_width = width * 0.78
    final_height = min(1240, final_width * card.height / max(card.width, 1))
    start_width = final_width * 0.78
    start_height = final_height * 0.78
    eased = ease_out_cubic(progress)
    current_width = start_width + (final_width - start_width) * eased
    current_height = start_height + (final_height - start_height) * eased
    center_x = width * (0.49 + 0.01 * eased)
    center_y = height * 0.48
    skew = (1.0 - eased) * 70
    corner_offset = 20 * (1.0 - eased)
    left = center_x - current_width / 2
    right = center_x + current_width / 2
    top = center_y - current_height / 2
    bottom = center_y + current_height / 2
    destination = np.float32(
        [
            [left + corner_offset, top + skew],
            [right - corner_offset * 0.6, top],
            [right, bottom - corner_offset * 0.4],
            [left - corner_offset * 0.7, bottom + skew * 0.35],
        ]
    )
    source = np.float32([[0, 0], [card.width - 1, 0], [card.width - 1, card.height - 1], [0, card.height - 1]])
    matrix = cv2.getPerspectiveTransform(source, destination)
    rgba = np.array(card.convert("RGBA"))
    warped = cv2.warpPerspective(rgba, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return Image.fromarray(warped, "RGBA")


def _flat_perspective_endpoint(card: Image.Image, width: int, height: int) -> tuple[Image.Image, tuple[int, int]]:
    final_width = int(round(width * 0.78))
    final_height = min(1240, int(round(final_width * card.height / max(card.width, 1))))
    resized = card.resize((final_width, final_height), Image.Resampling.LANCZOS)
    return resized, ((width - final_width) // 2, int(round(height * 0.48 - final_height / 2)))


class FrameRenderer:
    def __init__(self, plan: RenderPlan) -> None:
        self.plan = plan
        self.profile = get_profile(plan.platform_profile)
        if self.profile.canvas.w != plan.width or self.profile.canvas.h != plan.height:
            raise ValueError("platform profile dimensions differ from render plan")
        self.assets = {asset.asset_id: asset for asset in plan.assets}
        self.images = {
            asset.asset_id: Image.open(asset.path).convert("RGBA")
            for asset in plan.assets
            if asset.media_type == "image"
        }
        self.gif_frames: dict[str, list[Image.Image]] = {}
        self.video_captures: dict[str, cv2.VideoCapture] = {}
        self.video_state: dict[str, tuple[int, Image.Image]] = {}
        for asset in plan.assets:
            if asset.media_type != "video":
                continue
            if Path(asset.path).suffix.lower() == ".gif":
                with Image.open(asset.path) as animation:
                    self.gif_frames[asset.asset_id] = [frame.convert("RGBA") for frame in ImageSequence.Iterator(animation)]
            else:
                capture = cv2.VideoCapture(asset.path)
                if not capture.isOpened():
                    raise ValueError(f"unable to open render video asset: {asset.path}")
                self.video_captures[asset.asset_id] = capture
        self.card_cache: dict[tuple[str, str], Image.Image] = {}
        self.shot_starts = [shot.start_frame for shot in plan.shots]
        self.subtitle_starts = [cue.start_frame for cue in plan.subtitles]
        self.background = _grid_background(plan.width, plan.height).convert("RGBA")

    def close(self) -> None:
        for image in self.images.values():
            image.close()
        for frames in self.gif_frames.values():
            for image in frames:
                image.close()
        for capture in self.video_captures.values():
            capture.release()

    def _motion_frame(self, asset_id: str, shot: RenderShot, frame: int) -> Image.Image:
        asset = self.assets[asset_id]
        source_fps = asset.fps or self.plan.fps
        frame_count = asset.frame_count or 1
        local_frame = max(0, frame - shot.start_frame)
        source_index = int(math.floor(local_frame * source_fps / self.plan.fps)) % frame_count
        if asset_id in self.gif_frames:
            frames = self.gif_frames[asset_id]
            return frames[source_index % len(frames)].copy()
        cached = self.video_state.get(asset_id)
        if cached and cached[0] == source_index:
            return cached[1].copy()
        capture = self.video_captures[asset_id]
        if not cached or source_index != cached[0] + 1:
            capture.set(cv2.CAP_PROP_POS_FRAMES, source_index)
        ok, bgr = capture.read()
        if not ok:
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, bgr = capture.read()
        if not ok:
            raise ValueError(f"unable to decode frame {source_index} from {asset.path}")
        rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
        image = Image.fromarray(rgba, "RGBA")
        self.video_state[asset_id] = (source_index, image)
        return image.copy()

    def _source_for_shot(self, shot: RenderShot, frame: int) -> Image.Image:
        asset_id = shot.asset_ids[0]
        asset = self.assets[asset_id]
        if asset.media_type == "video":
            return self._motion_frame(asset_id, shot, frame)
        return self.images[asset_id]

    def _active_shot(self, frame: int) -> RenderShot:
        index = max(0, bisect.bisect_right(self.shot_starts, frame) - 1)
        return self.plan.shots[min(index, len(self.plan.shots) - 1)]

    def _active_subtitle(self, frame: int) -> SubtitleCue | None:
        index = bisect.bisect_right(self.subtitle_starts, frame) - 1
        if index < 0:
            return None
        cue = self.plan.subtitles[index]
        return cue if cue.start_frame <= frame < cue.end_frame else None

    @staticmethod
    def _active_focus(shot: RenderShot, frame: int) -> tuple[CompiledCue | None, float]:
        candidates = [cue for cue in shot.cues if cue.asset_anchor_id and frame >= cue.hit_frame - cue.anticipation_frames]
        if not candidates:
            return None, 0.0
        cue = max(candidates, key=lambda item: item.hit_frame)
        duration = max(1, cue.anticipation_frames + cue.settle_frames)
        progress = (frame - (cue.hit_frame - cue.anticipation_frames)) / duration
        return cue, max(0.0, min(1.0, progress))

    def _card_for_shot(self, shot: RenderShot, frame: int) -> Image.Image:
        asset_id = shot.asset_ids[0]
        image = self._source_for_shot(shot, frame)
        asset = self.assets[asset_id]
        focus_cue, focus_progress = self._active_focus(shot, frame)
        crop_cue = focus_cue or next((cue for cue in shot.cues if cue.asset_anchor_id), None)
        local_focus: dict[str, float] | None = None
        source = image
        if crop_cue and crop_cue.asset_anchor_id in asset.anchors and shot.template in {"ui_params_focus", "ui_feature_entry"}:
            panel = asset.anchor_panels.get(crop_cue.asset_anchor_id)
            source, local_focus = _crop_around_anchor(image, asset.anchors[crop_cue.asset_anchor_id], shot.template, panel)
        stage = self.profile.content_safe
        max_stage = PixelRect(stage.x, 290, stage.w, 1250)
        cache_key = (asset_id, f"{shot.template}:{crop_cue.asset_anchor_id if crop_cue else 'none'}")
        cacheable = asset.media_type == "image"
        if cacheable and cache_key not in self.card_cache:
            card, _ = _fit(source, PixelRect(0, 0, max_stage.w, max_stage.h))
            self.card_cache[cache_key] = _rounded_card(card, radius=26)
        if cacheable:
            card = self.card_cache[cache_key].copy()
        else:
            fitted, _ = _fit(source, PixelRect(0, 0, max_stage.w, max_stage.h))
            card = _rounded_card(fitted, radius=26)
        if local_focus and focus_cue:
            card = _focus_overlay(card, local_focus, focus_progress, shot.template)
        return card

    def _render_shot(self, shot: RenderShot, frame: int) -> Image.Image:
        canvas = self.background.copy()
        duration = max(1, shot.end_frame - shot.start_frame)
        progress = (frame - shot.start_frame) / duration
        card = self._card_for_shot(shot, frame)
        if shot.effect == "perspective_push_in":
            entrance_ratio = 0.18
            if progress < entrance_ratio:
                entrance_progress = min(1.0, progress / entrance_ratio)
                canvas = Image.alpha_composite(canvas, _perspective_card(card, self.plan.width, self.plan.height, entrance_progress))
            else:
                settled, settled_position = _flat_perspective_endpoint(card, self.plan.width, self.plan.height)
                _paste_shadow(canvas, settled, settled_position)
            return canvas
        position = ((self.plan.width - card.width) // 2, 290 + (1250 - card.height) // 2)
        alpha = 1.0
        scale = 1.0
        if shot.effect in {"fade_in", "crossfade"}:
            alpha = min(1.0, progress / 0.12)
        elif shot.effect == "fade_out":
            alpha = min(1.0, (1.0 - progress) / 0.12)
        elif shot.effect == "scale_in":
            scale = 0.94 + 0.06 * ease_out_cubic(min(1.0, progress / 0.22))
        elif shot.effect == "scale_out":
            scale = 1.06 - 0.06 * ease_out_cubic(min(1.0, progress / 0.22))
        elif shot.effect == "page_slide":
            position = (int(position[0] + (1.0 - ease_out_cubic(min(1.0, progress / 0.2))) * self.plan.width), position[1])
        if not math.isclose(scale, 1.0):
            resized = card.resize((int(card.width * scale), int(card.height * scale)), Image.Resampling.LANCZOS)
            position = ((self.plan.width - resized.width) // 2, position[1] + (card.height - resized.height) // 2)
            card = resized
        if alpha < 1.0:
            card = card.copy()
            card.putalpha(card.getchannel("A").point(lambda value: int(value * alpha)))
        _paste_shadow(canvas, card, position)
        return canvas

    def _draw_subtitle(self, canvas: Image.Image, cue: SubtitleCue) -> None:
        slot = self.profile.subtitle_top if cue.slot == "subtitle_top" else self.profile.subtitle_lower
        if fullwidth_units(cue.text) > 10.0:
            raise ValueError(f"subtitle is too long: {cue.text}")
        size = int(self.plan.style.get("subtitle_font_size", 64))
        minimum = int(self.plan.style.get("subtitle_font_min", 58))
        stroke = int(self.plan.style.get("subtitle_stroke", 4))
        draw = ImageDraw.Draw(canvas)
        font = _font(size)
        while size > minimum and draw.textbbox((0, 0), cue.text, font=font, stroke_width=stroke)[2] > slot.w:
            size -= 2
            font = _font(size)
        bbox = draw.textbbox((0, 0), cue.text, font=font, stroke_width=stroke)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = slot.x + (slot.w - text_width) // 2
        y = slot.y + (slot.h - text_height) // 2 - bbox[1]
        draw.text((x, y), cue.text, font=font, fill=(250, 250, 250), stroke_width=stroke, stroke_fill=(8, 10, 14))
        if cue.emphasize and cue.emphasize in cue.text:
            prefix, _, emphasis_suffix = cue.text.partition(cue.emphasize)
            prefix_width = draw.textlength(prefix, font=font)
            emphasize_width = draw.textlength(cue.emphasize, font=font)
            draw.text((x + int(prefix_width), y), cue.emphasize, font=font, fill=(255, 212, 74), stroke_width=stroke, stroke_fill=(8, 10, 14))
            if emphasis_suffix:
                suffix_x = x + int(prefix_width + emphasize_width)
                draw.text((suffix_x, y), emphasis_suffix, font=font, fill=(250, 250, 250), stroke_width=stroke, stroke_fill=(8, 10, 14))

    def render(self, frame: int) -> Image.Image:
        shot = self._active_shot(frame)
        canvas = self._render_shot(shot, frame)
        subtitle = self._active_subtitle(frame)
        if subtitle:
            self._draw_subtitle(canvas, subtitle)
        return canvas.convert("RGB")

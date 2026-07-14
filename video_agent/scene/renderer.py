from __future__ import annotations

import bisect
import math
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import cv2
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageSequence

from video_agent.compiler.subtitles import fullwidth_units
from video_agent.contracts import RenderPlan, RenderShot, SubtitleCue
from video_agent.platform import PixelRect, get_profile
from video_agent.scene.easing import ease_out_cubic


FONT_CANDIDATES = (
    Path(os.environ["VIDEO_AGENT_FONT"]) if os.environ.get("VIDEO_AGENT_FONT") else None,
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
)


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        if candidate and candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    if shutil.which("fc-match"):
        resolved = subprocess.run(
            ["fc-match", "-f", "%{file}", "Noto Sans CJK SC"], capture_output=True, text=True, encoding="utf-8", errors="replace"
        ).stdout.strip()
        if resolved and Path(resolved).is_file():
            return ImageFont.truetype(resolved, size=size)
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


def _paste_shadow(canvas: Image.Image, card: Image.Image, position: tuple[int, int]) -> None:
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    mask = card.getchannel("A") if card.mode == "RGBA" else Image.new("L", card.size, 255)
    blurred = mask.filter(ImageFilter.GaussianBlur(24))
    layer = Image.new("RGBA", card.size, (0, 0, 0, 150))
    layer.putalpha(blurred)
    shadow.alpha_composite(layer, (position[0] + 8, position[1] + 18))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(card, position)


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
        self.base_shots = sorted((shot for shot in plan.shots if shot.track == "base"), key=lambda item: item.start_frame)
        self.overlay_shots = sorted(
            (shot for shot in plan.shots if shot.track == "overlay"),
            key=lambda item: (int((item.overlay_layout or {}).get("z_index", 10)), item.start_frame),
        )
        if not self.base_shots:
            raise ValueError("render plan needs at least one base-track shot")
        self.shot_starts = [shot.start_frame for shot in self.base_shots]
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

    def _source_for_asset(self, shot: RenderShot, asset_id: str, frame: int) -> Image.Image:
        asset = self.assets[asset_id]
        if asset.media_type == "video":
            return self._motion_frame(asset_id, shot, frame)
        return self.images[asset_id]

    def _active_shot(self, frame: int) -> RenderShot:
        index = max(0, bisect.bisect_right(self.shot_starts, frame) - 1)
        return self.base_shots[min(index, len(self.base_shots) - 1)]

    def _active_subtitle(self, frame: int) -> SubtitleCue | None:
        index = bisect.bisect_right(self.subtitle_starts, frame) - 1
        if index < 0:
            return None
        cue = self.plan.subtitles[index]
        return cue if cue.start_frame <= frame < cue.end_frame else None

    def _card_from_image(self, shot: RenderShot, image: Image.Image, *, cache_key: tuple[str, str] | None = None) -> Image.Image:
        stage = self.profile.content_safe
        max_stage = (
            PixelRect(self.profile.critical_safe.x, 270, self.profile.critical_safe.w, 1260)
            if shot.template == "ui_params_focus"
            else PixelRect(stage.x, 290, stage.w, 1250)
        )
        if cache_key is not None and cache_key not in self.card_cache:
            card, _ = _fit(image, PixelRect(0, 0, max_stage.w, max_stage.h))
            self.card_cache[cache_key] = _rounded_card(card, radius=26)
        if cache_key is not None:
            card = self.card_cache[cache_key].copy()
        else:
            fitted, _ = _fit(image, PixelRect(0, 0, max_stage.w, max_stage.h))
            card = _rounded_card(fitted, radius=26)
        return card

    def _card_for_asset(self, shot: RenderShot, frame: int, asset_id: str) -> Image.Image:
        image = self._source_for_asset(shot, asset_id, frame)
        asset = self.assets[asset_id]
        cache_key = (asset_id, shot.template) if asset.media_type == "image" else None
        return self._card_from_image(shot, image, cache_key=cache_key)

    def _parameter_sequence_image(self, shot: RenderShot, frame: int) -> Image.Image:
        sequence = shot.parameter_sequence
        if sequence is None:
            raise ValueError("parameter sequence was requested for a shot without sequence metadata")
        base = self.images[sequence.base_asset_id]
        if frame < sequence.start_frame:
            return base
        if frame < sequence.stage_frame:
            progress = (frame - sequence.start_frame) / max(1, sequence.stage_frame - sequence.start_frame)
            return Image.blend(base, self.images[sequence.stage_asset_id], ease_out_cubic(progress))
        if frame < sequence.hit_frame:
            progress = (frame - sequence.stage_frame) / max(1, sequence.hit_frame - sequence.stage_frame)
            return Image.blend(self.images[sequence.stage_asset_id], self.images[sequence.final_asset_id], ease_out_cubic(progress))
        return self.images[sequence.final_asset_id]

    def _comparison_card(self, shot: RenderShot, frame: int) -> Image.Image:
        reference_id = shot.asset_bindings.get("reference")
        result_id = shot.asset_bindings.get("result")
        if not reference_id or not result_id:
            raise ValueError("reference_to_result requires reference and result asset bindings")
        stage = Image.new("RGBA", (self.profile.content_safe.w, 1250), (0, 0, 0, 0))
        label_font = _font(30)
        for index, (label, asset_id) in enumerate((("实景参考", reference_id), ("生成效果", result_id))):
            card = self._card_for_asset(shot, frame, asset_id)
            fitted, position = _fit(card, PixelRect(32, 60 + index * 600, stage.width - 64, 500))
            stage.alpha_composite(fitted, position)
            label_box = (position[0] + 14, position[1] + 14)
            draw = ImageDraw.Draw(stage)
            draw.rounded_rectangle((label_box[0], label_box[1], label_box[0] + 154, label_box[1] + 52), radius=16, fill=(12, 18, 26, 220))
            draw.text((label_box[0] + 15, label_box[1] + 8), label, font=label_font, fill=(238, 244, 255))
        return stage

    def _card_for_shot(self, shot: RenderShot, frame: int) -> Image.Image:
        if shot.template == "reference_to_result":
            return self._comparison_card(shot, frame)
        if shot.parameter_sequence:
            return self._card_from_image(shot, self._parameter_sequence_image(shot, frame))
        asset_id = shot.asset_bindings.get("primary") or next(iter(shot.asset_bindings.values()))
        return self._card_for_asset(shot, frame, asset_id)

    def _paint_shot(
        self,
        canvas: Image.Image,
        shot: RenderShot,
        frame: int,
        *,
        alpha_multiplier: float = 1.0,
        x_offset: int = 0,
    ) -> None:
        duration = max(1, shot.end_frame - shot.start_frame)
        progress = max(0.0, min(1.0, (frame - shot.start_frame) / duration))
        card = self._card_for_shot(shot, frame)
        overlay_layout = shot.overlay_layout if shot.track == "overlay" else None
        if overlay_layout:
            stage = self.profile.content_safe
            box = PixelRect(
                stage.x + round(float(overlay_layout["x"]) * stage.w),
                stage.y + round(float(overlay_layout["y"]) * stage.h),
                round(float(overlay_layout["w"]) * stage.w),
                round(float(overlay_layout["h"]) * stage.h),
            )
            card, position = _fit(card, box, fill=overlay_layout.get("fit") == "cover")
            position = (position[0] + x_offset, position[1])
        else:
            stage_y = 270 if shot.template == "ui_params_focus" else 290
            stage_h = 1260 if shot.template == "ui_params_focus" else 1250
            position = ((self.plan.width - card.width) // 2 + x_offset, stage_y + (stage_h - card.height) // 2)
        alpha = alpha_multiplier * (float(overlay_layout.get("opacity", 1.0)) if overlay_layout else 1.0)
        scale = 1.0
        if shot.motion == "fade_in":
            alpha *= min(1.0, progress / 0.12)
        elif shot.motion == "fade_out":
            alpha *= max(0.0, min(1.0, (1.0 - progress) / 0.12))
        elif shot.motion == "scale_in":
            if shot.template == "ui_feature_entry":
                scale = 0.82 + 0.20 * ease_out_cubic(min(1.0, progress / 0.75))
            elif shot.template == "ui_params_focus":
                scale = 0.90 + 0.10 * ease_out_cubic(min(1.0, progress / 0.50))
            else:
                scale = 0.94 + 0.06 * ease_out_cubic(min(1.0, progress / 0.22))
        elif shot.motion == "scale_out":
            scale = 1.06 - 0.06 * ease_out_cubic(min(1.0, progress / 0.22))
        if not math.isclose(scale, 1.0):
            center = (position[0] + card.width / 2, position[1] + card.height / 2)
            resized = card.resize((int(card.width * scale), int(card.height * scale)), Image.Resampling.LANCZOS)
            position = (round(center[0] - resized.width / 2), round(center[1] - resized.height / 2))
            card = resized
        if alpha < 1.0:
            card = card.copy()
            card.putalpha(card.getchannel("A").point(lambda value: int(value * alpha)))
        _paste_shadow(canvas, card, position)

    def _render_base(self, frame: int) -> Image.Image:
        canvas = self.background.copy()
        current = self._active_shot(frame)
        current_index = self.base_shots.index(current)
        transition = current.transition_in
        duration = int(transition.get("duration_frames", 0))
        kind = str(transition.get("kind", "cut"))
        if current_index and duration and frame < current.start_frame + duration:
            previous = self.base_shots[current_index - 1]
            progress = max(0.0, min(1.0, (frame - current.start_frame) / duration))
            if kind == "crossfade":
                self._paint_shot(canvas, previous, min(frame, previous.end_frame - 1), alpha_multiplier=1.0 - progress)
                self._paint_shot(canvas, current, frame, alpha_multiplier=progress)
                return canvas
            if kind == "slide_left":
                self._paint_shot(canvas, previous, min(frame, previous.end_frame - 1), x_offset=-round(self.plan.width * progress))
                self._paint_shot(canvas, current, frame, x_offset=round(self.plan.width * (1.0 - progress)))
                return canvas
            if kind == "slide_right":
                self._paint_shot(canvas, previous, min(frame, previous.end_frame - 1), x_offset=round(self.plan.width * progress))
                self._paint_shot(canvas, current, frame, x_offset=-round(self.plan.width * (1.0 - progress)))
                return canvas
        self._paint_shot(canvas, current, frame)
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
        canvas = self._render_base(frame)
        for shot in self.overlay_shots:
            if shot.start_frame <= frame < shot.end_frame:
                self._paint_shot(canvas, shot, frame)
        subtitle = self._active_subtitle(frame)
        if subtitle:
            self._draw_subtitle(canvas, subtitle)
        return canvas.convert("RGB")

"""Compile a V4 resolved timeline into a portable Jianying EditBlueprint."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .contracts import (
    BlueprintAudioClip,
    BlueprintCanvas,
    BlueprintKeyframe,
    BlueprintSubtitleCue,
    BlueprintVisualClip,
    JianyingEditBlueprint,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_")
    return cleaned or "clip"


def _grid_background(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height), (6, 10, 14))
    draw = ImageDraw.Draw(image)
    for x in range(0, width, 64):
        draw.line((x, 0, x, height), fill=(18, 29, 37), width=1)
    for y in range(0, height, 64):
        draw.line((0, y, width, y), fill=(18, 29, 37), width=1)
    return image


def _compose_frame(
    source: Path,
    destination: Path,
    *,
    canvas_width: int,
    canvas_height: int,
    layout: dict[str, Any],
) -> None:
    frame = _grid_background(canvas_width, canvas_height)
    with Image.open(source) as raw:
        image = raw.convert("RGBA")
        target_width = int(layout["width"])
        target_height = int(layout["height"])
        fit = layout["fit"]
        scale = (
            max(target_width / image.width, target_height / image.height)
            if fit == "cover"
            else min(target_width / image.width, target_height / image.height)
        )
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        if fit == "cover":
            left = max(0, (resized.width - target_width) // 2)
            top = max(0, (resized.height - target_height) // 2)
            resized = resized.crop((left, top, left + target_width, top + target_height))
        x = int(layout["x"]) + (target_width - resized.width) // 2
        y = int(layout["y"]) + (target_height - resized.height) // 2
        frame.paste(resized, (x, y), resized)
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame.save(destination, format="PNG")


def _effect_keyframes(
    effect: dict[str, Any],
    *,
    clip_start: int,
    clip_end: int,
) -> list[BlueprintKeyframe]:
    duration = clip_end - clip_start
    if duration <= 1:
        return []
    reveal = max(1, min(int(effect.get("parameters", {}).get("reveal_frames", 6)), duration - 1))
    effect_id = effect["effect_id"]
    direction = effect.get("direction", "none")

    if effect_id == "fade_in":
        return [
            BlueprintKeyframe(property="alpha", frame_offset=0, value=0.0),
            BlueprintKeyframe(property="alpha", frame_offset=reveal, value=1.0),
        ]
    if effect_id == "detail_push_in":
        return [
            BlueprintKeyframe(property="scale", frame_offset=0, value=1.0),
            BlueprintKeyframe(property="scale", frame_offset=reveal, value=1.06),
        ]
    if effect_id == "full_bleed_to_safe_card":
        return [
            BlueprintKeyframe(property="scale", frame_offset=0, value=1.08),
            BlueprintKeyframe(property="scale", frame_offset=reveal, value=1.0),
        ]
    if effect_id == "card_stack":
        offset = -0.16 if direction == "left" else 0.16
        return [
            BlueprintKeyframe(property="scale", frame_offset=0, value=0.9),
            BlueprintKeyframe(property="position_x", frame_offset=0, value=offset),
            BlueprintKeyframe(property="scale", frame_offset=reveal, value=1.0),
            BlueprintKeyframe(property="position_x", frame_offset=reveal, value=0.0),
        ]
    if effect_id == "before_after":
        offset = -0.08 if direction == "left" else 0.08
        return [
            BlueprintKeyframe(property="alpha", frame_offset=0, value=0.0),
            BlueprintKeyframe(property="position_x", frame_offset=0, value=offset),
            BlueprintKeyframe(property="alpha", frame_offset=reveal, value=1.0),
            BlueprintKeyframe(property="position_x", frame_offset=reveal, value=0.0),
        ]
    return []


def _copy_audio(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or _sha256(destination) != _sha256(source):
        shutil.copy2(source, destination)


def compile_jianying_blueprint(
    resolved_timeline_path: str | Path,
    output_dir: str | Path,
) -> tuple[JianyingEditBlueprint, Path]:
    timeline_path = Path(resolved_timeline_path).resolve()
    timeline_root = timeline_path.parent
    output_root = Path(output_dir).resolve()
    media_root = output_root / "media"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))

    asset_by_ref = {asset["asset_ref"]: asset for asset in timeline["render_assets"]}
    effect_by_id = {
        effect["effect_instance_id"]: effect for effect in timeline["effect_instances"]
    }
    visual_clips: list[BlueprintVisualClip] = []

    for track in timeline["visual_tracks"]:
        if track["track_kind"] != "base":
            continue
        for clip in track["clips"]:
            effect = effect_by_id[clip["effect_instance_id"]]
            items = clip["ordered_items"] or [
                {
                    "item_id": clip["clip_id"],
                    "asset_binding_name": next(iter(clip["asset_bindings"])),
                    "start_frame": clip["start_frame"],
                    "end_frame": clip["end_frame"],
                }
            ]
            for index, item in enumerate(items):
                asset_ref = clip["asset_bindings"][item["asset_binding_name"]]
                asset = asset_by_ref[asset_ref]
                source = timeline_root / asset["object_key"]
                if not source.is_file():
                    raise FileNotFoundError(f"resolved render asset missing: {source}")
                file_name = f"{len(visual_clips):03d}_{_safe_name(item['item_id'])}.png"
                destination = media_root / "visual" / file_name
                _compose_frame(
                    source,
                    destination,
                    canvas_width=timeline["width"],
                    canvas_height=timeline["height"],
                    layout=clip["layout"],
                )
                start_frame = int(item["start_frame"])
                end_frame = int(item["end_frame"])
                visual_clips.append(
                    BlueprintVisualClip(
                        clip_id=f"{clip['clip_id']}#{index}",
                        scene_id=clip["scene_id"],
                        source_asset_ref=asset_ref,
                        media_path=destination.relative_to(output_root).as_posix(),
                        start_frame=start_frame,
                        end_frame=end_frame,
                        effect_id=effect["effect_id"],
                        keyframes=_effect_keyframes(
                            effect,
                            clip_start=start_frame,
                            clip_end=end_frame,
                        ),
                    )
                )

    subtitle_cues = [
        BlueprintSubtitleCue(
            cue_id=cue["cue_id"],
            scene_id=cue["scene_id"],
            text=cue["text"],
            start_frame=cue["start_frame"],
            end_frame=cue["end_frame"],
            slot_id=cue["slot_id"],
            style_id=cue["style_id"],
            emphasize_text=cue.get("emphasize_text"),
        )
        for cue in timeline["subtitle_track"]
    ]

    audio_clips: list[BlueprintAudioClip] = []
    for index, audio in enumerate(timeline["audio_tracks"]):
        source = timeline_root / audio["object_key"]
        if not source.is_file():
            raise FileNotFoundError(f"resolved audio asset missing: {source}")
        suffix = source.suffix.lower() or ".wav"
        destination = media_root / "audio" / f"{index:03d}_{_safe_name(audio['kind'])}{suffix}"
        _copy_audio(source, destination)
        audio_clips.append(
            BlueprintAudioClip(
                track_id=audio["track_id"],
                kind=audio["kind"],
                media_path=destination.relative_to(output_root).as_posix(),
                start_frame=audio["start_frame"],
                gain_db=audio["gain_db"],
                max_duration_ms=audio.get("max_duration_ms"),
                fade_in_ms=audio.get("fade_in_ms", 0),
                fade_out_ms=audio.get("fade_out_ms", 0),
                anchor_id=audio.get("anchor_id"),
                hit_frame=audio.get("hit_frame"),
                expected_peak_frame=audio.get("expected_peak_frame"),
            )
        )

    blueprint = JianyingEditBlueprint(
        case_id=timeline["case_id"],
        run_id=timeline["run_id"],
        timeline_sha256=_sha256(timeline_path),
        canvas=BlueprintCanvas(
            width=timeline["width"],
            height=timeline["height"],
            fps=timeline["fps"],
            platform_profile_id=timeline["platform_profile_id"],
        ),
        frame_count=timeline["frame_count"],
        visual_clips=visual_clips,
        subtitle_cues=subtitle_cues,
        audio_clips=audio_clips,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    blueprint_path = output_root / "edit_blueprint.json"
    blueprint_path.write_text(
        json.dumps(blueprint.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return blueprint, blueprint_path

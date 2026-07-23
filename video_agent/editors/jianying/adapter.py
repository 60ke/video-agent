"""Execute a Jianying EditBlueprint through jianying-editor-skill."""

from __future__ import annotations

import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Literal

from .contracts import BlueprintKeyframe, JianyingEditBlueprint

_EASING = {
    "linear": {"curve_type": "Line"},
    "ease_in": {
        "curve_type": "Bezier",
        "left_control": (0.42, 0.0),
        "right_control": (1.0, 1.0),
    },
    "ease_out": {
        "curve_type": "Bezier",
        "left_control": (0.0, 0.0),
        "right_control": (0.58, 1.0),
    },
    "ease_in_out": {
        "curve_type": "Bezier",
        "left_control": (0.42, 0.0),
        "right_control": (0.58, 1.0),
    },
}

MotionBackend = Literal["keyframes", "jianying_native"]


def _native_clip_animation(
    clip: Any,
    *,
    is_first_clip: bool,
) -> tuple[str, str] | None:
    """Select a Jianying animation from scene semantics, not legacy effect IDs."""
    if is_first_clip:
        return ("IntroType", "翻入")
    if clip.motion_context == "parameter":
        return ("IntroType", "渐显")
    if clip.motion_context == "result":
        if clip.asset_orientation == "landscape":
            return ("GroupAnimationType", "左拉镜")
        return ("IntroType", "轻微放大")
    if clip.motion_context == "site_home":
        return ("IntroType", "缩小")
    return None


def _native_transition_name(previous_clip: Any, current_clip: Any) -> str:
    """Pick a native transition from semantic grouping and causal relations."""
    if previous_clip.scene_id == current_clip.scene_id:
        if previous_clip.motion_context == "gallery":
            return "左移"
        if previous_clip.motion_context in {
            "reference_result",
            "result_flat_plan",
        }:
            return "前后对比_II"
    if current_clip.motion_context == "site_home":
        return "推近"
    return "叠化"


def _bounded_native_duration_us(
    previous_clip: Any,
    current_clip: Any,
    *,
    fps: int,
    preferred_frames: int = 10,
) -> int:
    """Keep a transition inside both adjacent clips."""
    previous_frames = previous_clip.end_frame - previous_clip.start_frame
    current_frames = current_clip.end_frame - current_clip.start_frame
    duration_frames = max(
        1,
        min(preferred_frames, previous_frames // 2, current_frames // 2),
    )
    return _frame_to_us(duration_frames, fps)


def _frame_to_us(frame: int, fps: int) -> int:
    return round(frame * 1_000_000 / fps)


def _duration_us(start_frame: int, end_frame: int, fps: int) -> int:
    return _frame_to_us(end_frame, fps) - _frame_to_us(start_frame, fps)


def _load_skill(skill_root: Path) -> tuple[Any, Any]:
    scripts = skill_root.resolve() / "scripts"
    if not scripts.is_dir():
        raise FileNotFoundError(f"jianying skill scripts missing: {scripts}")
    scripts_value = str(scripts)
    for module_name in list(sys.modules):
        if (
            module_name == "jy_wrapper"
            or module_name == "core"
            or module_name.startswith("core.")
            or module_name == "utils"
            or module_name.startswith("utils.")
            or module_name == "pyJianYingDraft"
            or module_name.startswith("pyJianYingDraft.")
        ):
            sys.modules.pop(module_name, None)
    if scripts_value not in sys.path:
        sys.path.insert(0, scripts_value)
    wrapper = importlib.import_module("jy_wrapper")
    draft = importlib.import_module("pyJianYingDraft")
    return wrapper, draft


def _keyframe_property(draft: Any, keyframe: BlueprintKeyframe) -> Any:
    mapping = {
        "scale": draft.KeyframeProperty.uniform_scale,
        "position_x": draft.KeyframeProperty.position_x,
        "position_y": draft.KeyframeProperty.position_y,
        "rotation": draft.KeyframeProperty.rotation,
        "alpha": draft.KeyframeProperty.alpha,
    }
    return mapping[keyframe.property]


class JianyingDraftAdapter:
    def __init__(
        self,
        *,
        skill_root: str | Path,
        drafts_root: str | Path | None = None,
    ) -> None:
        self.skill_root = Path(skill_root).resolve()
        self.drafts_root = Path(drafts_root).resolve() if drafts_root else None
        self.wrapper, self.draft = _load_skill(self.skill_root)

    def build(
        self,
        blueprint: JianyingEditBlueprint,
        *,
        blueprint_root: str | Path,
        project_name: str,
        motion_backend: MotionBackend = "keyframes",
    ) -> dict[str, Any]:
        root = Path(blueprint_root).resolve()
        fps = blueprint.canvas.fps
        project = self.wrapper.JyProject(
            project_name,
            width=blueprint.canvas.width,
            height=blueprint.canvas.height,
            drafts_root=str(self.drafts_root) if self.drafts_root else None,
            overwrite=True,
        )

        visual_segments: list[tuple[Any, Any]] = []
        for clip_index, clip in enumerate(blueprint.visual_clips):
            source = root / clip.media_path
            segment = project.add_media_safe(
                str(source),
                start_time=_frame_to_us(clip.start_frame, fps),
                duration=_duration_us(clip.start_frame, clip.end_frame, fps),
                track_name="VideoTrack",
            )
            if segment is None:
                raise RuntimeError(f"failed to add visual clip: {clip.clip_id}")
            if motion_backend == "keyframes":
                for keyframe in clip.keyframes:
                    segment.add_keyframe(
                        _keyframe_property(self.draft, keyframe),
                        _frame_to_us(keyframe.frame_offset, fps),
                        keyframe.value,
                        **_EASING[keyframe.easing],
                    )
            else:
                animation = _native_clip_animation(
                    clip,
                    is_first_clip=clip_index == 0,
                )
                if animation:
                    enum_name, member_name = animation
                    animation_type = getattr(getattr(self.draft, enum_name), member_name)
                    clip_duration = _duration_us(
                        clip.start_frame,
                        clip.end_frame,
                        fps,
                    )
                    duration = min(500_000, max(100_000, clip_duration // 3))
                    segment.add_animation(animation_type, duration=duration)
            visual_segments.append((clip, segment))

        native_transition_count = 0
        if motion_backend == "jianying_native":
            for index in range(1, len(visual_segments)):
                previous_clip, previous_segment = visual_segments[index - 1]
                current_clip, _ = visual_segments[index]
                transition_name = _native_transition_name(
                    previous_clip,
                    current_clip,
                )
                transition_type = project._resolve_enum(
                    self.draft.TransitionType,
                    transition_name,
                )
                if transition_type is None:
                    raise RuntimeError(
                        f"native Jianying transition unavailable: {transition_name}"
                    )
                previous_segment.add_transition(
                    transition_type,
                    duration=_bounded_native_duration_us(
                        previous_clip,
                        current_clip,
                        fps=fps,
                    ),
                )
                native_transition_count += 1

        for audio in blueprint.audio_clips:
            source = root / audio.media_path
            duration = (
                audio.max_duration_ms * 1000 if audio.max_duration_ms is not None else None
            )
            segment = project.add_audio_safe(
                str(source),
                start_time=_frame_to_us(audio.start_frame, fps),
                duration=duration,
                track_name={
                    "voice": "VoiceOver",
                    "bgm": "BGM",
                    "sfx": "SFX",
                    "outro": "OutroAudio",
                }[audio.kind],
            )
            if segment is None:
                raise RuntimeError(f"failed to add audio clip: {audio.track_id}")
            segment.volume = math.pow(10.0, audio.gain_db / 20.0)
            if audio.fade_in_ms or audio.fade_out_ms:
                segment.add_fade(audio.fade_in_ms * 1000, audio.fade_out_ms * 1000)

        subtitle_lane_ends: list[int] = []
        for cue in blueprint.subtitle_cues:
            lane_index = next(
                (
                    index
                    for index, end_frame in enumerate(subtitle_lane_ends)
                    if cue.start_frame >= end_frame
                ),
                len(subtitle_lane_ends),
            )
            if lane_index == len(subtitle_lane_ends):
                subtitle_lane_ends.append(cue.end_frame)
            else:
                subtitle_lane_ends[lane_index] = cue.end_frame
            subtitle_track_name = (
                "Subtitles" if lane_index == 0 else f"Subtitles_{lane_index + 1}"
            )
            clip_settings = self.draft.ClipSettings(
                transform_y=0.74 if cue.slot_id == "subtitle_top" else -0.72
            )
            style = self.draft.TextStyle(
                size=7.2 if cue.style_id == "gallery_yellow" else 6.2,
                bold=True,
                color=(1.0, 0.82, 0.12)
                if cue.style_id == "gallery_yellow"
                else (1.0, 1.0, 1.0),
            )
            kwargs = {
                "start_time": _frame_to_us(cue.start_frame, fps),
                "duration": _duration_us(cue.start_frame, cue.end_frame, fps),
                "track_name": subtitle_track_name,
                "clip_settings": clip_settings,
                "style": style,
                "border": self.draft.TextBorder(
                    color=(0.0, 0.0, 0.0), alpha=1.0, width=45.0
                ),
            }
            if motion_backend == "jianying_native":
                cue_duration = _duration_us(cue.start_frame, cue.end_frame, fps)
                if cue_duration >= 200_000:
                    kwargs["anim_in"] = "渐显"
                    kwargs["anim_in_duration"] = min(250_000, cue_duration // 3)
            if cue.emphasize_text and cue.style_id != "gallery_yellow":
                project.add_rich_text(
                    cue.text,
                    [
                        {
                            "word": cue.emphasize_text,
                            "color": (1.0, 0.74, 0.08),
                            "bold": True,
                        }
                    ],
                    **kwargs,
                )
            else:
                project.add_text_simple(cue.text, **kwargs)

        save_result = project.save()
        draft_path = Path(save_result["draft_path"])
        manifest = {
            "schema_version": 1,
            "project_name": project_name,
            "draft_path": draft_path.as_posix(),
            "canvas": blueprint.canvas.model_dump(mode="json"),
            "frame_count": blueprint.frame_count,
            "duration_us": _frame_to_us(blueprint.frame_count, fps),
            "visual_clip_count": len(blueprint.visual_clips),
            "subtitle_cue_count": len(blueprint.subtitle_cues),
            "audio_clip_count": len(blueprint.audio_clips),
            "timeline_sha256": blueprint.timeline_sha256,
            "motion_backend": motion_backend,
            "native_transition_count": native_transition_count,
            "native_animation_count": (
                sum(
                    1
                    for index, clip in enumerate(blueprint.visual_clips)
                    if _native_clip_animation(clip, is_first_clip=index == 0)
                )
                if motion_backend == "jianying_native"
                else 0
            ),
        }
        return manifest


def write_manifest(manifest: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination

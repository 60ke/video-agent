"""Contracts for the deterministic Jianying execution backend."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BlueprintModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlueprintCanvas(BlueprintModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    platform_profile_id: str = Field(min_length=1)


class BlueprintKeyframe(BlueprintModel):
    property: Literal["scale", "position_x", "position_y", "rotation", "alpha"]
    frame_offset: int = Field(ge=0)
    value: float
    easing: Literal["linear", "ease_in", "ease_out", "ease_in_out"] = "ease_out"


class BlueprintVisualClip(BlueprintModel):
    clip_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    source_asset_ref: str = Field(min_length=1)
    media_path: str = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    effect_id: str = Field(min_length=1)
    motion_context: Literal[
        "site_home",
        "gallery",
        "parameter",
        "result",
        "reference_result",
        "result_flat_plan",
        "other",
    ] = "other"
    asset_orientation: Literal["landscape", "portrait", "square"] = "square"
    scene_clip_index: int = Field(default=0, ge=0)
    scene_clip_count: int = Field(default=1, ge=1)
    keyframes: list[BlueprintKeyframe] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_span(self) -> BlueprintVisualClip:
        if self.end_frame <= self.start_frame:
            raise ValueError("visual clip end_frame must be greater than start_frame")
        duration = self.end_frame - self.start_frame
        if any(keyframe.frame_offset >= duration for keyframe in self.keyframes):
            raise ValueError("visual keyframe must fall inside its clip")
        if self.scene_clip_index >= self.scene_clip_count:
            raise ValueError("scene_clip_index must be smaller than scene_clip_count")
        return self


class BlueprintSubtitleCue(BlueprintModel):
    cue_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    slot_id: Literal["subtitle_top", "subtitle_lower"]
    style_id: Literal["default", "gallery_yellow"]
    emphasize_text: str | None = None

    @model_validator(mode="after")
    def valid_span(self) -> BlueprintSubtitleCue:
        if self.end_frame <= self.start_frame:
            raise ValueError("subtitle end_frame must be greater than start_frame")
        if self.emphasize_text and self.emphasize_text not in self.text:
            raise ValueError("emphasize_text must be present in subtitle text")
        return self


class BlueprintAudioClip(BlueprintModel):
    track_id: str = Field(min_length=1)
    kind: Literal["voice", "bgm", "sfx", "outro"]
    media_path: str = Field(min_length=1)
    start_frame: int = Field(ge=0)
    gain_db: float = 0.0
    max_duration_ms: int | None = Field(default=None, ge=1)
    fade_in_ms: int = Field(default=0, ge=0)
    fade_out_ms: int = Field(default=0, ge=0)
    anchor_id: str | None = None
    hit_frame: int | None = Field(default=None, ge=0)
    expected_peak_frame: int | None = Field(default=None, ge=0)


class JianyingEditBlueprint(BlueprintModel):
    schema_version: Literal[1] = 1
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    timeline_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    canvas: BlueprintCanvas
    frame_count: int = Field(gt=0)
    visual_clips: list[BlueprintVisualClip] = Field(min_length=1)
    subtitle_cues: list[BlueprintSubtitleCue] = Field(default_factory=list)
    audio_clips: list[BlueprintAudioClip] = Field(default_factory=list)

    @model_validator(mode="after")
    def clips_within_timeline(self) -> JianyingEditBlueprint:
        for clip in self.visual_clips:
            if clip.end_frame > self.frame_count:
                raise ValueError(f"visual clip exceeds timeline: {clip.clip_id}")
        for cue in self.subtitle_cues:
            if cue.end_frame > self.frame_count:
                raise ValueError(f"subtitle cue exceeds timeline: {cue.cue_id}")
        return self

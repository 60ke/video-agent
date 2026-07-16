from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .base import Contract, VersionedContract


class RenderAsset(Contract):
    asset_id: str
    path: str
    sha256: str
    width: int
    height: int
    media_type: str = "image"
    fps: float | None = Field(default=None, gt=0)
    frame_count: int | None = Field(default=None, gt=0)
    duration_ms: int | None = Field(default=None, gt=0)
    accent_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class CompiledCue(Contract):
    action: str
    anchor_id: str
    hit_frame: int
    anticipation_frames: int = Field(default=5, ge=0, le=15)
    settle_frames: int = Field(default=8, ge=0, le=30)
    hold_frames: int = Field(default=12, ge=0)


class CompiledParameterFrameSequence(Contract):
    sequence_id: str = Field(min_length=1)
    base_asset_id: str = Field(min_length=1)
    stage_asset_id: str = Field(min_length=1)
    final_asset_id: str = Field(min_length=1)
    start_frame: int = Field(ge=0)
    stage_frame: int = Field(ge=0)
    hit_frame: int = Field(ge=0)
    minimum_hold_frames: int = Field(ge=1)
    crossfade_frames: int = Field(ge=1)
    timing_source: str
    matched_keywords: list[dict[str, int | str]] = Field(default_factory=list)
    timing_adjustment_reason: str | None = None
    required_field_labels: list[str] = Field(default_factory=list)
    callout_text: str = "填写必填项"
    callout_reveal_frames: int = Field(default=10, ge=1, le=90)

    @model_validator(mode="after")
    def valid_range(self) -> "CompiledParameterFrameSequence":
        if not self.start_frame < self.stage_frame < self.hit_frame:
            raise ValueError("parameter frame sequence must progress base, stage, final")
        return self


class CompiledEditorFlowSequence(Contract):
    sequence_id: str = Field(min_length=1)
    page_asset_id: str = Field(min_length=1)
    modal_asset_id: str = Field(min_length=1)
    focus_frame: int = Field(ge=0)
    modal_frame: int = Field(ge=0)
    focus_x: float = Field(ge=0.0, le=1.0)
    focus_y: float = Field(ge=0.0, le=1.0)
    focus_w: float = Field(gt=0.0, le=1.0)
    focus_h: float = Field(gt=0.0, le=1.0)
    lens_zoom: float = Field(default=2.15, ge=1.2, le=4.0)
    reveal_frames: int = Field(default=10, ge=4, le=45)

    @model_validator(mode="after")
    def valid_order(self) -> "CompiledEditorFlowSequence":
        if self.modal_frame < self.focus_frame:
            raise ValueError("editor modal cannot appear before focus")
        return self


class CompiledGalleryItem(Contract):
    asset_id: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    hit_frame: int = Field(ge=0)
    onset_frame: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def resolve_onset(self) -> "CompiledGalleryItem":
        if self.onset_frame is None:
            object.__setattr__(self, "onset_frame", self.hit_frame)
        return self


class RenderShot(Contract):
    shot_id: str
    scene_id: str | None = None
    scene_kind: str | None = None
    track: str = "base"
    beat_ids: list[str] = Field(min_length=1)
    template: str
    asset_bindings: dict[str, str] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    cues: list[CompiledCue] = Field(default_factory=list)
    motion: str = "none"
    transition_in: dict[str, int | str] = Field(default_factory=lambda: {"kind": "cut", "duration_frames": 0})
    long_hold_reason: str | None = None
    overlay_layout: dict[str, float | int | str] | None = None
    parameter_sequence: CompiledParameterFrameSequence | None = None
    editor_flow_sequence: CompiledEditorFlowSequence | None = None
    gallery_items: list[CompiledGalleryItem] = Field(default_factory=list)

    @property
    def asset_ids(self) -> list[str]:
        return list(self.asset_bindings.values())

    @model_validator(mode="after")
    def positive_span(self) -> "RenderShot":
        if self.end_frame <= self.start_frame:
            raise ValueError("render shot must have positive duration")
        return self


class SubtitleCue(Contract):
    cue_id: str
    text: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    slot: str
    emphasize: str | None = None
    beat_id: str | None = None
    style: Literal["default", "gallery_yellow"] = "default"


class AudioTrack(Contract):
    kind: str
    path: str
    start_frame: int = Field(default=0, ge=0)
    gain_db: float = 0.0
    loop: bool = False
    duck_under_voice: bool = False
    anchor_id: str | None = None
    semantic_id: str | None = None
    trim_start_ms: int = Field(default=0, ge=0)
    max_duration_ms: int | None = Field(default=None, gt=0)
    fade_in_ms: int = Field(default=0, ge=0)
    fade_out_ms: int = Field(default=0, ge=0)
    sync_frame: int | None = Field(default=None, ge=0)
    sync_point: str | None = None
    effective_sync_offset_ms: int = Field(default=0, ge=0)


class RenderPlan(VersionedContract):
    case_id: str
    run_id: str
    width: int = 1080
    height: int = 1920
    fps: int = 30
    frame_count: int = Field(gt=0)
    preferred_min_sec: float = 15.0
    preferred_max_sec: float = 20.0
    hard_max_sec: float = 24.0
    platform_profile: str = "douyin_portrait_v1"
    assets: list[RenderAsset]
    shots: list[RenderShot] = Field(min_length=1)
    subtitles: list[SubtitleCue]
    audio_tracks: list[AudioTrack]
    style: dict[str, Any] = Field(default_factory=dict)

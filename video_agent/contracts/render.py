from __future__ import annotations

from typing import Any

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
    anchors: dict[str, dict[str, float]] = Field(default_factory=dict)
    anchor_panels: dict[str, dict[str, float]] = Field(default_factory=dict)


class CompiledCue(Contract):
    action: str
    anchor_id: str
    hit_frame: int
    anticipation_frames: int = Field(default=5, ge=0, le=15)
    settle_frames: int = Field(default=8, ge=0, le=30)
    hold_frames: int = Field(default=12, ge=0)
    asset_anchor_id: str | None = None


class RenderShot(Contract):
    shot_id: str
    beat_id: str
    template: str
    asset_ids: list[str] = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    cues: list[CompiledCue] = Field(default_factory=list)
    effect: str | None = None
    long_hold_reason: str | None = None

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

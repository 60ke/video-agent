"""V4 CompiledVideoTimeline and Remotion Effect Adapter props."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from .common import V4Contract

_SHA256 = r"^[a-f0-9]{64}$"
_ASSET_REF = r"^asset://A\d{4,}$"

FitMode = Literal["contain", "cover"]
TrackKind = Literal["base", "overlay"]
HoldReason = Literal["reading", "appreciation", "pause", "scene_span"]
MediaKind = Literal["image", "video"]
VariantId = Literal["full", "compact", "instant"]
MotionDirection = Literal["none", "left", "right", "up", "down"]
SubtitleSlot = Literal["subtitle_top", "subtitle_lower"]
SubtitleStyle = Literal["default", "gallery_yellow"]
AudioKind = Literal["voice", "bgm", "sfx", "outro"]


class CompiledLayout(V4Contract):
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fit: FitMode
    border_radius: int = Field(ge=0)
    opacity: float = Field(ge=0.0, le=1.0)
    background_style_id: str = Field(min_length=1)
    safe_area_profile_id: str = Field(min_length=1)


class CompiledRenderAsset(V4Contract):
    asset_ref: str = Field(pattern=_ASSET_REF)
    object_key: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)
    media_kind: MediaKind
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_ms: int | None = Field(default=None, ge=0)
    has_alpha: bool = False


class CompiledEffectEvent(V4Contract):
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    hit_frame: int = Field(ge=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)


class CompiledEffectInstance(V4Contract):
    effect_instance_id: str = Field(min_length=1)
    effect_id: str = Field(min_length=1)
    effect_version: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    variant_id: VariantId
    direction: MotionDirection = "none"
    parameters: dict[str, Any] = Field(default_factory=dict)
    events: list[CompiledEffectEvent] = Field(default_factory=list)


class RemotionOrderedItem(V4Contract):
    item_id: str = Field(min_length=1)
    asset_binding_name: str = Field(min_length=1)
    member_key: str | None = None
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    hit_frame: int = Field(ge=0)


class CompiledVisualClip(V4Contract):
    clip_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    slot_id: str | None = None
    group_ref: str | None = None
    member_key: str | None = None
    asset_bindings: dict[str, str] = Field(default_factory=dict)
    ordered_items: list[RemotionOrderedItem] = Field(default_factory=list)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    semantic_hit_frame: int = Field(ge=0)
    hold_reason: HoldReason | None = None
    layout_profile_id: str = Field(min_length=1)
    layout: CompiledLayout
    effect_instance_id: str = Field(min_length=1)
    z_index: int = 0

    @model_validator(mode="after")
    def valid_span(self) -> CompiledVisualClip:
        if self.end_frame <= self.start_frame:
            raise ValueError("visual clip end_frame must be exclusive and > start_frame")
        return self


class CompiledVisualTrack(V4Contract):
    track_id: str = Field(min_length=1)
    track_kind: TrackKind
    clips: list[CompiledVisualClip] = Field(default_factory=list)


class CompiledSubtitleCueV4(V4Contract):
    cue_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    anchor_id: str | None = None
    text: str = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    slot_id: SubtitleSlot
    style_id: SubtitleStyle = "default"
    emphasize_text: str | None = None
    emphasize_start_frame: int | None = Field(default=None, ge=0)
    single_line: Literal[True] = True

    @model_validator(mode="after")
    def valid_span(self) -> CompiledSubtitleCueV4:
        if self.end_frame <= self.start_frame:
            raise ValueError("subtitle cue end_frame must be exclusive and > start_frame")
        return self


class CompiledAudioTrackV4(V4Contract):
    track_id: str = Field(min_length=1)
    kind: AudioKind
    object_key: str = Field(min_length=1)
    sha256: str = Field(pattern=_SHA256)
    start_frame: int = Field(ge=0)
    gain_db: float = 0.0
    anchor_id: str | None = None
    semantic_id: str | None = None
    hit_frame: int | None = Field(default=None, ge=0)
    configured_sync_offset_ms: int = 0
    effective_sync_offset_ms: int = 0
    trim_start_ms: int = Field(ge=0, default=0)
    expected_peak_frame: int | None = Field(default=None, ge=0)
    max_duration_ms: int | None = Field(default=None, ge=1)
    fade_in_ms: int = Field(ge=0, default=0)
    fade_out_ms: int = Field(ge=0, default=0)


class CompiledVideoTimeline(V4Contract):
    schema_version: int = Field(ge=1)
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: int = Field(gt=0)
    narration_frame_count: int = Field(ge=0)
    postroll_frames: int = Field(ge=0, default=0)
    frame_count: int = Field(ge=0)
    platform_profile_id: str = Field(min_length=1)
    registry_snapshot_id: str = Field(min_length=1)
    speech_timing_lock_sha256: str = Field(pattern=_SHA256)
    anchored_timing_plan_sha256: str = Field(pattern=_SHA256)
    resolved_asset_plan_sha256: str = Field(pattern=_SHA256)
    motion_audio_plan_sha256: str = Field(pattern=_SHA256)
    used_assets_snapshot_id: str = Field(min_length=1)
    render_assets: list[CompiledRenderAsset] = Field(default_factory=list)
    visual_tracks: list[CompiledVisualTrack] = Field(default_factory=list)
    effect_instances: list[CompiledEffectInstance] = Field(default_factory=list)
    subtitle_track: list[CompiledSubtitleCueV4] = Field(default_factory=list)
    audio_tracks: list[CompiledAudioTrackV4] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_frame_count(self) -> CompiledVideoTimeline:
        expected = self.narration_frame_count + self.postroll_frames
        if self.frame_count != expected:
            raise ValueError(
                f"frame_count ({self.frame_count}) must equal narration_frame_count + postroll_frames ({expected})"
            )
        instance_ids = {item.effect_instance_id for item in self.effect_instances}
        for track in self.visual_tracks:
            for clip in track.clips:
                if clip.effect_instance_id not in instance_ids:
                    raise ValueError(
                        f"clip {clip.clip_id} references unknown effect_instance_id {clip.effect_instance_id}"
                    )
        return self


class RemotionEffectEventProps(V4Contract):
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    hit_frame: int = Field(ge=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)


class RemotionEffectProps(V4Contract):
    effect_instance_id: str = Field(min_length=1)
    effect_id: str = Field(min_length=1)
    effect_version: str = Field(min_length=1)
    variant_id: VariantId
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    events: list[RemotionEffectEventProps] = Field(default_factory=list)
    direction: MotionDirection = "none"
    layout: CompiledLayout
    parameters: dict[str, Any] = Field(default_factory=dict)
    assets: dict[str, str] = Field(default_factory=dict)
    ordered_items: list[RemotionOrderedItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_span(self) -> RemotionEffectProps:
        if self.end_frame <= self.start_frame:
            raise ValueError("end_frame must be exclusive and > start_frame")
        return self

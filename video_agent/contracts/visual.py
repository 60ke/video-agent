from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract, VersionedContract


class CueBinding(Contract):
    action: str
    anchor_id: str
    offset_frames: int = Field(default=0, ge=-900, le=900)
    sfx: str | None = None


class TimeRef(Contract):
    """An immutable timing-lock anchor plus a deterministic frame offset."""

    anchor_id: str = Field(min_length=1)
    offset_frames: int = Field(default=0, ge=-900, le=900)


class TransitionIn(Contract):
    kind: Literal["cut", "crossfade", "slide_left", "slide_right"] = "cut"
    duration_frames: int = Field(default=0, ge=0, le=30)

    @model_validator(mode="after")
    def cut_has_no_duration(self) -> "TransitionIn":
        if self.kind == "cut" and self.duration_frames:
            raise ValueError("cut transitions must have zero duration")
        if self.kind != "cut" and self.duration_frames < 4:
            raise ValueError("visible transitions need at least four frames")
        return self


class OverlayLayout(Contract):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)
    fit: Literal["contain", "cover"] = "contain"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    z_index: int = Field(default=10, ge=1, le=100)

    @model_validator(mode="after")
    def safe_normalized_box(self) -> "OverlayLayout":
        if self.x + self.w > 1.0 or self.y + self.h > 1.0:
            raise ValueError("overlay layout must stay inside content_safe")
        if self.w * self.h > 0.30:
            raise ValueError("overlay layout may cover at most 30% of content_safe")
        return self


class CalloutAnimation(Contract):
    kind: Literal["handdrawn_circle_reveal"] = "handdrawn_circle_reveal"
    duration_frames: int = Field(default=18, ge=8, le=45)
    completion_action: str = "callout.complete"
    finish_pulse_scale: float = Field(default=1.018, ge=1.0, le=1.08)


class ShotPlan(Contract):
    shot_id: str
    track: Literal["base", "overlay"] = "base"
    beat_ids: list[str] = Field(min_length=1)
    start: TimeRef
    end: TimeRef
    template: str
    asset_bindings: dict[str, str] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    cue_bindings: list[CueBinding] = Field(default_factory=list)
    energy: Literal["low", "medium", "high"] = "medium"
    motion: Literal["none", "fade_in", "fade_out", "scale_in", "scale_out", "perspective_push_in"] = "none"
    transition_in: TransitionIn = Field(default_factory=TransitionIn)
    evidence_policy: str = "source_pixels_visible"
    long_hold_reason: Literal["reading", "appreciation", "pause"] | None = None
    overlay_layout: OverlayLayout | None = None
    callout_animation: CalloutAnimation | None = None

    @property
    def asset_ids(self) -> list[str]:
        return list(self.asset_bindings.values())

    @model_validator(mode="after")
    def range_is_not_empty(self) -> "ShotPlan":
        if self.start.anchor_id == self.end.anchor_id and self.start.offset_frames >= self.end.offset_frames:
            raise ValueError("shot end must be after shot start")
        if self.track == "overlay" and self.overlay_layout is None:
            raise ValueError("overlay shots require overlay_layout")
        if self.track == "base" and self.overlay_layout is not None:
            raise ValueError("base shots cannot define overlay_layout")
        return self


class VisualPlan(VersionedContract):
    case_id: str
    timing_lock_sha256: str | None = None
    shots: list[ShotPlan] = Field(min_length=1)

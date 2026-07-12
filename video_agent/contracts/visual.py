from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract, VersionedContract


class CueBinding(Contract):
    action: str
    anchor_id: str
    offset_frames: int = Field(default=0, ge=-900, le=900)
    asset_anchor_id: str | None = None
    sfx: str | None = None


class TimeRef(Contract):
    """An immutable timing-lock anchor plus a deterministic frame offset."""

    anchor_id: str = Field(min_length=1)
    offset_frames: int = Field(default=0, ge=-900, le=900)


class TransitionIn(Contract):
    kind: Literal["cut", "crossfade", "slide_left", "slide_right", "wipe_left", "wipe_right"] = "cut"
    duration_frames: int = Field(default=0, ge=0, le=30)

    @model_validator(mode="after")
    def cut_has_no_duration(self) -> "TransitionIn":
        if self.kind == "cut" and self.duration_frames:
            raise ValueError("cut transitions must have zero duration")
        if self.kind != "cut" and self.duration_frames < 4:
            raise ValueError("visible transitions need at least four frames")
        return self


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

    @property
    def asset_ids(self) -> list[str]:
        return list(self.asset_bindings.values())

    @model_validator(mode="after")
    def range_is_not_empty(self) -> "ShotPlan":
        if self.start.anchor_id == self.end.anchor_id and self.start.offset_frames >= self.end.offset_frames:
            raise ValueError("shot end must be after shot start")
        return self


class VisualPlan(VersionedContract):
    case_id: str
    timing_lock_sha256: str | None = None
    shots: list[ShotPlan] = Field(min_length=1)

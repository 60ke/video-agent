from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Contract, VersionedContract


class CueBinding(Contract):
    action: str
    anchor_id: str
    asset_anchor_id: str | None = None
    sfx: str | None = None


class ShotPlan(Contract):
    shot_id: str
    beat_id: str
    template: str
    asset_ids: list[str] = Field(min_length=1)
    cue_bindings: list[CueBinding] = Field(default_factory=list)
    energy: Literal["low", "medium", "high"] = "medium"
    effect: str | None = None
    evidence_policy: str = "source_pixels_visible"
    long_hold_reason: Literal["reading", "appreciation", "pause"] | None = None


class VisualPlan(VersionedContract):
    case_id: str
    timing_lock_sha256: str | None = None
    shots: list[ShotPlan] = Field(min_length=1)

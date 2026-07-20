"""V4 AnchoredTimingPlan — Scene phrases bound to speech tokens."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import V4Contract

_SHA256 = r"^[a-f0-9]{64}$"

AnchorBindingKind = Literal["slot", "operation", "claim", "effect_event", "sfx_intent"]


class AnchoredSceneSpan(V4Contract):
    scene_id: str = Field(min_length=1)
    token_ids: list[str] = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)  # exclusive

    @model_validator(mode="after")
    def valid_span(self) -> AnchoredSceneSpan:
        if self.end_frame <= self.start_frame:
            raise ValueError("scene span end_frame must be exclusive and > start_frame")
        return self


class PhraseAnchorV4(V4Contract):
    """Canonical semantic hit. Do not import V3 contracts.timing.PhraseAnchor."""

    anchor_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    token_ids: list[str] = Field(min_length=1)
    onset_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    onset_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    hit_frame: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_hit(self) -> PhraseAnchorV4:
        if self.hit_frame != self.onset_frame:
            raise ValueError("hit_frame must equal onset_frame (first token onset)")
        if self.end_frame <= self.onset_frame:
            raise ValueError("phrase anchor must have a positive exclusive frame span")
        if self.end_ms < self.onset_ms:
            raise ValueError("phrase end_ms must be >= onset_ms")
        return self


class AnchorBinding(V4Contract):
    binding_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    binding_kind: AnchorBindingKind
    source_id: str = Field(min_length=1)


class AnchoredTimingPlan(V4Contract):
    schema_version: int = Field(ge=1)
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    narration_sha256: str = Field(pattern=_SHA256)
    speech_timing_lock_sha256: str = Field(pattern=_SHA256)
    scene_plan_sha256: str = Field(pattern=_SHA256)
    fps: int = Field(gt=0)
    duration_frames: int = Field(ge=0)
    scene_spans: list[AnchoredSceneSpan] = Field(default_factory=list)
    anchors: list[PhraseAnchorV4] = Field(default_factory=list)
    bindings: list[AnchorBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> AnchoredTimingPlan:
        scene_ids = [span.scene_id for span in self.scene_spans]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("AnchoredTimingPlan.scene_spans scene_id must be unique")
        anchor_ids = [anchor.anchor_id for anchor in self.anchors]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("AnchoredTimingPlan.anchors anchor_id must be unique")
        binding_ids = [binding.binding_id for binding in self.bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("AnchoredTimingPlan.bindings binding_id must be unique")
        known = set(anchor_ids)
        for binding in self.bindings:
            if binding.anchor_id not in known:
                raise ValueError(f"binding {binding.binding_id} references unknown anchor {binding.anchor_id}")
        return self

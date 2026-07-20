"""Stable Stage 6 fail-loud error codes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STAGE6_ERROR_CODES = frozenset(
    {
        "speech_text_mismatch",
        "scene_span_gap",
        "scene_span_overlap",
        "anchor_unresolved",
        "anchor_phrase_ambiguous",
        "timeline_base_track_gap",
        "timeline_base_track_overlap",
        "effect_budget_revalidation_failed",
        "effect_variant_unavailable",
        "sfx_peak_tolerance_exceeded",
        "subtitle_single_line_overflow",
        "claim_evidence_not_visible",
        "adapter_coverage_missing",
        "material_snapshot_mismatch",
        "media_decode_preflight_failed",
    }
)


@dataclass
class Stage6Error(RuntimeError):
    code: str
    message: str
    scene_id: str | None = None
    slot_id: str | None = None
    event_id: str | None = None
    anchor_id: str | None = None
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.code not in STAGE6_ERROR_CODES:
            raise ValueError(f"unknown Stage6 error code: {self.code}")
        super().__init__(f"{self.code} | {self.message}")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "error_code": self.code,
            "detail": self.message,
        }
        if self.scene_id is not None:
            payload["scene_id"] = self.scene_id
        if self.slot_id is not None:
            payload["slot_id"] = self.slot_id
        if self.event_id is not None:
            payload["event_id"] = self.event_id
        if self.anchor_id is not None:
            payload["anchor_id"] = self.anchor_id
        if self.details:
            payload["details"] = self.details
        return payload

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
    duration_frames: int = Field(default=0, ge=0)

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


class ParameterFrameSequence(Contract):
    """A human-approved set of complete parameter-page keyframes."""

    sequence_id: str = Field(min_length=1)
    base_asset_id: str = Field(min_length=1)
    stage_asset_id: str = Field(min_length=1)
    final_asset_id: str = Field(min_length=1)
    required_field_labels: list[str] = Field(min_length=1)
    callout_text: str = Field(min_length=1)
    callout_reveal_frames: int = Field(default=10, ge=1, le=90)


class EditorFlowSequence(Contract):
    """A fixed editor page and modal, activated by word-level anchors."""

    sequence_id: str = Field(min_length=1)
    page_asset_id: str = Field(min_length=1)
    modal_asset_id: str = Field(min_length=1)
    focus_anchor_id: str = Field(min_length=1)
    modal_anchor_id: str = Field(min_length=1)
    focus_x: float = Field(ge=0.0, le=1.0)
    focus_y: float = Field(ge=0.0, le=1.0)
    focus_w: float = Field(gt=0.0, le=1.0)
    focus_h: float = Field(gt=0.0, le=1.0)
    lens_zoom: float = Field(default=2.15, ge=1.2, le=4.0)
    reveal_frames: int = Field(default=10, ge=4, le=45)


class GalleryItem(Contract):
    """One visual item whose appearance is locked to a spoken phrase."""

    asset_id: str = Field(min_length=1)
    phrase: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)


class ShotPlan(Contract):
    shot_id: str
    scene_id: str | None = None
    scene_kind: str | None = None
    track: Literal["base", "overlay"] = "base"
    beat_ids: list[str] = Field(min_length=1)
    start: TimeRef
    end: TimeRef
    template: str
    asset_bindings: dict[str, str] = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    cue_bindings: list[CueBinding] = Field(default_factory=list)
    energy: Literal["low", "medium", "high"] = "medium"
    motion: Literal[
        "none",
        "fade_in",
        "fade_out",
        "scale_in",
        "scale_out",
        "image_pan_scan",
        "detail_push_in",
        "result_reveal",
        "full_bleed_to_safe_card",
        "page_turn_3d",
        "card_flip_3d",
        "paper_curl_flip",
        "spring_card_pop",
        "brand_breath",
        "film_strip",
        "grid_reveal",
        "vertical_scroll",
        "before_after",
        "slide_gallery",
        "card_stack",
        "light_sweep",
    ] = "none"
    transition_in: TransitionIn = Field(default_factory=TransitionIn)
    evidence_policy: str = "source_pixels_visible"
    long_hold_reason: Literal["reading", "appreciation", "pause"] | None = None
    overlay_layout: OverlayLayout | None = None
    parameter_sequence: ParameterFrameSequence | None = None
    editor_flow_sequence: EditorFlowSequence | None = None
    gallery_items: list[GalleryItem] = Field(default_factory=list)

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
        if self.parameter_sequence is not None and self.template != "ui_params_focus":
            raise ValueError("parameter frame sequences require ui_params_focus")
        if self.editor_flow_sequence is not None and self.template != "editor_interaction":
            raise ValueError("editor flow sequences require editor_interaction")
        if self.motion in {"slide_gallery", "card_stack"} and len(self.asset_bindings) < 2:
            raise ValueError(f"{self.motion} requires at least two asset bindings")
        if self.gallery_items:
            binding_ids = set(self.asset_bindings.values())
            missing = [item.asset_id for item in self.gallery_items if item.asset_id not in binding_ids]
            if missing:
                raise ValueError(f"gallery items must reference bound assets: {missing}")
        return self


class VisualPlan(VersionedContract):
    case_id: str
    timing_lock_sha256: str | None = None
    action_scene_plan_sha256: str | None = None
    shots: list[ShotPlan] = Field(min_length=1)

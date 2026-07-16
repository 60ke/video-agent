from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from .base import Contract, VersionedContract


class EvidenceClass(str, Enum):
    SOURCE = "E0_source_evidence"
    FAITHFUL = "E1_faithful_derivative"
    SEMANTIC = "E2_semantic_derivative"
    DECORATIVE = "E3_decorative"


class DeriveKind(str, Enum):
    CROP_AND_REFRAME = "crop_and_reframe"
    RESULT_DETAIL_CROP = "result_detail_crop"
    RESULT_VERTICAL_LAYOUT = "result_vertical_layout"
    RESULT_COLLECTION = "result_collection"
    CANVAS_EXTEND = "canvas_extend"
    SITE_HOME_KEYFRAME = "site_home_keyframe"
    SITE_FEATURE_ENTRY_KEYFRAME = "site_feature_entry_keyframe"
    LOGO_ISOLATE_SEMANTIC = "logo_isolate_semantic"
    BRAND_IP_SUBTITLE_BREAK = "brand_ip_subtitle_break"
    IDENTITY_TO_SYSTEM_TRANSITION = "identity_to_system_transition"
    TEXT_VISUAL_BREAK = "text_visual_break"
    PARAMETER_CALLOUT_SEQUENCE = "parameter_callout_sequence"
    VIDEO_SAFE_RELAYOUT = "video_safe_relayout"
    RESULT_TO_REFERENCE_MOCK = "result_to_reference_mock"
    LOGO_TO_REFERENCE_BOARD = "logo_to_reference_board"
    RESULT_TO_APPLICATION = "result_to_application"
    RESULT_TO_FLAT_PLAN = "result_to_flat_plan"
    RESULT_TO_EDIT_STATE = "result_to_edit_state"
    RESULT_TO_VARIATION = "result_to_variation"
    CONTEXTUAL_RESULT_FILL = "contextual_result_fill"
    GALLERY_PREVIEW = "gallery_preview"
    RESULT_TO_EDITOR_COMPOSITE = "result_to_editor_composite"


class NormalizedRect(Contract):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def inside_source(self) -> "NormalizedRect":
        if self.x + self.w > 1.000001 or self.y + self.h > 1.000001:
            raise ValueError("normalized rectangle exceeds source bounds")
        return self


class VisualAnchor(Contract):
    anchor_id: str
    label: str
    role: str
    intent: str = "focus"
    rect: NormalizedRect
    panel_rect: NormalizedRect | None = None
    source: Literal["cdp", "filename", "vision", "human", "derived"] = "cdp"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AssetQuality(Contract):
    status: Literal["unreviewed", "machine_checked", "human_approved", "rejected"] = "unreviewed"
    readable: bool | None = None
    checks: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None


class Provenance(Contract):
    origin: str
    parent_asset_ids: list[str] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    prompt_sha256: str | None = None
    response_id: str | None = None


class Asset(Contract):
    asset_id: str = Field(pattern=r"^asset_[a-z0-9_]+$")
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: Literal["image", "video", "audio"] = "image"
    filename: str
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    semantic_path: list[str] = Field(default_factory=list)
    role: str
    production_eligible: bool = True
    evidence_class: EvidenceClass
    claims: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    identity_group: str | None = None
    visual_anchors: list[VisualAnchor] = Field(default_factory=list)
    quality: AssetQuality = Field(default_factory=AssetQuality)
    provenance: Provenance
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def evidence_claim_boundary(self) -> "Asset":
        if self.evidence_class in {EvidenceClass.SEMANTIC, EvidenceClass.DECORATIVE} and self.claims:
            raise ValueError("E2/E3 assets cannot support factual claims")
        return self


class AssetCatalog(VersionedContract):
    catalog_id: str
    generated_at: str
    source_root: str
    assets: list[Asset]
    source_catalog_sha256: str | None = None
    warnings: list[str] = Field(default_factory=list)


class DerivedAssetRequest(Contract):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    source_asset_id: str
    related_asset_ids: list[str] = Field(default_factory=list)
    derive_kind: DeriveKind
    instruction: str = ""
    output_role: str = "derived_image"
    semantic_path: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    purpose: str = "visual_density"
    beat_id: str | None = None
    preferred_start_frame: int | None = Field(default=None, ge=0)
    preferred_end_frame: int | None = Field(default=None, gt=0)
    scene_id: str | None = None
    semantic_phrase: str | None = None
    target_orientation: Literal["landscape", "portrait", "square"] | None = None
    preserve: list[str] = Field(default_factory=list)
    relationship_id: str | None = None

    @model_validator(mode="after")
    def validate_preferred_window(self) -> "DerivedAssetRequest":
        if (
            self.preferred_start_frame is not None
            and self.preferred_end_frame is not None
            and self.preferred_end_frame <= self.preferred_start_frame
        ):
            raise ValueError("preferred materialization window must have positive duration")
        if self.source_asset_id in self.related_asset_ids:
            raise ValueError("source_asset_id must not be repeated in related_asset_ids")
        return self


class MaterializationPlan(VersionedContract):
    case_id: str
    requests: list[DerivedAssetRequest] = Field(default_factory=list)

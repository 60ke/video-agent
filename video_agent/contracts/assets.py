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
    CANVAS_EXTEND = "canvas_extend"
    SITE_HOME_KEYFRAME = "site_home_keyframe"
    SITE_FEATURE_ENTRY_KEYFRAME = "site_feature_entry_keyframe"
    SITE_PARAMS_KEYFRAME = "site_params_keyframe"
    LOGO_ISOLATE_SEMANTIC = "logo_isolate_semantic"
    BRAND_IP_SUBTITLE_BREAK = "brand_ip_subtitle_break"
    IDENTITY_TO_SYSTEM_TRANSITION = "identity_to_system_transition"


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
    status: Literal["unreviewed", "machine_checked", "vision_verified", "human_approved", "rejected"] = "unreviewed"
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
    derive_kind: DeriveKind
    instruction: str = ""
    output_role: str = "derived_image"
    semantic_path: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class MaterializationPlan(VersionedContract):
    case_id: str
    requests: list[DerivedAssetRequest] = Field(default_factory=list)

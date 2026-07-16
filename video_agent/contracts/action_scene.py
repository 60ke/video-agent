from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .assets import DerivedAssetRequest
from .base import Contract, VersionedContract
from .visual import TimeRef


SceneKind = Literal[
    "site_home",
    "feature_entry",
    "parameter_input",
    "result_detail",
    "result_gallery",
    "result_gallery_summary",
    "reference_input",
    "reference_to_result",
    "result_to_flat_plan",
    "editor_workspace",
    "editor_before_after",
    "brand_closing",
    "light_sweep_fallback",
]

NarrativeRole = Literal["opening", "body", "closing"]
VisualPurpose = Literal[
    "product_overview",
    "feature_navigation",
    "parameter_operation",
    "single_result_evidence",
    "multi_result_evidence",
    "causal_evidence",
    "editor_operation",
    "abstract_bridge",
    "brand_close",
]


class SceneGalleryItem(Contract):
    asset_id: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)


class ActionScene(Contract):
    scene_id: str = Field(pattern=r"^scene_[A-Za-z0-9_-]+$")
    scene_kind: SceneKind
    narrative_role: NarrativeRole
    visual_purpose: VisualPurpose
    beat_ids: list[str] = Field(min_length=1)
    semantic_phrase: str = Field(min_length=1)
    start: TimeRef
    end: TimeRef
    feature_path: list[str] = Field(default_factory=list)
    asset_terms: list[str] = Field(default_factory=list)
    asset_bindings: dict[str, str] = Field(default_factory=dict)
    gallery_items: list[SceneGalleryItem] = Field(default_factory=list)
    derivation_request_ids: list[str] = Field(default_factory=list)
    relationship_group_id: str | None = None
    relationship_kind: str | None = None
    fallback_policy: Literal["exact", "derive_or_fallback", "light_sweep"] = "exact"

    @model_validator(mode="after")
    def validate_scene_assets(self) -> "ActionScene":
        binding_ids = set(self.asset_bindings.values())
        missing = [item.asset_id for item in self.gallery_items if item.asset_id not in binding_ids]
        if missing:
            raise ValueError(f"scene gallery items must reference bound assets: {missing}")
        if self.scene_kind == "result_gallery" and len(self.gallery_items) < 2:
            raise ValueError("result_gallery requires at least two word-anchored items")
        if self.scene_kind == "result_gallery":
            asset_ids = [item.asset_id for item in self.gallery_items]
            anchor_ids = [item.anchor_id for item in self.gallery_items]
            if len(set(asset_ids)) != len(asset_ids):
                raise ValueError("result_gallery items must use distinct assets")
            if len(set(anchor_ids)) != len(anchor_ids):
                raise ValueError("result_gallery items must use distinct spoken-phrase anchors")
        if self.scene_kind in {"reference_to_result", "result_to_flat_plan", "editor_before_after"}:
            required = {"input", "output"}
            if set(self.asset_bindings) != required:
                raise ValueError(f"{self.scene_kind} requires input and output asset bindings")
        purposes_by_kind = {
            "site_home": {"product_overview"},
            "feature_entry": {"feature_navigation"},
            "parameter_input": {"parameter_operation"},
            "result_detail": {"single_result_evidence"},
            "result_gallery": {"multi_result_evidence"},
            "result_gallery_summary": {"multi_result_evidence"},
            "reference_input": {"causal_evidence"},
            "reference_to_result": {"causal_evidence"},
            "result_to_flat_plan": {"causal_evidence"},
            "editor_workspace": {"editor_operation"},
            "editor_before_after": {"editor_operation", "causal_evidence"},
            "brand_closing": {"brand_close"},
            "light_sweep_fallback": {"abstract_bridge", "brand_close"},
        }
        if self.visual_purpose not in purposes_by_kind[self.scene_kind]:
            raise ValueError(
                f"scene kind {self.scene_kind} cannot satisfy visual purpose {self.visual_purpose}"
            )
        if self.scene_kind == "brand_closing" and self.narrative_role != "closing":
            raise ValueError("brand_closing must be a closing scene")
        if self.visual_purpose == "brand_close" and self.narrative_role != "closing":
            raise ValueError("brand_close visual purpose must be a closing scene")
        if not self.asset_bindings and not self.derivation_request_ids:
            raise ValueError("action scene requires assets or a derivation request")
        return self


class ActionScenePlan(VersionedContract):
    case_id: str
    timing_lock_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    scenes: list[ActionScene] = Field(min_length=1)
    derivation_requests: list[DerivedAssetRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request_references(self) -> "ActionScenePlan":
        request_ids = {request.request_id for request in self.derivation_requests}
        if len(request_ids) != len(self.derivation_requests):
            raise ValueError("action scene derivation request IDs must be unique")
        unknown = {
            request_id
            for scene in self.scenes
            for request_id in scene.derivation_request_ids
            if request_id not in request_ids
        }
        if unknown:
            raise ValueError(f"action scenes reference unknown derivation requests: {sorted(unknown)}")
        return self

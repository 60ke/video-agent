from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import DomainValidationError, V4Contract, ValidationIssue


SlotResolveStatus = Literal["resolved_asset", "resolved_group_member", "resolved_no_asset"]
RankMode = Literal["single", "deterministic_weighted", "semantic_ranked"]
SelectionScope = Literal["independent", "dependency_reuse", "group_binding", "configured"]
GapAction = Literal["fail_missing_source", "fail_missing_config", "derive", "resolve_no_asset"]
DerivationStatus = Literal["pending", "signature_hit", "generated", "registered", "failed"]
MaterialGapReason = Literal[
    "missing_source_asset",
    "missing_configured_asset",
    "no_candidate_asset",
    "incomplete_asset_group",
    "relation_not_bound_to_input",
    "claim_evidence_unsatisfied",
    "no_asset_transition",
    "missing_derivation_capability",
]


class CandidateSummary(V4Contract):
    asset_ref: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    module: str | None = None
    category_path: list[str] = Field(default_factory=list)
    asset_role: str = Field(min_length=1)
    case_label: str | None = None
    industry: str | None = None
    description: str | None = None
    orientation: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    evidence_class: str = Field(min_length=1)
    claims: list[str] = Field(default_factory=list)


class SelectionDecision(V4Contract):
    decision_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    query_contract: dict
    candidate_asset_refs: list[str] = Field(default_factory=list)
    candidate_group_refs: list[str] = Field(default_factory=list)
    hard_filter_counts: dict[str, int] = Field(default_factory=dict)
    rank_mode: RankMode
    selection_scope: SelectionScope
    semantic_requirement: str | None = None
    seed_material: str = Field(min_length=1)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    selected_asset_ref: str | None = None
    selected_group_ref: str | None = None
    rejected_reasons: list[str] = Field(default_factory=list)


class MaterialGap(V4Contract):
    scene_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    category_id: str | None = None
    asset_role: str = Field(min_length=1)
    source_variant: str = Field(min_length=1)
    required_group_type: str | None = None
    required_pattern_id: str | None = None
    required_member_key: str | None = None
    upstream_asset_refs: list[str] = Field(default_factory=list)
    claim_requirements: list[str] = Field(default_factory=list)
    reason_code: MaterialGapReason
    derivation_allowed: bool


class RequiredGroupSpec(V4Contract):
    group_type: str = Field(min_length=1)
    pattern_id: str = Field(min_length=1)
    member_key: str = Field(min_length=1)


class DerivationNarrativeContext(V4Contract):
    scene_text: str = Field(min_length=1)
    anchor_phrase: str = Field(min_length=1)
    previous_scene_summary: str | None = None
    next_scene_summary: str | None = None


class DerivationRequest(V4Contract):
    """Stage 4 → Stage 5 request shape. Final capability/signature live on PreparedDerivation."""

    request_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    derivation_type: str = Field(min_length=1)
    category_id: str | None = None
    target_asset_role: str = Field(min_length=1)
    required_group: RequiredGroupSpec | None = None
    parent_asset_refs: list[str] = Field(default_factory=list)
    context_asset_refs: list[str] = Field(default_factory=list)
    narrative_context: DerivationNarrativeContext | None = None
    target_orientation: str | None = None
    evidence_ceiling: str = Field(min_length=1)
    status: DerivationStatus = "pending"


class GapPolicyRule(V4Contract):
    source_kind: str = Field(min_length=1)
    asset_role: str = Field(min_length=1)
    pattern_id: str | None = None
    action: GapAction


class SemanticRankerConfig(V4Contract):
    enabled: bool = False
    trigger: Literal["explicit_semantic_requirement_only"] = "explicit_semantic_requirement_only"


class Stage4SelectionConfig(V4Contract):
    schema_version: int = Field(ge=1)
    profile_id: str = Field(min_length=1)
    semantic_ranker: SemanticRankerConfig = Field(default_factory=SemanticRankerConfig)
    weights: dict[str, float] = Field(default_factory=dict)
    gap_policies: list[GapPolicyRule] = Field(default_factory=list)
    requires_stage5_registry: bool = True


class ResolvedSlot(V4Contract):
    slot_id: str = Field(min_length=1)
    status: SlotResolveStatus
    asset_ref: str | None = None
    group_ref: str | None = None
    member_key: str | None = None
    selection_decision_id: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> ResolvedSlot:
        if self.status == "resolved_no_asset":
            if self.asset_ref is not None or self.group_ref is not None:
                raise ValueError("resolved_no_asset must not carry asset/group refs")
            return self
        if self.status == "resolved_asset":
            if not self.asset_ref:
                raise ValueError("resolved_asset requires asset_ref")
            return self
        if self.status == "resolved_group_member":
            if not self.asset_ref or not self.group_ref or not self.member_key:
                raise ValueError("resolved_group_member requires asset_ref, group_ref, member_key")
        return self


class ResolvedSceneAssets(V4Contract):
    scene_id: str = Field(min_length=1)
    inputs: dict[str, str] = Field(default_factory=dict)
    slots: list[ResolvedSlot]
    outputs: dict[str, str] = Field(default_factory=dict)


class ResolvedAssetPlan(V4Contract):
    schema_version: int = Field(ge=1)
    run_seed: str = Field(min_length=1)
    scene_plan_sha256: str = Field(min_length=1)
    repository_base_revision: int = Field(ge=0)
    pre_run_repository_fingerprint: str = Field(min_length=1)
    used_assets_snapshot_id: str = Field(min_length=1)
    post_run_repository_revision: int = Field(ge=0)
    post_run_repository_fingerprint: str = Field(min_length=1)
    registry_snapshot_id: str = Field(min_length=1)
    group_bindings: dict[str, str] = Field(default_factory=dict)
    scenes: list[ResolvedSceneAssets] = Field(min_length=1)
    selection_decisions: list[SelectionDecision] = Field(default_factory=list)
    material_gaps: list[MaterialGap] = Field(default_factory=list)
    derivation_requests: list[DerivationRequest] = Field(default_factory=list)


def validate_resolved_asset_plan(plan: ResolvedAssetPlan) -> None:
    issues: list[ValidationIssue] = []
    scene_ids = [scene.scene_id for scene in plan.scenes]
    if len(scene_ids) != len(set(scene_ids)):
        issues.append(ValidationIssue(code="duplicate_scene", path="scenes", message="scene_id must be unique"))
    for alias, group_ref in plan.group_bindings.items():
        if not group_ref.startswith("group://"):
            issues.append(
                ValidationIssue(
                    code="invalid_group_binding",
                    path=f"group_bindings.{alias}",
                    message="group binding must be a group_ref",
                )
            )
    if issues:
        raise DomainValidationError("ResolvedAssetPlan", issues)

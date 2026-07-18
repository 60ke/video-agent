from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .assets import EvidenceClass, SourceKind
from .common import V4Contract


WebsiteTruthPolicy = Literal["forbidden", "faithful_only", "allowed"]
DerivationExecutorKind = Literal["gpt_image", "deterministic", "composite"]
OrientationName = Literal["portrait", "landscape", "square"]
SfxConflictAction = Literal["keep", "attenuate", "suppress"]
SfxSyncPoint = Literal["onset", "peak", "offset"]
AnimatedInputPolicy = Literal["preserve_without_extra_breath", "allow_brand_breath", "reject"]
VoiceResolveMode = Literal["fixed", "auto"]


class CapabilityEntry(V4Contract):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = ""
    enabled: bool = True
    schema_version: int = Field(default=1, ge=1)
    handler: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class CategoryEntry(CapabilityEntry):
    module: str = Field(min_length=1)
    category_path: list[str] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    scope_eligible: bool = True

    @model_validator(mode="after")
    def validate_hierarchy(self) -> "CategoryEntry":
        if any(not segment.strip() or "/" in segment for segment in self.category_path):
            raise ValueError("category_path segments must be non-empty and cannot contain slash")
        expected = "/".join([self.module, *self.category_path])
        if self.id != expected:
            raise ValueError(f"category id must match module/category_path: {expected}")
        if len(self.aliases) != len(set(self.aliases)):
            raise ValueError("category aliases must be unique within an entry")
        return self


class AssetRoleEntry(CapabilityEntry):
    requires_category: bool = True
    allowed_source_kinds: list[SourceKind] = Field(min_length=1)
    default_derived_evidence: EvidenceClass | None = None
    allowed_parent_roles: list[str] = Field(default_factory=list)
    allowed_group_types: list[str] = Field(default_factory=list)
    allowed_derivation_ids: list[str] = Field(default_factory=list)
    display_capability_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_policy(self) -> "AssetRoleEntry":
        if len(self.allowed_source_kinds) != len(set(self.allowed_source_kinds)):
            raise ValueError("allowed_source_kinds must be unique")
        if self.default_derived_evidence == EvidenceClass.SOURCE:
            raise ValueError("derived assets cannot default to E0 evidence")
        if self.default_derived_evidence is not None and SourceKind.DERIVED not in self.allowed_source_kinds:
            raise ValueError("default_derived_evidence requires derived in allowed_source_kinds")
        return self


class ClaimEntry(CapabilityEntry):
    required_evidence_classes: list[EvidenceClass] = Field(min_length=1)

    @field_validator("required_evidence_classes")
    @classmethod
    def validate_evidence_classes(cls, values: list[EvidenceClass]) -> list[EvidenceClass]:
        if len(values) != len(set(values)):
            raise ValueError("required_evidence_classes must be unique")
        if any(value in {EvidenceClass.SEMANTIC, EvidenceClass.DECORATIVE} for value in values):
            raise ValueError("factual claims cannot accept E2/E3 evidence")
        return values


class GroupTypeEntry(CapabilityEntry):
    ordered: bool = False
    allowed_member_roles: list[str] = Field(default_factory=list)


class RelationPatternMember(V4Contract):
    member_key: str = Field(min_length=1)
    asset_role: str = Field(min_length=1)
    required: bool = True
    order: int = Field(ge=1)


class RelationPatternEntry(CapabilityEntry):
    group_type: str = Field(min_length=1)
    members: list[RelationPatternMember] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_members(self) -> "RelationPatternEntry":
        keys = [member.member_key for member in self.members]
        if len(keys) != len(set(keys)):
            raise ValueError("relation pattern member_key values must be unique")
        orders = [member.order for member in self.members]
        if len(orders) != len(set(orders)):
            raise ValueError("relation pattern order values must be unique")
        if sorted(orders) != list(range(1, len(self.members) + 1)):
            raise ValueError("relation pattern orders must be contiguous from 1")
        return self


class RegistryDocument(V4Contract):
    registry_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[CapabilityEntry]


class CategoryRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^category$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[CategoryEntry]


class AssetRoleRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^asset_role$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[AssetRoleEntry]


class ClaimRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^claim$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[ClaimEntry]


class GroupTypeRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^group_type$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[GroupTypeEntry]


class RelationPatternRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^relation_pattern$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[RelationPatternEntry]


class DerivationCapabilities(V4Contract):
    version: str = Field(min_length=1)
    executor_kind: DerivationExecutorKind
    input_roles: list[str] = Field(default_factory=list)
    context_roles: list[str] = Field(default_factory=list)
    output_roles: list[str] = Field(min_length=1)
    allowed_group_patterns: list[str] = Field(default_factory=list)
    minimum_parents: int = Field(ge=0)
    maximum_parents: int | None = Field(default=None, ge=0)
    output_evidence_class: str = Field(min_length=1)
    prompt_template: str | None = None
    prompt_contract_version: str | None = None
    provider_profile: str | None = None
    supports_orientations: list[OrientationName] = Field(min_length=1)
    website_truth_policy: WebsiteTruthPolicy

    @model_validator(mode="after")
    def validate_parent_bounds(self) -> "DerivationCapabilities":
        if self.maximum_parents is not None and self.maximum_parents < self.minimum_parents:
            raise ValueError("maximum_parents must be >= minimum_parents")
        if self.minimum_parents == 0 and self.input_roles:
            raise ValueError("zero-parent capabilities must not declare input_roles")
        if self.minimum_parents > 0 and not self.input_roles:
            raise ValueError("parent-requiring capabilities must declare input_roles")
        if len(self.output_roles) != len(set(self.output_roles)):
            raise ValueError("output_roles must be unique")
        if len(self.supports_orientations) != len(set(self.supports_orientations)):
            raise ValueError("supports_orientations must be unique")
        return self


class DerivationEntry(CapabilityEntry):
    capabilities: DerivationCapabilities  # type: ignore[assignment]


class DerivationRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^derivation$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[DerivationEntry]


class EffectCapabilities(V4Contract):
    visual_structures: list[str] = Field(min_length=1)
    asset_roles: list[str] = Field(min_length=1)
    media_types: list[str] = Field(min_length=1)
    orientations: list[OrientationName] = Field(min_length=1)
    minimum_items: int = Field(ge=0, default=1)
    maximum_items: int | None = Field(default=None, ge=0)
    supports_mixed_orientation: bool = False
    animated_input_policy: AnimatedInputPolicy = "preserve_without_extra_breath"
    continuity_scope: str = Field(min_length=1)
    minimum_scene_frames: int = Field(ge=1)
    readable_settle_frames: int = Field(ge=0, default=0)
    requires_readable_hold: bool = False
    event_bindings: list[str] = Field(default_factory=list)
    fallback_effect_ids: list[str] = Field(default_factory=list)
    weight: int = Field(ge=0, default=100)

    @model_validator(mode="after")
    def validate_item_bounds(self) -> "EffectCapabilities":
        if self.maximum_items is not None and self.maximum_items < self.minimum_items:
            raise ValueError("maximum_items must be >= minimum_items")
        if len(self.visual_structures) != len(set(self.visual_structures)):
            raise ValueError("visual_structures must be unique")
        if len(self.asset_roles) != len(set(self.asset_roles)):
            raise ValueError("asset_roles must be unique")
        return self


class EffectEntry(CapabilityEntry):
    capabilities: EffectCapabilities  # type: ignore[assignment]


class EffectRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^effect$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[EffectEntry]


class SfxCapabilities(V4Contract):
    relative_path: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    gain_db: float
    trim_start_ms: int = Field(ge=0, default=0)
    max_duration_ms: int | None = Field(default=None, ge=1)
    fade_in_ms: int = Field(ge=0, default=0)
    fade_out_ms: int = Field(ge=0, default=0)
    priority: int = Field(ge=0)
    sync_point: SfxSyncPoint
    sync_offset_ms: int = 0
    allowed_event_intents: list[str] = Field(default_factory=list)
    forbidden_event_intents: list[str] = Field(default_factory=list)
    source_kinds: list[str] = Field(default_factory=list)
    alternate_sfx_ids: list[str] = Field(default_factory=list)
    sample_rate: int = Field(ge=1, default=48000)
    sample_width_bits: int = Field(ge=8, default=16)
    channels: int = Field(ge=1, default=2)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or normalized.startswith("../") or "/../" in f"/{normalized}/":
            raise ValueError("SFX path must be a repo-relative POSIX path without parent traversal")
        if ":" in normalized.split("/")[0]:
            raise ValueError("SFX path must not be an absolute Windows path")
        return normalized


class SfxEntry(CapabilityEntry):
    capabilities: SfxCapabilities  # type: ignore[assignment]


class SfxRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^sfx$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[SfxEntry]


class SfxProfileCapabilities(V4Contract):
    min_interval_ms: int = Field(ge=0)
    window_ms: int = Field(ge=1)
    window_event_budget: int = Field(ge=0)
    same_kind_cooldown_ms: int = Field(ge=0)
    priority_budgets: dict[str, int] = Field(default_factory=dict)
    conflict_action: SfxConflictAction = "suppress"
    prefer_operation_semantic: bool = True
    default_sfx_catalog_profile: str | None = None


class SfxProfileEntry(CapabilityEntry):
    capabilities: SfxProfileCapabilities  # type: ignore[assignment]


class SfxProfileRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^sfx_profile$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[SfxProfileEntry]


class VoiceCapabilities(V4Contract):
    provider: str = Field(min_length=1)
    provider_voice_ref: str = Field(min_length=1)
    language: str = Field(min_length=1)
    traits: list[str] = Field(default_factory=list)
    default_speed: float = Field(gt=0)
    supported_emotions: list[str] = Field(default_factory=list)
    resolve_mode: VoiceResolveMode = "fixed"
    subtitle_type: str = Field(min_length=1, default="zh")
    priority: int = Field(ge=0, default=100)

    @field_validator("provider_voice_ref")
    @classmethod
    def reject_literal_secrets(cls, value: str) -> str:
        lowered = value.casefold()
        if any(token in lowered for token in ("apikey", "api_key", "secret", "token=")):
            raise ValueError("provider_voice_ref must be a config reference, not a secret literal")
        return value


class VoiceEntry(CapabilityEntry):
    capabilities: VoiceCapabilities  # type: ignore[assignment]


class VoiceRegistryDocument(V4Contract):
    registry_id: str = Field(pattern=r"^voice$")
    version: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    entries: list[VoiceEntry]


RegistryDocumentType = (
    RegistryDocument
    | CategoryRegistryDocument
    | AssetRoleRegistryDocument
    | ClaimRegistryDocument
    | GroupTypeRegistryDocument
    | RelationPatternRegistryDocument
    | DerivationRegistryDocument
    | EffectRegistryDocument
    | SfxRegistryDocument
    | SfxProfileRegistryDocument
    | VoiceRegistryDocument
)


class FrozenRegistryDocument(V4Contract):
    registry_id: str
    version: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    document: dict[str, Any]


class FrozenRegistrySnapshot(V4Contract):
    snapshot_id: str = Field(pattern=r"^registry-snapshot://sha256/[a-f0-9]{64}$")
    created_at: datetime
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    registries: list[FrozenRegistryDocument]

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_unique_registries(self) -> "FrozenRegistrySnapshot":
        ids = [item.registry_id for item in self.registries]
        if len(ids) != len(set(ids)):
            raise ValueError("frozen registry IDs must be unique")
        return self

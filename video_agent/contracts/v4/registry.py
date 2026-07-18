from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from .assets import EvidenceClass, SourceKind
from .common import V4Contract


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


RegistryDocumentType = (
    RegistryDocument
    | CategoryRegistryDocument
    | AssetRoleRegistryDocument
    | ClaimRegistryDocument
    | GroupTypeRegistryDocument
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

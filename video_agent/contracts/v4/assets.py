from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
import re

from pydantic import Field, field_validator, model_validator

from .common import V4Contract


_ASSET_REF_PATTERN = r"^asset://A[0-9]{4,}$"
_GROUP_REF_PATTERN = r"^group://G[0-9]{4,}$"
_SHA256_PATTERN = r"^[a-f0-9]{64}$"


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class EvidenceClass(str, Enum):
    SOURCE = "E0_source_evidence"
    FAITHFUL = "E1_faithful_derivative"
    SEMANTIC = "E2_semantic_derivative"
    DECORATIVE = "E3_decorative"


class SourceKind(str, Enum):
    ORIGINAL = "original"
    DERIVED = "derived"


class AssetStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class Orientation(str, Enum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"
    SQUARE = "square"


class AssetLineage(V4Contract):
    parent_asset_refs: list[str] = Field(min_length=1)
    derivation_type: str = Field(min_length=1)
    executor_id: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None
    prompt_template_version: str | None = None
    prompt_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    parameters_sha256: str = Field(pattern=_SHA256_PATTERN)
    derivation_signature: str = Field(pattern=_SHA256_PATTERN)
    created_at: datetime

    @field_validator("parent_asset_refs")
    @classmethod
    def validate_parent_refs(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("lineage parent_asset_refs must be unique")
        for value in values:
            if not re.fullmatch(_ASSET_REF_PATTERN, value):
                raise ValueError(f"invalid parent asset reference: {value}")
        return values

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _require_timezone(value)


class AssetRecord(V4Contract):
    asset_ref: str = Field(pattern=_ASSET_REF_PATTERN)
    filename: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    content_sha256: str = Field(pattern=_SHA256_PATTERN)
    media_type: str = Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")
    module: str | None = None
    category_id: str | None = None
    category_path: list[str] = Field(default_factory=list)
    asset_role: str = Field(min_length=1)
    case_label: str | None = None
    industry: str | None = None
    description: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    orientation: Orientation
    animated: bool = False
    source_kind: SourceKind
    origin_type: str = Field(min_length=1)
    evidence_class: EvidenceClass
    claims: list[str] = Field(default_factory=list)
    status: AssetStatus = AssetStatus.ACTIVE
    superseded_by: str | None = Field(default=None, pattern=_ASSET_REF_PATTERN)
    lineage: AssetLineage | None = None
    created_at: datetime

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("object_key must use normalized POSIX syntax")
        path = PurePosixPath(value)
        if value.startswith("/") or path.is_absolute() or ".." in path.parts or ":" in path.parts[0]:
            raise ValueError("object_key must be a relative POSIX path without traversal")
        if value != path.as_posix() or value in {"", "."}:
            raise ValueError("object_key must be normalized POSIX syntax")
        return value

    @field_validator("category_path")
    @classmethod
    def validate_category_path(cls, value: list[str]) -> list[str]:
        if any(not segment.strip() or "/" in segment for segment in value):
            raise ValueError("category_path segments must be non-empty and cannot contain slash")
        return value

    @field_validator("claims")
    @classmethod
    def validate_unique_claims(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("asset claims must be unique")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @model_validator(mode="after")
    def validate_domain_invariants(self) -> "AssetRecord":
        if PurePosixPath(self.object_key).name != self.filename:
            raise ValueError("filename must equal the final object_key segment")

        expected_orientation = (
            Orientation.LANDSCAPE
            if self.width > self.height
            else Orientation.PORTRAIT
            if self.height > self.width
            else Orientation.SQUARE
        )
        if self.orientation != expected_orientation:
            raise ValueError(f"orientation must match dimensions: expected {expected_orientation.value}")

        has_category = self.category_id is not None or self.module is not None or bool(self.category_path)
        if has_category:
            if self.category_id is None or self.module is None or not self.category_path:
                raise ValueError("category_id, module and category_path must be present together")
            expected_category = "/".join([self.module, *self.category_path])
            if self.category_id != expected_category:
                raise ValueError(f"category_id does not match module/category_path: {expected_category}")

        if self.source_kind == SourceKind.ORIGINAL and self.lineage is not None:
            raise ValueError("original assets cannot have lineage")
        if self.source_kind == SourceKind.DERIVED and self.lineage is None:
            raise ValueError("derived assets require lineage")
        if self.lineage is not None and self.asset_ref in self.lineage.parent_asset_refs:
            raise ValueError("asset lineage cannot reference the child as a parent")

        if self.evidence_class == EvidenceClass.SOURCE and self.source_kind != SourceKind.ORIGINAL:
            raise ValueError("E0 evidence requires an original asset")
        if self.evidence_class in {EvidenceClass.FAITHFUL, EvidenceClass.SEMANTIC}:
            if self.source_kind != SourceKind.DERIVED:
                raise ValueError("E1/E2 evidence requires a derived asset")
        if self.evidence_class in {EvidenceClass.SEMANTIC, EvidenceClass.DECORATIVE} and self.claims:
            raise ValueError("E2/E3 assets cannot support factual claims")

        if self.status == AssetStatus.ACTIVE and self.superseded_by is not None:
            raise ValueError("active assets cannot set superseded_by")
        if self.status == AssetStatus.SUPERSEDED and self.superseded_by is None:
            raise ValueError("superseded assets require superseded_by")
        if self.superseded_by == self.asset_ref:
            raise ValueError("an asset cannot supersede itself")
        return self


class AssetGroupMember(V4Contract):
    member_key: str = Field(min_length=1)
    asset_role: str = Field(min_length=1)
    asset_ref: str = Field(pattern=_ASSET_REF_PATTERN)
    order: int = Field(ge=1)


class AssetGroup(V4Contract):
    group_ref: str = Field(pattern=_GROUP_REF_PATTERN)
    group_type: str = Field(min_length=1)
    category_id: str = Field(min_length=1)
    members: list[AssetGroupMember] = Field(min_length=1)
    status: AssetStatus = AssetStatus.ACTIVE
    superseded_by: str | None = Field(default=None, pattern=_GROUP_REF_PATTERN)
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _require_timezone(value)

    @model_validator(mode="after")
    def validate_group_invariants(self) -> "AssetGroup":
        member_keys = [member.member_key for member in self.members]
        if len(member_keys) != len(set(member_keys)):
            raise ValueError("asset group member_key values must be unique")
        orders = [member.order for member in self.members]
        if len(orders) != len(set(orders)):
            raise ValueError("asset group order values must be unique")
        if self.status == AssetStatus.ACTIVE and self.superseded_by is not None:
            raise ValueError("active groups cannot set superseded_by")
        if self.status == AssetStatus.SUPERSEDED and self.superseded_by is None:
            raise ValueError("superseded groups require superseded_by")
        if self.superseded_by == self.group_ref:
            raise ValueError("an asset group cannot supersede itself")
        return self

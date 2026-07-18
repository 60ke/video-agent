from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from video_agent.contracts.v4 import (
    AssetGroup,
    AssetGroupMember,
    AssetLineage,
    AssetRecord,
    AssetRepositorySnapshot,
    EvidenceClass,
    Orientation,
    SourceKind,
)


class AssetRepositoryError(RuntimeError):
    pass


class AssetNotFoundError(AssetRepositoryError):
    pass


class AssetConflictError(AssetRepositoryError):
    pass


@dataclass(frozen=True)
class AssetQuery:
    category_ids: tuple[str, ...] = ()
    asset_roles: tuple[str, ...] = ()
    source_kinds: tuple[SourceKind, ...] = ()
    orientations: tuple[Orientation, ...] = ()
    claims: tuple[str, ...] = ()
    active_only: bool = True


@dataclass(frozen=True)
class GroupQuery:
    group_types: tuple[str, ...] = ()
    pattern_ids: tuple[str, ...] = ()
    category_ids: tuple[str, ...] = ()
    member_roles: tuple[str, ...] = ()
    active_only: bool = True


@dataclass(frozen=True)
class AssetDraft:
    filename: str
    object_key: str
    content_sha256: str
    media_type: str
    module: str | None
    category_id: str | None
    category_path: list[str] = field(default_factory=list)
    asset_role: str = ""
    case_label: str | None = None
    industry: str | None = None
    description: str | None = None
    width: int = 0
    height: int = 0
    orientation: Orientation = Orientation.SQUARE
    animated: bool = False
    source_kind: SourceKind = SourceKind.ORIGINAL
    origin_type: str = ""
    evidence_class: EvidenceClass = EvidenceClass.SOURCE
    claims: list[str] = field(default_factory=list)
    lineage: AssetLineage | None = None


@dataclass(frozen=True)
class AssetGroupDraft:
    group_type: str
    pattern_id: str
    category_id: str
    members: list[AssetGroupMember]


class AssetRepository(Protocol):
    def get_asset(self, asset_ref: str, *, include_superseded: bool = True) -> AssetRecord | None: ...
    def query_assets(self, query: AssetQuery) -> list[AssetRecord]: ...
    def register_asset(self, draft: AssetDraft) -> AssetRecord: ...
    def supersede_asset(self, old_ref: str, replacement: AssetDraft) -> AssetRecord: ...
    def find_by_derivation_signature(self, signature: str) -> AssetRecord | None: ...
    def get_group(self, group_ref: str, *, include_superseded: bool = True) -> AssetGroup | None: ...
    def query_groups(self, query: GroupQuery) -> list[AssetGroup]: ...
    def register_group(self, draft: AssetGroupDraft) -> AssetGroup: ...
    def supersede_group(self, old_ref: str, replacement: AssetGroupDraft) -> AssetGroup: ...
    def bind_configured_asset(self, config_key: str, asset_ref: str) -> None: ...
    def validate_configured_asset_binding(self, config_key: str, asset_ref: str) -> AssetRecord: ...
    def configured_asset(self, config_key: str) -> AssetRecord | None: ...
    def freeze(self, asset_refs: list[str], group_refs: list[str]) -> AssetRepositorySnapshot: ...
    def validate_snapshot(self, snapshot: AssetRepositorySnapshot) -> None: ...
    def restore_snapshot(self, snapshot: AssetRepositorySnapshot) -> tuple[list[AssetRecord], list[AssetGroup]]: ...


def asset_draft_from_record(asset: AssetRecord) -> AssetDraft:
    return AssetDraft(
        filename=asset.filename,
        object_key=asset.object_key,
        content_sha256=asset.content_sha256,
        media_type=asset.media_type,
        module=asset.module,
        category_id=asset.category_id,
        category_path=asset.category_path,
        asset_role=asset.asset_role,
        case_label=asset.case_label,
        industry=asset.industry,
        description=asset.description,
        width=asset.width,
        height=asset.height,
        orientation=asset.orientation,
        animated=asset.animated,
        source_kind=asset.source_kind,
        origin_type=asset.origin_type,
        evidence_class=asset.evidence_class,
        claims=asset.claims,
        lineage=asset.lineage,
    )

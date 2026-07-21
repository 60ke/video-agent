from __future__ import annotations

import logging
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


LOGGER = logging.getLogger(__name__)


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
    containing_asset_refs: tuple[str, ...] = ()
    required_member_keys: tuple[str, ...] = ()
    active_only: bool = True


@dataclass(frozen=True)
class ResolutionVisibility:
    """Fixed candidate view: base revision plus the current Run overlay."""

    as_of_revision: int
    extra_asset_refs: tuple[str, ...] = ()
    extra_group_refs: tuple[str, ...] = ()


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


def category_triple_from_id(
    category_id: str | None,
    *,
    fallback_module: str | None = None,
    fallback_category_id: str | None = None,
    fallback_category_path: list[str] | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """Return (category_id, module, category_path) satisfying AssetRecord invariants.

    Prefer an explicit multi-segment category_id. Otherwise reuse a complete
    parent triple. Never return a partial mix (id without path, etc.).
    """
    for candidate in (category_id, fallback_category_id):
        if not candidate:
            continue
        parts = [part.strip() for part in str(candidate).split("/") if part.strip()]
        if len(parts) >= 2:
            normalized = "/".join(parts)
            return normalized, parts[0], parts[1:]
    if fallback_module and fallback_category_path:
        path = [part for part in fallback_category_path if str(part).strip()]
        if path:
            return "/".join([fallback_module, *path]), fallback_module, path
    return None, None, []


@dataclass(frozen=True)
class AssetGroupDraft:
    group_type: str
    pattern_id: str
    category_id: str
    members: list[AssetGroupMember]


class AssetRepository(Protocol):
    def current_revision(self) -> int: ...
    def repository_fingerprint(self, *, as_of_revision: int | None = None) -> str: ...
    def open_resolution_session(self) -> AssetResolutionSession: ...
    def get_asset(
        self,
        asset_ref: str,
        *,
        include_superseded: bool = True,
        visibility: ResolutionVisibility | None = None,
    ) -> AssetRecord | None: ...
    def query_assets(
        self,
        query: AssetQuery,
        *,
        visibility: ResolutionVisibility | None = None,
    ) -> list[AssetRecord]: ...
    def register_asset(self, draft: AssetDraft) -> AssetRecord: ...
    def supersede_asset(self, old_ref: str, replacement: AssetDraft) -> AssetRecord: ...
    def find_by_derivation_signature(
        self,
        signature: str,
        *,
        visibility: ResolutionVisibility | None = None,
    ) -> AssetRecord | None: ...
    def get_group(
        self,
        group_ref: str,
        *,
        include_superseded: bool = True,
        visibility: ResolutionVisibility | None = None,
    ) -> AssetGroup | None: ...
    def query_groups(
        self,
        query: GroupQuery,
        *,
        visibility: ResolutionVisibility | None = None,
    ) -> list[AssetGroup]: ...
    def register_group(self, draft: AssetGroupDraft) -> AssetGroup: ...
    def register_derived_group(
        self,
        *,
        drafts: list[AssetDraft],
        draft_member_keys: list[str],
        reuse_member_refs: dict[str, str],
        group_type: str,
        pattern_id: str,
        category_id: str,
        member_specs: list[tuple[str, str, int]],
    ) -> AssetGroup: ...
    def supersede_group(self, old_ref: str, replacement: AssetGroupDraft) -> AssetGroup: ...
    def bind_configured_asset(self, config_key: str, asset_ref: str) -> None: ...
    def validate_configured_asset_binding(self, config_key: str, asset_ref: str) -> AssetRecord: ...
    def configured_asset(
        self,
        config_key: str,
        *,
        visibility: ResolutionVisibility | None = None,
    ) -> AssetRecord | None: ...
    def freeze(self, asset_refs: list[str], group_refs: list[str]) -> AssetRepositorySnapshot: ...
    def validate_snapshot(self, snapshot: AssetRepositorySnapshot) -> None: ...
    def restore_snapshot(self, snapshot: AssetRepositorySnapshot) -> tuple[list[AssetRecord], list[AssetGroup]]: ...


@dataclass
class AssetResolutionSession:
    """Run-scoped repository view: base revision UNION this Run's registrations."""

    repository: AssetRepository
    base_revision: int
    pre_run_repository_fingerprint: str
    run_created_asset_refs: set[str] = field(default_factory=set)
    run_created_group_refs: set[str] = field(default_factory=set)
    verified_asset_refs: set[str] = field(default_factory=set)
    invalid_asset_refs: set[str] = field(default_factory=set)

    def visibility(self) -> ResolutionVisibility:
        return ResolutionVisibility(
            as_of_revision=self.base_revision,
            extra_asset_refs=tuple(sorted(self.run_created_asset_refs)),
            extra_group_refs=tuple(sorted(self.run_created_group_refs)),
        )

    def get_asset(self, asset_ref: str, *, include_superseded: bool = True) -> AssetRecord | None:
        asset = self.repository.get_asset(
            asset_ref, include_superseded=include_superseded, visibility=self.visibility()
        )
        return asset if asset is not None and self._is_technically_available(asset) else None

    def query_assets(self, query: AssetQuery) -> list[AssetRecord]:
        return [
            asset
            for asset in self.repository.query_assets(query, visibility=self.visibility())
            if self._is_technically_available(asset)
        ]

    def find_by_derivation_signature(self, signature: str) -> AssetRecord | None:
        return self.repository.find_by_derivation_signature(signature, visibility=self.visibility())

    def get_group(self, group_ref: str, *, include_superseded: bool = True) -> AssetGroup | None:
        return self.repository.get_group(
            group_ref, include_superseded=include_superseded, visibility=self.visibility()
        )

    def query_groups(self, query: GroupQuery) -> list[AssetGroup]:
        groups = self.repository.query_groups(query, visibility=self.visibility())
        return [group for group in groups if self._group_is_technically_available(group)]

    def configured_asset(self, config_key: str) -> AssetRecord | None:
        asset = self.repository.configured_asset(config_key, visibility=self.visibility())
        return asset if asset is not None and self._is_technically_available(asset) else None

    def _is_technically_available(self, asset: AssetRecord) -> bool:
        if asset.asset_ref in self.invalid_asset_refs:
            return False
        if asset.asset_ref in self.verified_asset_refs:
            return True
        object_store = getattr(self.repository, "object_store", None)
        if object_store is None:
            self.verified_asset_refs.add(asset.asset_ref)
            return True
        try:
            object_store.verify(asset.object_key, asset.content_sha256)
        except Exception as exc:  # noqa: BLE001 - corrupt repository rows are filtered from candidates.
            self.invalid_asset_refs.add(asset.asset_ref)
            LOGGER.warning(
                "[Stage4][素材完整性] 排除不可用素材 asset_ref=%s object_key=%s error=%s",
                asset.asset_ref,
                asset.object_key,
                exc,
            )
            return False
        self.verified_asset_refs.add(asset.asset_ref)
        return True

    def _group_is_technically_available(self, group: AssetGroup) -> bool:
        for member in group.members:
            asset = self.repository.get_asset(
                member.asset_ref,
                include_superseded=False,
                visibility=self.visibility(),
            )
            if asset is None or not self._is_technically_available(asset):
                return False
        return True

    def register_asset(self, draft: AssetDraft) -> AssetRecord:
        asset = self.repository.register_asset(draft)
        self.run_created_asset_refs.add(asset.asset_ref)
        return asset

    def register_group(self, draft: AssetGroupDraft) -> AssetGroup:
        group = self.repository.register_group(draft)
        self.run_created_group_refs.add(group.group_ref)
        return group

    def register_derived_group(
        self,
        *,
        drafts: list[AssetDraft],
        draft_member_keys: list[str],
        reuse_member_refs: dict[str, str],
        group_type: str,
        pattern_id: str,
        category_id: str,
        member_specs: list[tuple[str, str, int]],
    ) -> AssetGroup:
        group = self.repository.register_derived_group(
            drafts=drafts,
            draft_member_keys=draft_member_keys,
            reuse_member_refs=reuse_member_refs,
            group_type=group_type,
            pattern_id=pattern_id,
            category_id=category_id,
            member_specs=member_specs,
        )
        for member in group.members:
            self.run_created_asset_refs.add(member.asset_ref)
        self.run_created_group_refs.add(group.group_ref)
        return group

    def supersede_asset(self, old_ref: str, replacement: AssetDraft) -> AssetRecord:
        asset = self.repository.supersede_asset(old_ref, replacement)
        self.run_created_asset_refs.add(asset.asset_ref)
        return asset

    def supersede_group(self, old_ref: str, replacement: AssetGroupDraft) -> AssetGroup:
        group = self.repository.supersede_group(old_ref, replacement)
        self.run_created_group_refs.add(group.group_ref)
        return group

    def freeze_used(self, asset_refs: list[str], group_refs: list[str]) -> AssetRepositorySnapshot:
        return self.repository.freeze(asset_refs, group_refs)


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

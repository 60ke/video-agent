from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from video_agent.assets.v4_validation import validate_asset_against_registry, validate_group_against_assets
from video_agent.contracts.v4 import (
    AssetGroup,
    AssetGroupMember,
    AssetLineage,
    AssetRecord,
    AssetStatus,
    EvidenceClass,
    SourceKind,
)
from video_agent.io import sha256_file

from .repository import AssetDraft, AssetGroupDraft, AssetQuery
from .sqlite_repository import SQLiteAssetRepository


class AssetImportError(RuntimeError):
    def __init__(self, message: str, *, orphans: list[str] | None = None) -> None:
        super().__init__(message)
        self.orphans = orphans or []


def import_manifest(repository: SQLiteAssetRepository, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("import manifest schema_version must be 1")

    items = list(manifest.get("assets", []))
    group_items = list(manifest.get("groups", []))
    draft_by_id: dict[str, AssetDraft] = {}
    ordered_ids: list[str] = []
    source_by_id: dict[str, Path] = {}
    lineage_raw_by_id: dict[str, dict[str, Any]] = {}

    for index, item in enumerate(items):
        asset_id = str(item.get("id") or f"asset_{index}")
        if asset_id in draft_by_id:
            raise AssetImportError(f"duplicate import asset id: {asset_id}")
        if asset_id.startswith("asset://"):
            raise AssetImportError(f"import asset id cannot use the repository reference namespace: {asset_id}")
        source = Path(item["source"]).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        info = repository.object_store._inspect_path(  # noqa: SLF001 - preflight without write
            source, item["object_key"], content_sha256=sha256_file(source)
        )
        raw_lineage = item.get("lineage")
        if not raw_lineage and SourceKind(item["source_kind"]) is SourceKind.DERIVED:
            raise AssetImportError(f"derived asset requires lineage: {item.get('object_key')}")
        if raw_lineage:
            lineage_raw_by_id[asset_id] = raw_lineage
        draft = AssetDraft(
            filename=Path(item["object_key"]).name,
            object_key=item["object_key"],
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=item.get("module"),
            category_id=item.get("category_id"),
            category_path=item.get("category_path", []),
            asset_role=item["asset_role"],
            case_label=item.get("case_label"),
            industry=item.get("industry"),
            description=item.get("description"),
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=info.animated,
            source_kind=SourceKind(item["source_kind"]),
            origin_type=item["origin_type"],
            evidence_class=EvidenceClass(item["evidence_class"]),
            claims=item.get("claims", []),
            lineage=None,
        )
        draft_by_id[asset_id] = draft
        ordered_ids.append(asset_id)
        source_by_id[asset_id] = source

    registration_ids = _topological_asset_ids(ordered_ids, lineage_raw_by_id, draft_by_id, repository)
    temp_refs = _synthetic_asset_refs(repository, ordered_ids)
    preflight_assets: dict[str, AssetRecord] = {}
    for asset_id in ordered_ids:
        draft = draft_by_id[asset_id]
        raw_lineage = lineage_raw_by_id.get(asset_id)
        if raw_lineage is not None:
            resolved_parents: list[str] = []
            for parent in raw_lineage["parent_asset_refs"]:
                parent = str(parent)
                if parent in draft_by_id:
                    resolved_parents.append(temp_refs[parent])
                elif parent.startswith("asset://"):
                    if repository.get_asset(parent) is None:
                        raise AssetImportError(f"parent asset not found: {parent}")
                    resolved_parents.append(parent)
                else:
                    raise AssetImportError(f"unresolved lineage parent: {parent}")
            lineage = _lineage_from_raw(raw_lineage, resolved_parents)
            draft = AssetDraft(**{**draft.__dict__, "lineage": lineage})
            draft_by_id[asset_id] = draft
        record = AssetRecord(
            asset_ref=temp_refs[asset_id],
            created_at=datetime.now(timezone.utc),
            status=AssetStatus.ACTIVE,
            superseded_by=None,
            **draft.__dict__,
        )
        validate_asset_against_registry(record, repository.registry)
        preflight_assets[record.asset_ref] = record

    for index, item in enumerate(group_items):
        members = []
        for member in item["members"]:
            member_kind, raw = _group_member_reference(member)
            if member_kind == "asset_id":
                if raw not in temp_refs:
                    raise AssetImportError(f"group member import id not found: {raw}")
                asset_ref = temp_refs[raw]
            else:
                asset_ref = raw
            members.append(
                AssetGroupMember(
                    member_key=member["member_key"],
                    asset_role=member["asset_role"],
                    asset_ref=asset_ref,
                    order=member["order"],
                )
            )
        group = AssetGroup(
            group_ref=f"group://G{index + 1:04d}",
            group_type=item["group_type"],
            pattern_id=item["pattern_id"],
            category_id=item["category_id"],
            members=members,
            status=AssetStatus.ACTIVE,
            superseded_by=None,
            created_at=datetime.now(timezone.utc),
        )
        assets_for_group = dict(preflight_assets)
        for member in members:
            if member.asset_ref not in assets_for_group:
                existing = repository.get_asset(member.asset_ref)
                if existing is None:
                    raise AssetImportError(f"group member missing: {member.asset_ref}")
                assets_for_group[member.asset_ref] = existing
        validate_group_against_assets(group, assets_for_group, repository.registry)

    newly_copied: list[str] = []
    try:
        for asset_id in ordered_ids:
            draft = draft_by_id[asset_id]
            target = repository.object_store.resolve(draft.object_key)
            existed = target.is_file()
            info = repository.object_store.put_file(source_by_id[asset_id], draft.object_key)
            if info.content_sha256 != draft.content_sha256:
                raise AssetImportError(f"content hash changed during copy: {draft.object_key}")
            if not existed:
                newly_copied.append(draft.object_key)

        registered_by_id: dict[str, AssetRecord] = {}
        groups: list[AssetGroup] = []
        with repository.transaction():
            id_to_ref: dict[str, str] = {}
            for asset_id in registration_ids:
                draft = draft_by_id[asset_id]
                raw_lineage = lineage_raw_by_id.get(asset_id)
                if raw_lineage is not None:
                    parents = [
                        id_to_ref[parent] if parent in draft_by_id else parent
                        for parent in raw_lineage["parent_asset_refs"]
                    ]
                    draft = AssetDraft(**{**draft.__dict__, "lineage": _lineage_from_raw(raw_lineage, parents)})
                asset = repository._register_asset(draft)
                id_to_ref[asset_id] = asset.asset_ref
                registered_by_id[asset_id] = asset
            for item in group_items:
                members = []
                for member in item["members"]:
                    member_kind, raw = _group_member_reference(member)
                    members.append(
                        AssetGroupMember(
                            member_key=member["member_key"],
                            asset_role=member["asset_role"],
                            asset_ref=id_to_ref[raw] if member_kind == "asset_id" else raw,
                            order=member["order"],
                        )
                    )
                groups.append(
                    repository._register_group(
                        AssetGroupDraft(item["group_type"], item["pattern_id"], item["category_id"], members)
                    )
                )
    except Exception as exc:
        orphans = [
            key
            for key in newly_copied
            if repository.connection.execute("SELECT 1 FROM assets WHERE object_key=?", (key,)).fetchone() is None
        ]
        if isinstance(exc, AssetImportError):
            exc.orphans = orphans
            raise
        raise AssetImportError(str(exc), orphans=orphans) from exc

    return {
        "assets": [registered_by_id[asset_id].asset_ref for asset_id in ordered_ids],
        "groups": [group.group_ref for group in groups],
        "orphans": [],
    }


def supersede_imported_asset(repository: SQLiteAssetRepository, old_ref: str, draft: AssetDraft):
    return repository.supersede_asset(old_ref, draft)


def _lineage_from_raw(raw: dict[str, Any], parent_asset_refs: list[str]) -> AssetLineage:
    created = raw.get("created_at")
    created_at = datetime.fromisoformat(created) if created else datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return AssetLineage(
        parent_asset_refs=parent_asset_refs,
        derivation_type=raw["derivation_type"],
        executor_id=raw["executor_id"],
        provider=raw.get("provider"),
        model=raw.get("model"),
        prompt_template_version=raw.get("prompt_template_version"),
        prompt_sha256=raw.get("prompt_sha256"),
        parameters_sha256=raw["parameters_sha256"],
        derivation_signature=raw["derivation_signature"],
        created_at=created_at,
    )


def _topological_asset_ids(
    ordered_ids: list[str],
    lineage_raw_by_id: dict[str, dict[str, Any]],
    draft_by_id: dict[str, AssetDraft],
    repository: SQLiteAssetRepository,
) -> list[str]:
    dependencies: dict[str, set[str]] = {asset_id: set() for asset_id in ordered_ids}
    children: dict[str, set[str]] = defaultdict(set)
    for asset_id, raw_lineage in lineage_raw_by_id.items():
        for raw_parent in raw_lineage.get("parent_asset_refs", []):
            parent = str(raw_parent)
            if parent in draft_by_id:
                dependencies[asset_id].add(parent)
                children[parent].add(asset_id)
            elif parent.startswith("asset://"):
                if repository.get_asset(parent) is None:
                    raise AssetImportError(f"parent asset not found: {parent}")
            else:
                raise AssetImportError(f"unresolved lineage parent: {parent}")

    position = {asset_id: index for index, asset_id in enumerate(ordered_ids)}
    ready = sorted((asset_id for asset_id, parents in dependencies.items() if not parents), key=position.get)
    result: list[str] = []
    while ready:
        asset_id = ready.pop(0)
        result.append(asset_id)
        for child in sorted(children.get(asset_id, ()), key=position.get):
            dependencies[child].discard(asset_id)
            if not dependencies[child] and child not in result and child not in ready:
                ready.append(child)
                ready.sort(key=position.get)
    if len(result) != len(ordered_ids):
        stuck = [asset_id for asset_id in ordered_ids if asset_id not in result]
        raise AssetImportError(f"lineage cycle among imported assets: {stuck}")
    return result


def _synthetic_asset_refs(repository: SQLiteAssetRepository, ordered_ids: list[str]) -> dict[str, str]:
    existing = {asset.asset_ref for asset in repository.query_assets(AssetQuery(active_only=False))}
    next_value = (
        max(
            (int(match.group(1)) for ref in existing if (match := re.fullmatch(r"asset://A(\d+)", ref))),
            default=0,
        )
        + 1
    )
    refs: dict[str, str] = {}
    for asset_id in ordered_ids:
        while f"asset://A{next_value:04d}" in existing:
            next_value += 1
        refs[asset_id] = f"asset://A{next_value:04d}"
        existing.add(refs[asset_id])
        next_value += 1
    return refs


def _group_member_reference(member: dict[str, Any]) -> tuple[str, str]:
    has_id = member.get("asset_id") is not None
    has_ref = member.get("asset_ref") is not None
    if has_id == has_ref:
        raise AssetImportError("group member must provide exactly one of asset_id or asset_ref")
    return ("asset_id", str(member["asset_id"])) if has_id else ("asset_ref", str(member["asset_ref"]))

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from video_agent.assets.v4_validation import validate_asset_against_registry, validate_group_against_assets
from video_agent.contracts.v4 import AssetGroupMember, AssetLineage, EvidenceClass, SourceKind
from video_agent.io import sha256_file, sha256_json

from .repository import AssetDraft, AssetGroupDraft, AssetQuery, GroupQuery
from .sqlite_repository import SQLiteAssetRepository

MAPPING_VERSION = "legacy-v3-to-v4.2"
ROLE_MAP = {
    "site_home": "site_home",
    "feature_list": "feature_list",
    "other": "other",
    "feature_entry": "feature_entry",
    "feature_form_params": "parameter_panel",
    "result_image": "result_image",
    "reference_image": "reference_image",
    "plane_result": "flat_plan",
    "editor_workspace": "editor_page",
    "editor_local_modal": "editor_modal",
    "gallery_preview": "result_image",
    "brand_logo": "brand_logo",
    "outro": "outro",
}
AUTHORITATIVE_INPUTS = (
    "catalog.json",
    "derived/generated/registry.json",
    "relationships.json",
    "derived/sites/柯幻熊猫/文生图/功能入口/manifest.json",
    "derived/sites/柯幻熊猫/文生图/参数面板/manifest.json",
    "derived/sites/柯幻熊猫/文生图/参数面板序列/manifest.json",
    "derived/workflow_scenes/manifest.json",
    "results/_library_manifest.json",
)

ParentKind = Literal["legacy_id", "content_sha256", "object_key"]


class _DryRunRollback(Exception):
    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report


@dataclass(frozen=True)
class ParentHint:
    kind: ParentKind
    values: tuple[str, ...]


@dataclass(frozen=True)
class PlannedAsset:
    source_name: str
    legacy_id: str
    draft: AssetDraft
    parent_hint: ParentHint | None = None
    source_payload: dict[str, Any] | None = None


def migrate_legacy(repository: SQLiteAssetRepository, assets_root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    assets_root = assets_root.resolve()
    inputs = {name: assets_root / name for name in AUTHORITATIVE_INPUTS}
    catalog_path = inputs["catalog.json"]
    if not catalog_path.is_file():
        raise FileNotFoundError(catalog_path)

    fingerprint_sources = {name: sha256_file(path) for name, path in inputs.items() if path.is_file()}
    fingerprint = sha256_json(fingerprint_sources)
    migration_key = f"{MAPPING_VERSION}:{fingerprint}"
    existing = repository.connection.execute(
        "SELECT report_json FROM migration_runs WHERE migration_key=? AND status='completed'",
        (migration_key,),
    ).fetchone()
    if existing and not dry_run:
        return json.loads(existing["report_json"])

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    library = _load_json(inputs["results/_library_manifest.json"])
    generated = _load_json(inputs["derived/generated/registry.json"])
    relationships = _load_json(inputs["relationships.json"]).get("relationships", [])
    workflow = _load_json(inputs["derived/workflow_scenes/manifest.json"])
    entry_manifest = _load_json(inputs["derived/sites/柯幻熊猫/文生图/功能入口/manifest.json"])
    params_manifest = _load_json(inputs["derived/sites/柯幻熊猫/文生图/参数面板/manifest.json"])
    param_sequences = _load_json(inputs["derived/sites/柯幻熊猫/文生图/参数面板序列/manifest.json"])

    enrichment = _build_enrichment(library, generated)
    _enrich_site_manifest(enrichment, entry_manifest, "site_feature_entry_keyframe")
    _enrich_site_manifest(enrichment, params_manifest, "site_parameter_panel_keyframe")

    plans = _plan_catalog_assets(repository, assets_root, catalog.get("assets", []), enrichment)
    plans.extend(_plan_generated_assets(repository, assets_root, generated.get("assets", [])))
    plans.extend(_plan_site_manifest_assets(repository, assets_root, entry_manifest, "site_entry", "feature_entry"))
    plans.extend(_plan_site_manifest_assets(repository, assets_root, params_manifest, "site_params", "parameter_panel"))
    plans.extend(_plan_workflow_assets(repository, assets_root, workflow.get("assets", [])))
    plans.extend(_plan_sequence_frame_assets(repository, assets_root, param_sequences.get("sequences", [])))
    plans = _dedupe_plans(plans)
    plans = _order_by_lineage_dag(plans)

    report: dict[str, Any] = {
        "mapping_version": MAPPING_VERSION,
        "migration_key": migration_key,
        "input_fingerprint": fingerprint,
        "dry_run": dry_run,
        "assets": [],
        "groups": [],
        "bindings": {},
        "warnings": [],
        "failures": [],
    }

    try:
        with repository.transaction():
            refs: dict[str, str] = {}
            hash_refs: dict[str, str] = {}
            key_refs: dict[str, str] = {}
            hash_by_category: dict[tuple[str, str | None], str] = {}
            role_by_ref: dict[str, str] = {}
            for plan in plans:
                mapped = repository.connection.execute(
                    "SELECT v4_ref FROM legacy_id_map WHERE source_name=? AND legacy_id=?",
                    (plan.source_name, plan.legacy_id),
                ).fetchone()
                if mapped:
                    asset = repository.get_asset(mapped["v4_ref"])
                    if asset is None:
                        raise ValueError(f"legacy map points to missing asset: {plan.legacy_id}")
                else:
                    existing_by_key = repository.connection.execute(
                        "SELECT asset_ref FROM assets WHERE object_key=?",
                        (plan.draft.object_key,),
                    ).fetchone()
                    if existing_by_key:
                        asset = repository.get_asset(existing_by_key["asset_ref"])
                        assert asset is not None
                    else:
                        draft = _apply_parent_hint(
                            plan,
                            refs,
                            hash_refs,
                            key_refs=key_refs,
                            hash_by_category=hash_by_category,
                        )
                        asset = repository._register_asset(draft)
                    payload = plan.source_payload or {
                        "legacy_id": plan.legacy_id,
                        "object_key": plan.draft.object_key,
                    }
                    repository.connection.execute(
                        "INSERT OR IGNORE INTO legacy_id_map VALUES (?,?,?,?,?)",
                        (
                            plan.source_name,
                            plan.legacy_id,
                            "asset",
                            asset.asset_ref,
                            json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        ),
                    )
                refs[plan.legacy_id] = asset.asset_ref
                catalog_asset_id = (plan.source_payload or {}).get("asset_id")
                if isinstance(catalog_asset_id, str) and catalog_asset_id:
                    # Keep hash-based catalog IDs resolvable for relationships, but never let a
                    # colliding second path overwrite the first mapping.
                    refs.setdefault(catalog_asset_id, asset.asset_ref)
                key_refs[asset.object_key] = asset.asset_ref
                hash_by_category[(asset.content_sha256, asset.category_id)] = asset.asset_ref
                # Keep a single sha→ref fallback for workflows that only know content hashes.
                # Prefer first registration so shared screenshots do not silently flip parents.
                hash_refs.setdefault(asset.content_sha256, asset.asset_ref)
                role_by_ref[asset.asset_ref] = asset.asset_role
                report["assets"].append(
                    {
                        "source_name": plan.source_name,
                        "legacy_id": plan.legacy_id,
                        "asset_ref": asset.asset_ref,
                        "object_key": asset.object_key,
                        "role": asset.asset_role,
                        "source_kind": asset.source_kind.value,
                        "evidence_class": asset.evidence_class.value,
                    }
                )

            workflow_index = _build_workflow_index(workflow.get("assets", []), hash_refs, refs)
            registered_editor_keys: set[tuple[str, str, str]] = set()
            for relationship in relationships:
                _register_relationship_groups(
                    repository,
                    relationship,
                    refs,
                    hash_refs,
                    role_by_ref,
                    workflow_index,
                    registered_editor_keys,
                    report,
                )
            _register_parameter_sequences(
                repository, assets_root, param_sequences.get("sequences", []), hash_refs, report
            )
            _register_remaining_workflow_editor_groups(
                repository, workflow_index, registered_editor_keys, report
            )
            _bind_configured_assets(repository, report)
            group_refs = [item["group_ref"] for item in report["groups"]]
            report["snapshot"] = repository.freeze(list(refs.values()), group_refs).content_sha256
            if dry_run:
                raise _DryRunRollback(report)
            now = datetime.now(timezone.utc).isoformat()
            repository.connection.execute(
                "INSERT INTO migration_runs VALUES (?,?,?,?,?,?,?)",
                (
                    migration_key,
                    MAPPING_VERSION,
                    fingerprint,
                    "completed",
                    json.dumps(report, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
    except _DryRunRollback as done:
        return done.report
    return report


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_enrichment(library: dict[str, Any], generated: dict[str, Any]) -> dict[str, dict[str, Any]]:
    enrichment: dict[str, dict[str, Any]] = {}
    for item in library.get("assets", []) + generated.get("assets", []):
        digest = item.get("sha256") or item.get("content_sha256")
        if digest:
            enrichment[digest] = dict(item)
    return enrichment


def _enrich_site_manifest(enrichment: dict[str, dict[str, Any]], manifest: dict[str, Any], derive_kind: str) -> None:
    for item in manifest.get("assets", []):
        digest = item.get("output_sha256")
        if not digest:
            continue
        current = dict(enrichment.get(digest, {}))
        current.update(
            {
                "source_path": item.get("source_path") or current.get("source_path"),
                "source_sha256": item.get("source_sha256"),
                "parent_sha256s": [item["source_sha256"]] if item.get("source_sha256") else current.get("parent_sha256s", []),
                "derive_kind": derive_kind,
                "provider": item.get("provider"),
                "model": item.get("model"),
                "prompt_sha256": item.get("prompt_sha256"),
                "semantic_path": ["文生图", *item.get("feature_path", [])] if item.get("feature_path") else current.get("semantic_path"),
                "evidence_class": "E2_semantic_derivative",
                "origin": derive_kind,
            }
        )
        enrichment[digest] = current


def _plan_catalog_assets(
    repository: SQLiteAssetRepository,
    assets_root: Path,
    items: list[dict[str, Any]],
    enrichment: dict[str, dict[str, Any]],
) -> list[PlannedAsset]:
    plans: list[PlannedAsset] = []
    for item in items:
        role = _role(item)
        if role is None:
            continue
        object_key = _object_key(item.get("path", ""), assets_root)
        info = repository.object_store.inspect(object_key)
        expected = item.get("sha256")
        if expected and expected != info.content_sha256:
            raise ValueError(
                f"legacy hash mismatch for {item.get('asset_id')}: expected {expected}, got {info.content_sha256}"
            )
        meta = enrichment.get(info.content_sha256, {})
        category = _category(item.get("semantic_path") or meta.get("semantic_path") or [], repository, role)
        source_kind, evidence, parent_hint, lineage = _provenance(
            item, meta, info.content_sha256, assets_root=assets_root
        )
        claims = _map_claims(item.get("claims") or meta.get("claims") or [], repository, evidence)
        draft = AssetDraft(
            filename=Path(object_key).name,
            object_key=object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=category[0] if category else None,
            category_id="/".join(category) if category else None,
            category_path=category[1:] if category else [],
            asset_role=role,
            case_label=item.get("case_label") or meta.get("case_label"),
            industry=item.get("industry") or meta.get("industry"),
            description=item.get("description") or meta.get("description"),
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=info.animated,
            source_kind=source_kind,
            origin_type=str((item.get("provenance") or {}).get("origin") or meta.get("origin") or "legacy_v3"),
            evidence_class=evidence,
            claims=claims,
            lineage=lineage,
        )
        # object_key is the stable identity. Hash-prefixed catalog asset_ids can collide when
        # two screenshots intentionally share bytes (e.g. VI vs 文化墙 entry).
        legacy_id = object_key
        plans.append(
            PlannedAsset(
                "catalog",
                legacy_id,
                draft,
                parent_hint,
                {
                    "asset_id": item.get("asset_id"),
                    "object_key": object_key,
                    "quality": item.get("quality"),
                    "production_eligible": item.get("production_eligible"),
                },
            )
        )
    return plans


def _plan_generated_assets(
    repository: SQLiteAssetRepository,
    assets_root: Path,
    items: list[dict[str, Any]],
) -> list[PlannedAsset]:
    plans: list[PlannedAsset] = []
    for item in items:
        role = _role(item)
        if role is None:
            continue
        object_key = _object_key(item.get("path", ""), assets_root)
        info = repository.object_store.inspect(object_key)
        if item.get("sha256") and item["sha256"] != info.content_sha256:
            raise ValueError(f"generated registry hash mismatch for {object_key}")
        parents = [str(value) for value in (item.get("parent_asset_ids") or []) if value]
        parent_hashes = [str(value) for value in (item.get("parent_sha256s") or []) if value]
        if item.get("source_sha256"):
            parent_hashes.append(str(item["source_sha256"]))
        source_path = item.get("source_path")
        if source_path:
            hint = ParentHint("object_key", (_object_key(str(source_path), assets_root),))
        elif parent_hashes:
            hint = ParentHint("content_sha256", tuple(dict.fromkeys(parent_hashes)))
        elif parents:
            hint = ParentHint("legacy_id", tuple(parents))
        else:
            raise ValueError(f"generated asset missing parents: {object_key}")
        category = _category(item.get("semantic_path") or [], repository, role)
        derivation_type = str(item.get("derive_kind") or item.get("derivation_type") or "generated")
        lineage = _placeholder_lineage(
            derivation_type=derivation_type,
            executor_id=str(item.get("executor_id") or "generated_registry"),
            provider=item.get("provider"),
            model=item.get("model"),
            prompt_sha256=item.get("prompt_sha256"),
            parameters={"object_key": object_key, "parents": list(hint.values)},
        )
        draft = AssetDraft(
            filename=Path(object_key).name,
            object_key=object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=category[0] if category else None,
            category_id="/".join(category) if category else None,
            category_path=category[1:] if category else [],
            asset_role=role,
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=info.animated,
            source_kind=SourceKind.DERIVED,
            origin_type=str(item.get("origin") or "generated_registry"),
            evidence_class=EvidenceClass.SEMANTIC,
            claims=[],
            lineage=lineage,
        )
        legacy_id = str(item.get("asset_id") or item.get("sha256") or object_key)
        plans.append(PlannedAsset("generated", legacy_id, draft, hint, item))
    return plans


def _plan_site_manifest_assets(
    repository: SQLiteAssetRepository,
    assets_root: Path,
    manifest: dict[str, Any],
    source_name: str,
    role: str,
) -> list[PlannedAsset]:
    plans: list[PlannedAsset] = []
    derive_kind = "site_feature_entry_keyframe" if role == "feature_entry" else "site_parameter_panel_keyframe"
    for item in manifest.get("assets", []):
        output_path = item.get("output_path")
        output_sha = item.get("output_sha256")
        source_sha = item.get("source_sha256")
        if not output_path or not output_sha or not source_sha:
            raise ValueError(f"{source_name} manifest entry missing output/source hashes")
        object_key = _object_key(output_path, assets_root)
        info = repository.object_store.inspect(object_key)
        if info.content_sha256 != output_sha:
            raise ValueError(f"{source_name} hash mismatch for {object_key}")
        feature_path = ["文生图", *item.get("feature_path", [])]
        category = _category(feature_path, repository, role)
        if item.get("source_path"):
            source_object_key = _object_key(str(item["source_path"]), assets_root)
            hint = ParentHint("object_key", (source_object_key,))
            parent_params = {"source_object_key": source_object_key, "source_sha": source_sha}
        else:
            hint = ParentHint("content_sha256", (str(source_sha),))
            parent_params = {"source_sha": source_sha}
        lineage = _placeholder_lineage(
            derivation_type=derive_kind,
            executor_id=str(item.get("provider") or source_name),
            provider=item.get("provider"),
            model=item.get("model"),
            prompt_sha256=item.get("prompt_sha256"),
            parameters={
                **parent_params,
                "object_key": object_key,
                "derive_kind": derive_kind,
            },
        )
        draft = AssetDraft(
            filename=Path(object_key).name,
            object_key=object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=category[0] if category else None,
            category_id="/".join(category) if category else None,
            category_path=category[1:] if category else [],
            asset_role=role,
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=info.animated,
            source_kind=SourceKind.DERIVED,
            origin_type=derive_kind,
            evidence_class=EvidenceClass.SEMANTIC,
            claims=[],
            lineage=lineage,
        )
        plans.append(PlannedAsset(source_name, output_sha, draft, hint, item))
    return plans


def _plan_workflow_assets(
    repository: SQLiteAssetRepository,
    assets_root: Path,
    items: list[dict[str, Any]],
) -> list[PlannedAsset]:
    plans: list[PlannedAsset] = []
    for index, item in enumerate(items):
        if "path" not in item or "role" not in item:
            continue
        role = _role(item)
        if role is None:
            continue
        object_key = _object_key(item["path"], assets_root)
        info = repository.object_store.inspect(object_key)
        if item.get("sha256") and item["sha256"] != info.content_sha256:
            raise ValueError(f"workflow hash mismatch for {object_key}")
        category = _category(item.get("semantic_path") or [], repository, role)
        parent_sha = item.get("source_artwork_sha256")
        if parent_sha:
            source_kind, evidence = SourceKind.DERIVED, EvidenceClass.SEMANTIC
            hint = ParentHint("content_sha256", (str(parent_sha),))
            lineage = _placeholder_lineage(
                derivation_type=str(item.get("workflow_step") or "workflow_scene"),
                executor_id="legacy_workflow",
                provider=item.get("provider"),
                model=item.get("model"),
                prompt_sha256=item.get("prompt_sha256"),
                parameters={"parent_sha": parent_sha, "object_key": object_key},
            )
        else:
            source_kind, evidence = SourceKind.ORIGINAL, EvidenceClass.SOURCE
            hint, lineage = None, None
        legacy_id = str(item.get("sha256") or f"workflow:{index}:{object_key}")
        # Also alias common catalog-style id used by relationships.json
        alias = f"asset_workflow_scene_{info.content_sha256[:12]}"
        draft = AssetDraft(
            filename=Path(object_key).name,
            object_key=object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=category[0] if category else None,
            category_id="/".join(category) if category else None,
            category_path=category[1:] if category else [],
            asset_role=role,
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=info.animated,
            source_kind=source_kind,
            origin_type="legacy_workflow",
            evidence_class=evidence,
            claims=[],
            lineage=lineage,
        )
        plans.append(PlannedAsset("workflow", legacy_id, draft, hint, item))
        plans.append(PlannedAsset("workflow_alias", alias, draft, hint, {"alias_of": legacy_id, **item}))
    return plans


def _plan_sequence_frame_assets(
    repository: SQLiteAssetRepository,
    assets_root: Path,
    sequences: list[dict[str, Any]],
) -> list[PlannedAsset]:
    plans: list[PlannedAsset] = []
    for sequence in sequences:
        feature_path = ["文生图", *sequence.get("feature_path", [])]
        source_sha = sequence.get("source_sha256")
        source_path = sequence.get("source_path")
        for member_key, frame in (sequence.get("frames") or {}).items():
            object_key = _object_key(frame["path"], assets_root)
            info = repository.object_store.inspect(object_key)
            if frame.get("sha256") and frame["sha256"] != info.content_sha256:
                raise ValueError(f"sequence frame hash mismatch: {object_key}")
            category = _category(feature_path, repository, "parameter_panel")
            if source_sha or source_path:
                source_kind, evidence = SourceKind.DERIVED, EvidenceClass.SEMANTIC
                if source_path:
                    source_object_key = _object_key(str(source_path), assets_root)
                    hint = ParentHint("object_key", (source_object_key,))
                    parent_params = {
                        "source_object_key": source_object_key,
                        "source_sha": source_sha,
                    }
                else:
                    hint = ParentHint("content_sha256", (str(source_sha),))
                    parent_params = {"source_sha": source_sha}
                lineage = _placeholder_lineage(
                    derivation_type="site_params_flower_text_frame_sequence",
                    executor_id=str(frame.get("origin") or "legacy_sequence"),
                    provider=frame.get("provider"),
                    model=frame.get("model"),
                    prompt_sha256=sequence.get("prompt_sha256"),
                    parameters={
                        **parent_params,
                        "member_key": member_key,
                        "object_key": object_key,
                        "sequence_id": sequence.get("sequence_id"),
                    },
                )
            else:
                source_kind, evidence = SourceKind.ORIGINAL, EvidenceClass.SOURCE
                hint, lineage = None, None
            draft = AssetDraft(
                filename=Path(object_key).name,
                object_key=object_key,
                content_sha256=info.content_sha256,
                media_type=info.media_type,
                module=category[0] if category else None,
                category_id="/".join(category) if category else None,
                category_path=category[1:] if category else [],
                asset_role="parameter_panel",
                width=info.width,
                height=info.height,
                orientation=info.orientation,
                animated=False,
                source_kind=source_kind,
                origin_type="parameter_sequence",
                evidence_class=evidence,
                claims=[],
                lineage=lineage,
            )
            plans.append(
                PlannedAsset(
                    "parameter_sequence",
                    f"{sequence.get('sequence_id')}:{member_key}",
                    draft,
                    hint,
                    {"sequence_id": sequence.get("sequence_id"), "member_key": member_key},
                )
            )
    return plans


def _dedupe_plans(plans: list[PlannedAsset]) -> list[PlannedAsset]:
    by_key: dict[str, PlannedAsset] = {}
    priority = {
        "catalog": 0,
        "generated": 1,
        "site_entry": 2,
        "site_params": 2,
        "workflow": 3,
        "workflow_alias": 4,
        "parameter_sequence": 5,
    }
    alias_plans: list[PlannedAsset] = []
    for plan in plans:
        if plan.source_name == "workflow_alias":
            alias_plans.append(plan)
            continue
        current = by_key.get(plan.draft.object_key)
        if current is None or priority.get(plan.source_name, 9) < priority.get(current.source_name, 9):
            by_key[plan.draft.object_key] = plan
    result = list(by_key.values())
    # Keep alias plans that point at surviving object keys so relationship IDs resolve.
    for alias in alias_plans:
        if alias.draft.object_key in by_key:
            result.append(alias)
    return result


def _order_by_lineage_dag(plans: list[PlannedAsset]) -> list[PlannedAsset]:
    by_legacy = {plan.legacy_id: plan for plan in plans}
    # Catalog plans use object_key as the unique legacy_id; also index unambiguous
    # catalog asset_ids so parent_asset_ids like "result" still order correctly.
    asset_id_claims: dict[str, PlannedAsset | None] = {}
    for plan in plans:
        asset_id = (plan.source_payload or {}).get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            continue
        if asset_id in asset_id_claims and asset_id_claims[asset_id] is not plan:
            asset_id_claims[asset_id] = None
        else:
            asset_id_claims[asset_id] = plan
    for asset_id, plan in asset_id_claims.items():
        if plan is not None and asset_id not in by_legacy:
            by_legacy[asset_id] = plan
    by_hash = {plan.draft.content_sha256: plan for plan in plans}
    by_object_key = {plan.draft.object_key: plan for plan in plans}
    remaining = {
        f"{plan.source_name}:{plan.legacy_id}": plan
        for plan in sorted(
            plans,
            key=lambda item: (
                item.draft.object_key,
                item.draft.content_sha256,
                item.source_name,
                item.legacy_id,
            ),
        )
    }
    ordered: list[PlannedAsset] = []
    registered_keys: set[str] = set()
    registered_hashes: set[str] = set()
    registered_legacy: set[str] = set()
    while remaining:
        progress = False
        for key, plan in list(remaining.items()):
            if plan.parent_hint is None:
                ordered.append(plan)
                registered_keys.add(plan.draft.object_key)
                registered_hashes.add(plan.draft.content_sha256)
                registered_legacy.add(plan.legacy_id)
                del remaining[key]
                progress = True
                continue
            ready = True
            for value in plan.parent_hint.values:
                if plan.parent_hint.kind == "legacy_id":
                    parent = by_legacy.get(value)
                    if parent is not None and f"{parent.source_name}:{parent.legacy_id}" in remaining:
                        ready = False
                        break
                    if parent is None and value not in registered_legacy:
                        # Parent may already be outside this batch; allow and fail later if unresolved.
                        continue
                elif plan.parent_hint.kind == "object_key":
                    parent = by_object_key.get(value)
                    if parent is not None and f"{parent.source_name}:{parent.legacy_id}" in remaining:
                        ready = False
                        break
                else:
                    parent = by_hash.get(value)
                    if parent is not None and f"{parent.source_name}:{parent.legacy_id}" in remaining:
                        ready = False
                        break
                    # Shared-hash screenshots may have multiple catalog plans. Wait until every
                    # remaining plan with this hash is registered so category-aware parent
                    # resolution can see the matching category.
                    for other in remaining.values():
                        if other.draft.content_sha256 == value and other is not plan:
                            ready = False
                            break
                    if not ready:
                        break
            if ready:
                ordered.append(plan)
                registered_keys.add(plan.draft.object_key)
                registered_hashes.add(plan.draft.content_sha256)
                registered_legacy.add(plan.legacy_id)
                del remaining[key]
                progress = True
        if not progress:
            stuck = ", ".join(sorted(remaining))
            raise ValueError(f"lineage cycle or unresolved parents among: {stuck}")
    return ordered


def _resolve_content_sha_parent(
    content_sha256: str,
    *,
    preferred_category_id: str | None,
    hash_refs: dict[str, str],
    hash_by_category: dict[tuple[str, str | None], str],
) -> str:
    if preferred_category_id is not None:
        matched = hash_by_category.get((content_sha256, preferred_category_id))
        if matched is not None:
            return matched
    if content_sha256 not in hash_refs:
        raise ValueError(f"missing parent hash {content_sha256}")
    return hash_refs[content_sha256]


def _apply_parent_hint(
    plan: PlannedAsset,
    refs: dict[str, str],
    hash_refs: dict[str, str],
    *,
    key_refs: dict[str, str] | None = None,
    hash_by_category: dict[tuple[str, str | None], str] | None = None,
) -> AssetDraft:
    if plan.draft.lineage is None:
        return plan.draft
    if plan.parent_hint is None:
        raise ValueError(f"derived asset missing parent hint: {plan.draft.object_key}")
    key_refs = key_refs or {}
    hash_by_category = hash_by_category or {}
    parent_refs: list[str] = []
    for value in plan.parent_hint.values:
        if plan.parent_hint.kind == "legacy_id":
            if value not in refs:
                raise ValueError(f"missing parent legacy id {value} for {plan.draft.object_key}")
            parent_refs.append(refs[value])
        elif plan.parent_hint.kind == "object_key":
            if value not in key_refs:
                raise ValueError(f"missing parent object_key {value} for {plan.draft.object_key}")
            parent_refs.append(key_refs[value])
        else:
            parent_refs.append(
                _resolve_content_sha_parent(
                    value,
                    preferred_category_id=plan.draft.category_id,
                    hash_refs=hash_refs,
                    hash_by_category=hash_by_category,
                )
            )
    parent_refs = list(dict.fromkeys(parent_refs))
    lineage = AssetLineage(
        parent_asset_refs=parent_refs,
        derivation_type=plan.draft.lineage.derivation_type,
        executor_id=plan.draft.lineage.executor_id,
        provider=plan.draft.lineage.provider,
        model=plan.draft.lineage.model,
        prompt_template_version=plan.draft.lineage.prompt_template_version,
        prompt_sha256=plan.draft.lineage.prompt_sha256,
        parameters_sha256=plan.draft.lineage.parameters_sha256,
        derivation_signature=plan.draft.lineage.derivation_signature,
        created_at=plan.draft.lineage.created_at,
    )
    return AssetDraft(**{**plan.draft.__dict__, "lineage": lineage})


def _placeholder_lineage(
    *,
    derivation_type: str,
    executor_id: str,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
    prompt_sha256: str | None = None,
) -> AssetLineage:
    parameters_sha256 = sha256_json(parameters)
    return AssetLineage(
        parent_asset_refs=["asset://A0000"],
        derivation_type=derivation_type,
        executor_id=executor_id,
        provider=provider,
        model=model,
        prompt_template_version=None,
        prompt_sha256=prompt_sha256,
        parameters_sha256=parameters_sha256,
        derivation_signature=sha256_json(
            {
                "derivation_type": derivation_type,
                "executor_id": executor_id,
                "parameters": parameters,
            }
        ),
        created_at=datetime.now(timezone.utc),
    )


def _role(item: dict[str, Any]) -> str | None:
    if item.get("role") == "brand_ip":
        return None
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    derive_kind = item.get("derive_kind") or meta.get("derive_kind")
    editor_flow_role = item.get("editor_flow_role") or meta.get("editor_flow_role")
    workflow_step = item.get("workflow_step") or meta.get("workflow_step")
    if (
        derive_kind in {"edited_result", "result_to_edit_state"}
        or editor_flow_role == "edited_result"
        or workflow_step == "edited_result"
    ):
        return "edited_result"
    role = ROLE_MAP.get(item.get("role"))
    if role is None:
        raise ValueError(f"unknown legacy role: {item.get('role')}")
    return role


def _object_key(value: str, root: Path) -> str:
    value = value.replace("\\", "/")
    if value.startswith("assets/"):
        return value[len("assets/") :]
    path = Path(value)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(f"legacy primary path outside object root: {value}") from exc
    return value.lstrip("./")


def _category(path: list[str], repository: SQLiteAssetRepository, role: str) -> list[str] | None:
    if not path:
        role_entry = repository.registry.entry("asset_role", role)
        if role_entry and getattr(role_entry, "requires_category", False):
            raise ValueError(f"category-required role missing semantic_path: {role}")
        return None
    candidates: list[str] = []
    if len(path) >= 2 and path[0] in {"文生图", "网站"}:
        candidates.append("/".join(path))
    else:
        candidates.append("文生图/" + "/".join(path))
        candidates.append("/".join(path))
    for candidate in candidates:
        category = repository.registry.resolve_category(candidate)
        if category is not None:
            return category.id.split("/")
    category = repository.registry.resolve_category(path[-1])
    if category is not None:
        return category.id.split("/")
    role_entry = repository.registry.entry("asset_role", role)
    if role_entry and getattr(role_entry, "requires_category", False):
        raise ValueError(f"unknown legacy category: {path}")
    return None


def _map_claims(raw_claims: list[Any], repository: SQLiteAssetRepository, evidence: EvidenceClass) -> list[str]:
    if evidence in {EvidenceClass.SEMANTIC, EvidenceClass.DECORATIVE}:
        return []
    mapped: list[str] = []
    for claim in raw_claims:
        value = str(claim)
        if value == "curated_result_image":
            value = "feature_can_generate_result"
        if repository.registry.entry("claim", value) is not None:
            mapped.append(value)
    return mapped


def _provenance(
    item: dict[str, Any],
    meta: dict[str, Any],
    content_sha256: str,
    *,
    assets_root: Path | None = None,
) -> tuple[SourceKind, EvidenceClass, ParentHint | None, AssetLineage | None]:
    provenance = item.get("provenance") or {}
    item_meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    origin = str(provenance.get("origin") or meta.get("origin") or "")
    parents = [str(value) for value in (provenance.get("parent_asset_ids") or meta.get("parent_asset_ids") or []) if value]
    parent_hashes = [str(value) for value in (meta.get("parent_sha256s") or []) if value]
    if meta.get("source_sha256"):
        parent_hashes.append(str(meta["source_sha256"]))
    source_artwork = (
        item_meta.get("source_artwork_sha256")
        or item.get("source_artwork_sha256")
        or meta.get("source_artwork_sha256")
    )
    if source_artwork:
        parent_hashes.append(str(source_artwork))
    source_path = item_meta.get("source_path") or meta.get("source_path") or item.get("source_path")
    derive_kind = item.get("derive_kind") or meta.get("derive_kind") or item_meta.get("derive_kind")
    if not derive_kind and (item.get("editor_flow_role") or item_meta.get("editor_flow_role")) == "edited_result":
        derive_kind = "edited_result"
    explicit = item.get("evidence_class")

    if meta.get("source_sha256") and meta.get("derive_kind"):
        evidence = EvidenceClass(meta.get("evidence_class") or EvidenceClass.SEMANTIC.value)
    elif explicit:
        evidence = EvidenceClass(explicit)
    elif item.get("role") == "outro" or "decorative" in origin:
        evidence = EvidenceClass.DECORATIVE
    elif derive_kind or parents or parent_hashes or source_path:
        evidence = EvidenceClass.SEMANTIC
    else:
        evidence = EvidenceClass.SOURCE

    if evidence is EvidenceClass.SOURCE:
        return SourceKind.ORIGINAL, evidence, None, None
    if evidence is EvidenceClass.DECORATIVE and not parents and not parent_hashes and not derive_kind and not source_path:
        return SourceKind.ORIGINAL, evidence, None, None
    if not parents and not parent_hashes and not source_path:
        raise ValueError(f"derived legacy asset requires parents: {item.get('asset_id') or content_sha256}")

    # Prefer source object_key so shared-byte screenshots still parent to the matching path/category.
    if source_path and assets_root is not None:
        hint = ParentHint("object_key", (_object_key(str(source_path), assets_root),))
    elif parent_hashes:
        hint = ParentHint("content_sha256", tuple(dict.fromkeys(parent_hashes)))
    else:
        hint = ParentHint("legacy_id", tuple(parents))
    lineage = _placeholder_lineage(
        derivation_type=str(derive_kind or origin or "legacy_derived"),
        executor_id="legacy_catalog",
        provider=meta.get("provider"),
        model=meta.get("model"),
        prompt_sha256=meta.get("prompt_sha256"),
        parameters={"parents": list(hint.values), "content_sha256": content_sha256},
    )
    return SourceKind.DERIVED, evidence, hint, lineage


@dataclass
class WorkflowFlow:
    flow_id: str
    category: str | None = None
    source_result: str | None = None
    editor_page: str | None = None
    edited_result: str | None = None
    seen_roles: set[str] | None = None


def _feature_key(path: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    parts = list(path)
    if parts and parts[0] != "文生图":
        parts = ["文生图", *parts]
    return tuple(parts)


def _canonical_category_id(
    path: list[str] | tuple[str, ...],
    repository: SQLiteAssetRepository,
    role: str,
) -> str:
    category = _category(list(path), repository, role)
    if not category:
        raise ValueError(f"missing category for {role}: {list(path)}")
    return "/".join(category)


def _build_workflow_index(
    items: list[dict[str, Any]],
    hash_refs: dict[str, str],
    refs: dict[str, str],
) -> dict[str, Any]:
    by_flow: dict[str, WorkflowFlow] = {}
    by_feature: dict[tuple[str, ...], list[str]] = {}
    by_editor_sha: dict[str, str] = {}
    for item in items:
        digest = item.get("sha256")
        if not digest or digest not in hash_refs:
            continue
        asset_ref = hash_refs[digest]
        feature = _feature_key(item.get("semantic_path") or [])
        flow_id = item.get("editor_flow_sequence_id") or f"feature:{'/'.join(feature)}"
        bucket = by_flow.setdefault(str(flow_id), WorkflowFlow(flow_id=str(flow_id), seen_roles=set()))
        assert bucket.seen_roles is not None
        role = item.get("editor_flow_role") or item.get("workflow_step") or item.get("role")
        bucket.seen_roles.add(str(role))
        if feature:
            bucket.category = "/".join(feature)
            by_feature.setdefault(feature, []).append(str(flow_id))
        if role in {"page", "editor_page", "editor_workspace", "local_editing"}:
            bucket.editor_page = asset_ref
            by_editor_sha[digest] = str(flow_id)
            by_editor_sha[f"asset_workflow_scene_{digest[:12]}"] = str(flow_id)
        elif role == "edited_result":
            bucket.edited_result = asset_ref
        source_sha = item.get("source_artwork_sha256")
        if source_sha and source_sha in hash_refs:
            bucket.source_result = hash_refs[str(source_sha)]
    return {"by_flow": by_flow, "by_feature": by_feature, "by_editor_sha": by_editor_sha, "refs": refs}


def _register_relationship_groups(
    repository: SQLiteAssetRepository,
    relationship: dict[str, Any],
    refs: dict[str, str],
    hash_refs: dict[str, str],
    role_by_ref: dict[str, str],
    workflow_index: dict[str, Any],
    registered_editor_keys: set[tuple[str, str, str]],
    report: dict[str, Any],
) -> None:
    rel_id = relationship.get("relationship_id")
    category_parts = relationship.get("feature_path") or []
    editor_intent = any(
        relationship.get(key)
        for key in ("editor_composite_asset_id", "edited_result_asset_id", "editor_modal_asset_id")
    )
    causal_intent = any(
        relationship.get(key) for key in ("reference_asset_id", "flat_plan_asset_id", "plane_asset_id")
    )
    if not category_parts:
        if not editor_intent and not causal_intent:
            return
        raise ValueError(f"relationship missing feature_path: {rel_id}")
    category = _canonical_category_id(category_parts, repository, "result_image")

    reference_id = relationship.get("reference_asset_id")
    result_id = relationship.get("result_asset_id")
    flat_id = relationship.get("flat_plan_asset_id") or relationship.get("plane_asset_id")
    if causal_intent:
        missing = [
            name
            for name, value in (("reference_image", reference_id), ("result_image", result_id), ("flat_plan", flat_id))
            if not value
        ]
        if missing:
            raise ValueError(f"relationship {rel_id} missing causal members: {', '.join(missing)}")
        assert reference_id and result_id and flat_id
        for legacy_id in (reference_id, result_id, flat_id):
            if legacy_id not in refs:
                raise ValueError(f"relationship {rel_id} references unknown asset {legacy_id}")
        members = [
            AssetGroupMember(
                member_key="reference_image",
                asset_role="reference_image",
                asset_ref=refs[reference_id],
                order=1,
            ),
            AssetGroupMember(
                member_key="result_image",
                asset_role="result_image",
                asset_ref=refs[result_id],
                order=2,
            ),
            AssetGroupMember(
                member_key="flat_plan",
                asset_role="flat_plan",
                asset_ref=refs[flat_id],
                order=3,
            ),
        ]
        group = repository._register_group(AssetGroupDraft("causal", "reference_result_plan", category, members))
        report["groups"].append(
            {"relationship_id": rel_id, "pattern_id": "reference_result_plan", "group_ref": group.group_ref}
        )

    if editor_intent:
        source_ref, editor_ref, edited_ref = _resolve_editor_members(
            relationship, refs, role_by_ref, workflow_index
        )
        key = (source_ref, editor_ref, edited_ref)
        if key in registered_editor_keys:
            return
        members = [
            AssetGroupMember(member_key="source_result", asset_role="result_image", asset_ref=source_ref, order=1),
            AssetGroupMember(member_key="editor_page", asset_role="editor_page", asset_ref=editor_ref, order=2),
            AssetGroupMember(member_key="edited_result", asset_role="edited_result", asset_ref=edited_ref, order=3),
        ]
        group = repository._register_group(AssetGroupDraft("process", "editor_sequence", category, members))
        registered_editor_keys.add(key)
        report["groups"].append(
            {"relationship_id": rel_id, "pattern_id": "editor_sequence", "group_ref": group.group_ref}
        )


def _resolve_editor_members(
    relationship: dict[str, Any],
    refs: dict[str, str],
    role_by_ref: dict[str, str],
    workflow_index: dict[str, Any],
) -> tuple[str, str, str]:
    rel_id = relationship.get("relationship_id")
    result_id = relationship.get("result_asset_id")
    editor_id = relationship.get("editor_composite_asset_id")
    edited_id = relationship.get("edited_result_asset_id")
    feature = _feature_key(relationship.get("feature_path") or [])
    by_flow: dict[str, WorkflowFlow] = workflow_index["by_flow"]
    by_feature: dict[tuple[str, ...], list[str]] = workflow_index["by_feature"]
    by_editor_sha: dict[str, str] = workflow_index["by_editor_sha"]

    flow: WorkflowFlow | None = None
    if editor_id and editor_id in by_editor_sha:
        flow = by_flow[by_editor_sha[editor_id]]
    if flow is None and editor_id and editor_id in refs:
        editor_asset_ref = refs[editor_id]
        for candidate in by_flow.values():
            if candidate.editor_page == editor_asset_ref:
                flow = candidate
                break
    if flow is None and feature in by_feature:
        flow = by_flow[by_feature[feature][0]]

    source_ref: str | None = None
    editor_ref: str | None = None
    edited_ref: str | None = None

    if editor_id and result_id and editor_id == result_id:
        if flow is None or not flow.editor_page:
            raise ValueError(
                f"relationship {rel_id} editor_composite_asset_id equals result_asset_id; "
                "distinct editor_page required from workflow manifest"
            )
        editor_ref = flow.editor_page
        source_ref = flow.source_result
    else:
        if result_id:
            if result_id not in refs:
                raise ValueError(f"relationship {rel_id} references unknown result {result_id}")
            source_ref = refs[result_id]
        if editor_id:
            if editor_id not in refs:
                raise ValueError(f"relationship {rel_id} references unknown editor {editor_id}")
            editor_ref = refs[editor_id]
        if flow:
            source_ref = source_ref or flow.source_result
            editor_ref = editor_ref or flow.editor_page

    if edited_id:
        if edited_id not in refs:
            raise ValueError(f"relationship {rel_id} references unknown edited result {edited_id}")
        edited_ref = refs[edited_id]
    elif flow:
        edited_ref = flow.edited_result

    if not source_ref or not editor_ref or not edited_ref:
        raise ValueError(
            f"relationship {rel_id} incomplete editor_sequence after workflow merge "
            f"(source={source_ref}, editor={editor_ref}, edited={edited_ref})"
        )
    if source_ref == editor_ref:
        raise ValueError(f"relationship {rel_id} source_result must be distinct from editor_page")
    if role_by_ref.get(source_ref) not in {None, "result_image"}:
        raise ValueError(f"relationship {rel_id} source_result has role {role_by_ref.get(source_ref)}")
    return source_ref, editor_ref, edited_ref


def _register_parameter_sequences(
    repository: SQLiteAssetRepository,
    assets_root: Path,
    sequences: list[dict[str, Any]],
    hash_refs: dict[str, str],
    report: dict[str, Any],
) -> None:
    for sequence in sequences:
        frames = sequence.get("frames") or {}
        if not {"base", "stage", "final"} <= set(frames):
            raise ValueError(f"parameter sequence missing frames: {sequence.get('sequence_id')}")
        members = []
        for order, key in enumerate(("base", "stage", "final"), 1):
            digest = frames[key]["sha256"]
            if digest not in hash_refs:
                object_key = _object_key(frames[key]["path"], assets_root)
                row = repository.connection.execute(
                    "SELECT asset_ref FROM assets WHERE object_key=?", (object_key,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"parameter sequence frame not migrated: {object_key}")
                hash_refs[digest] = row["asset_ref"]
            members.append(
                AssetGroupMember(
                    member_key=key,
                    asset_role="parameter_panel",
                    asset_ref=hash_refs[digest],
                    order=order,
                )
            )
        category = _canonical_category_id(
            sequence.get("feature_path", []), repository, "parameter_panel"
        )
        group = repository._register_group(
            AssetGroupDraft("process", "parameter_callout_sequence", category, members)
        )
        report["groups"].append(
            {
                "sequence_id": sequence.get("sequence_id"),
                "pattern_id": "parameter_callout_sequence",
                "group_ref": group.group_ref,
            }
        )


def _register_remaining_workflow_editor_groups(
    repository: SQLiteAssetRepository,
    workflow_index: dict[str, Any],
    registered_editor_keys: set[tuple[str, str, str]],
    report: dict[str, Any],
) -> None:
    by_flow: dict[str, WorkflowFlow] = workflow_index["by_flow"]
    for flow_id, bucket in by_flow.items():
        assert bucket.seen_roles is not None
        started = bool(bucket.seen_roles & {"page", "editor_page", "edited_result", "modal"})
        complete = bucket.source_result and bucket.editor_page and bucket.edited_result
        if complete:
            key = (bucket.source_result, bucket.editor_page, bucket.edited_result)
            if key in registered_editor_keys:
                continue
            if not bucket.category:
                raise ValueError(f"workflow {flow_id} missing category for editor_sequence")
            category = _canonical_category_id(
                bucket.category.split("/"), repository, "result_image"
            )
            members = [
                AssetGroupMember(
                    member_key="source_result",
                    asset_role="result_image",
                    asset_ref=bucket.source_result,
                    order=1,
                ),
                AssetGroupMember(
                    member_key="editor_page",
                    asset_role="editor_page",
                    asset_ref=bucket.editor_page,
                    order=2,
                ),
                AssetGroupMember(
                    member_key="edited_result",
                    asset_role="edited_result",
                    asset_ref=bucket.edited_result,
                    order=3,
                ),
            ]
            group = repository._register_group(
                AssetGroupDraft("process", "editor_sequence", category, members)
            )
            registered_editor_keys.add(key)
            report["groups"].append(
                {"workflow_id": flow_id, "pattern_id": "editor_sequence", "group_ref": group.group_ref}
            )
        elif started and flow_id.startswith("editor_flow_"):
            raise ValueError(
                f"workflow {flow_id} incomplete editor_sequence "
                f"(source={bucket.source_result}, editor={bucket.editor_page}, edited={bucket.edited_result})"
            )


def _bind_configured_assets(repository: SQLiteAssetRepository, report: dict[str, Any]) -> None:
    logos = [
        asset
        for asset in repository.query_assets(AssetQuery(asset_roles=("brand_logo",), active_only=True))
        if asset.filename == "柯幻熊猫_LOGO.png"
    ]
    outros = repository.query_assets(AssetQuery(asset_roles=("outro",), active_only=True))
    if len(logos) != 1:
        raise ValueError(f"expected exactly one official brand logo, found {len(logos)}")
    if len(outros) != 1:
        raise ValueError(f"expected exactly one outro asset, found {len(outros)}")
    now = datetime.now(timezone.utc).isoformat()
    repository.connection.execute(
        "INSERT INTO configured_asset_bindings VALUES (?,?,?) "
        "ON CONFLICT(config_key) DO UPDATE SET asset_ref=excluded.asset_ref, updated_at=excluded.updated_at",
        ("default_brand_logo", logos[0].asset_ref, now),
    )
    repository.connection.execute(
        "INSERT INTO configured_asset_bindings VALUES (?,?,?) "
        "ON CONFLICT(config_key) DO UPDATE SET asset_ref=excluded.asset_ref, updated_at=excluded.updated_at",
        ("default_outro", outros[0].asset_ref, now),
    )
    report["bindings"] = {
        "default_brand_logo": logos[0].asset_ref,
        "default_outro": outros[0].asset_ref,
    }


def audit_repository(repository: SQLiteAssetRepository) -> dict[str, Any]:
    failures: list[str] = []
    assets = repository.query_assets(AssetQuery(active_only=False))
    assets_by_ref = {asset.asset_ref: asset for asset in assets}
    for asset in assets:
        try:
            info = repository.object_store.inspect(asset.object_key)
        except Exception as exc:  # noqa: BLE001 - audit collects failures
            failures.append(f"{asset.asset_ref}: object missing ({exc})")
            continue
        if info.content_sha256 != asset.content_sha256:
            failures.append(f"{asset.asset_ref}: hash drift")
        try:
            validate_asset_against_registry(asset, repository.registry)
        except Exception as exc:  # noqa: BLE001 - audit collects failures
            failures.append(f"{asset.asset_ref}: registry validation failed ({exc})")
        if asset.lineage:
            for parent in asset.lineage.parent_asset_refs:
                if parent not in assets_by_ref:
                    failures.append(f"{asset.asset_ref}: missing parent {parent}")
        if asset.superseded_by is not None and asset.superseded_by not in assets_by_ref:
            failures.append(f"{asset.asset_ref}: missing superseding asset {asset.superseded_by}")
    failures.extend(
        _cycle_failures(
            "lineage",
            {asset.asset_ref: list(asset.lineage.parent_asset_refs) if asset.lineage else [] for asset in assets},
        )
    )
    failures.extend(
        _cycle_failures(
            "asset supersede",
            {asset.asset_ref: [asset.superseded_by] if asset.superseded_by else [] for asset in assets},
        )
    )

    groups = repository.query_groups(GroupQuery(active_only=False))
    groups_by_ref = {group.group_ref: group for group in groups}
    for group in groups:
        for member in group.members:
            if member.asset_ref not in assets_by_ref:
                failures.append(f"{group.group_ref}: missing member {member.asset_ref}")
        if group.superseded_by is not None and group.superseded_by not in groups_by_ref:
            failures.append(f"{group.group_ref}: missing superseding group {group.superseded_by}")
        try:
            validate_group_against_assets(group, assets_by_ref, repository.registry)
        except Exception as exc:  # noqa: BLE001 - audit collects failures
            failures.append(f"{group.group_ref}: group validation failed ({exc})")
    failures.extend(
        _cycle_failures(
            "group supersede",
            {group.group_ref: [group.superseded_by] if group.superseded_by else [] for group in groups},
        )
    )

    configured_entries = {
        entry.id: entry
        for entry in repository.registry.registry("configured_asset").entries
        if entry.enabled
    }
    binding_rows = repository.connection.execute(
        "SELECT config_key,asset_ref FROM configured_asset_bindings ORDER BY config_key"
    ).fetchall()
    bindings = {row["config_key"]: row["asset_ref"] for row in binding_rows}
    for key in sorted(set(bindings) - set(configured_entries)):
        failures.append(f"configured binding uses unknown or disabled key: {key}")
    for key in sorted(configured_entries):
        asset_ref = bindings.get(key)
        if asset_ref is None:
            failures.append(f"configured binding missing: {key}")
            continue
        try:
            repository.validate_configured_asset_binding(key, asset_ref)
        except Exception as exc:  # noqa: BLE001 - audit collects failures
            failures.append(f"configured binding invalid: {key} -> {asset_ref} ({exc})")
    return {"ok": not failures, "asset_count": len(assets), "group_count": len(groups), "failures": failures}


def _cycle_failures(label: str, edges: dict[str, list[str]]) -> list[str]:
    state: dict[str, int] = {}
    failures: list[str] = []

    for root in sorted(edges):
        if state.get(root) == 2:
            continue
        state[root] = 1
        path = [root]
        active_index = {root: 0}
        stack = [(root, iter(edges.get(root, [])))]
        while stack:
            node, targets = stack[-1]
            try:
                target = next(targets)
            except StopIteration:
                stack.pop()
                state[node] = 2
                active_index.pop(node, None)
                path.pop()
                continue
            if target not in edges:
                continue
            target_state = state.get(target, 0)
            if target_state == 0:
                state[target] = 1
                active_index[target] = len(path)
                path.append(target)
                stack.append((target, iter(edges.get(target, []))))
            elif target_state == 1:
                cycle = path[active_index[target] :] + [target]
                message = f"{label} cycle: {' -> '.join(cycle)}"
                if message not in failures:
                    failures.append(message)
    return failures

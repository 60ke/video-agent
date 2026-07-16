from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

from video_agent.contracts import Asset
from video_agent.io import sha256_json


def _sort_key(asset: Asset) -> tuple[str, str, str]:
    return (
        PurePosixPath(asset.path.replace("\\", "/")).as_posix().casefold(),
        asset.filename.casefold(),
        asset.asset_id,
    )


@dataclass(frozen=True)
class AIAssetIndex:
    """Stable, run-scoped references used in model prompts instead of hash IDs."""

    assets_by_ref: dict[str, Asset]

    @classmethod
    def build(cls, assets: Iterable[Asset]) -> "AIAssetIndex":
        ordered = sorted(assets, key=_sort_key)
        width = max(4, len(str(len(ordered))))
        return cls(
            assets_by_ref={f"A{index:0{width}d}": asset for index, asset in enumerate(ordered, start=1)}
        )

    @property
    def refs(self) -> set[str]:
        return set(self.assets_by_ref)

    def asset(self, asset_ref: str) -> Asset:
        try:
            return self.assets_by_ref[asset_ref]
        except KeyError as exc:
            raise ValueError(f"AI returned unknown asset_ref: {asset_ref}") from exc

    def refs_for_asset_id(self, asset_id: str) -> list[str]:
        return [ref for ref, asset in self.assets_by_ref.items() if asset.asset_id == asset_id]

    def ref_for_asset(self, asset: Asset) -> str:
        for ref, candidate in self.assets_by_ref.items():
            if candidate is asset or (
                candidate.asset_id == asset.asset_id
                and candidate.path == asset.path
                and candidate.filename == asset.filename
            ):
                return ref
        raise ValueError(f"asset is absent from AI asset index: {asset.path}")

    def compact_table(self, assets: Iterable[Asset]) -> dict[str, Any]:
        allowed = {(asset.asset_id, asset.path, asset.filename) for asset in assets}
        fields = [
            "asset_ref",
            "filename",
            "semantic_path",
            "role",
            "orientation",
            "evidence_class",
            "claims",
            "tags",
            "origin",
            "path",
            "parent_asset_refs",
        ]
        rows: list[list[Any]] = []
        for asset_ref, asset in self.assets_by_ref.items():
            if (asset.asset_id, asset.path, asset.filename) not in allowed:
                continue
            if not asset.production_eligible or asset.quality.status == "rejected":
                continue
            if not asset.width or not asset.height:
                orientation = "unknown"
            elif asset.width / asset.height >= 1.2:
                orientation = "landscape"
            elif asset.width / asset.height <= 0.82:
                orientation = "portrait"
            else:
                orientation = "square"
            parent_refs = sorted(
                {
                    ref
                    for parent_id in asset.provenance.parent_asset_ids
                    for ref in self.refs_for_asset_id(parent_id)
                }
            )
            rows.append(
                [
                    asset_ref,
                    asset.filename,
                    asset.semantic_path,
                    asset.role,
                    orientation,
                    asset.evidence_class.value,
                    asset.claims,
                    asset.tags,
                    asset.provenance.origin,
                    asset.path,
                    parent_refs,
                ]
            )
        return {"fields": fields, "rows": rows}

    def manifest(self) -> dict[str, Any]:
        entries = [
            {
                "asset_ref": asset_ref,
                "asset_id": asset.asset_id,
                "filename": asset.filename,
                "path": asset.path,
                "semantic_path": asset.semantic_path,
                "role": asset.role,
            }
            for asset_ref, asset in self.assets_by_ref.items()
        ]
        return {
            "schema_version": 1,
            "reference_format": "A + zero-padded run-scoped sequence",
            "entries": entries,
            "index_sha256": sha256_json(entries),
        }


def translate_relationships_for_ai(
    relationships: Iterable[dict[str, Any]], asset_index: AIAssetIndex
) -> list[dict[str, Any]]:
    translated: list[dict[str, Any]] = []
    for relationship in relationships:
        item = dict(relationship)
        valid = True
        for key, value in list(item.items()):
            if not key.endswith("_asset_id") or not isinstance(value, str) or not value:
                continue
            refs = asset_index.refs_for_asset_id(value)
            if not refs:
                valid = False
                break
            item[key] = refs[0]
        if valid:
            translated.append(item)
    return translated


def resolve_ai_asset_refs(result: dict[str, Any], asset_index: AIAssetIndex) -> dict[str, Any]:
    """Resolve known AI response reference fields back to internal catalog IDs."""

    import json

    resolved = json.loads(json.dumps(result, ensure_ascii=False))
    for scene in resolved.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        bindings = scene.get("asset_bindings")
        if isinstance(bindings, dict):
            scene["asset_bindings"] = {
                key: asset_index.asset(value).asset_id
                for key, value in bindings.items()
                if isinstance(value, str) and value
            }
        gallery = scene.get("gallery_items")
        if isinstance(gallery, list):
            for item in gallery:
                if isinstance(item, dict) and isinstance(item.get("asset_id"), str):
                    item["asset_id"] = asset_index.asset(item["asset_id"]).asset_id
    for request in resolved.get("derivation_requests", []):
        if not isinstance(request, dict):
            continue
        source_ref = request.get("source_asset_id")
        if isinstance(source_ref, str) and source_ref:
            request["source_asset_id"] = asset_index.asset(source_ref).asset_id
        related_refs = request.get("related_asset_ids")
        if isinstance(related_refs, list):
            request["related_asset_ids"] = [
                asset_index.asset(ref).asset_id for ref in related_refs if isinstance(ref, str) and ref
            ]
    return resolved

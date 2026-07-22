from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from video_agent.registries import CapabilityRegistrySnapshot


def scope_categories_payload(registry: CapabilityRegistrySnapshot) -> list[dict[str, Any]]:
    return [
        {
            "category_id": item.category_id,
            "display_name": item.name,
            "aliases": item.aliases,
        }
        for item in registry.categories
        if item.enabled and item.scope_eligible
    ]


def scene_registry_payload(registry: CapabilityRegistrySnapshot) -> dict[str, Any]:
    return {
        "categories": [
            {"category_id": item.category_id, "display_name": item.name, "aliases": item.aliases}
            for item in registry.categories
            if item.enabled
        ],
        "asset_roles": [
            item for item in _items(registry.asset_roles)
            if item["item_id"] != "outro"
        ],
        "visual_structures": _items(registry.visual_structures),
        "operation_intents": _items(registry.operation_intents),
        "claims": _items(registry.claims),
        "group_types": _items(registry.group_types),
        "relation_patterns": [
            {
                "pattern_id": pattern.item_id,
                "group_type": pattern.group_type,
                "members": [member.model_dump(mode="json") for member in pattern.members],
            }
            for pattern in registry.relation_patterns
            if pattern.enabled
        ],
        "configured_assets": [],
    }


def scene_material_availability_payload(assets: Iterable[Any]) -> dict[str, Any]:
    """Project active repository facts for semantic planning without file picks."""

    grouped: dict[tuple[str, str | None], list[Any]] = defaultdict(list)
    for asset in assets:
        status = getattr(getattr(asset, "status", None), "value", getattr(asset, "status", None))
        if status != "active":
            continue
        grouped[(str(asset.asset_role), asset.category_id)].append(asset)

    available: list[dict[str, Any]] = []
    for (asset_role, category_id), records in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1] or "")
    ):
        ordered = sorted(records, key=lambda asset: (asset.filename, asset.object_key))
        available.append(
            {
                "asset_role": asset_role,
                "category_id": category_id,
                "count": len(ordered),
                "orientations": sorted(
                    {
                        getattr(getattr(asset, "orientation", None), "value", str(asset.orientation))
                        for asset in ordered
                    }
                ),
                "examples": [
                    {
                        "filename": asset.filename,
                        "object_key": asset.object_key,
                        "description": asset.description,
                    }
                    for asset in ordered[:3]
                ],
            }
        )
    return {
        "source": "v4_active_asset_repository",
        "role_category_availability": available,
    }


def _items(items) -> list[dict[str, str | bool]]:
    return [
        {
            "item_id": item.item_id,
            "requires_category": item.requires_category,
        }
        for item in items
        if item.enabled
    ]

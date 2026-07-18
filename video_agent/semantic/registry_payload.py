from __future__ import annotations

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
        "asset_roles": _items(registry.asset_roles),
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
        "configured_assets": _items(registry.configured_assets),
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

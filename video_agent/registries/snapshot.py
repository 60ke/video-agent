from __future__ import annotations

from pathlib import Path

from pydantic import Field

from video_agent.contracts.v4.common import V4Contract

from .hub import CapabilityRegistryHub


class CategoryDefinition(V4Contract):
    category_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True
    scope_eligible: bool = True


class RegistryDefinition(V4Contract):
    item_id: str = Field(min_length=1)
    enabled: bool = True
    requires_category: bool = False


class CapabilityRegistrySnapshot(V4Contract):
    categories: list[CategoryDefinition]
    asset_roles: list[RegistryDefinition]
    visual_structures: list[RegistryDefinition]
    operation_intents: list[RegistryDefinition]
    claims: list[RegistryDefinition]
    group_types: list[RegistryDefinition]
    configured_assets: list[RegistryDefinition]
    registry_versions: dict[str, str] = Field(default_factory=dict)
    registry_hashes: dict[str, str] = Field(default_factory=dict)

    def category(self, category_id: str) -> CategoryDefinition | None:
        return next((item for item in self.categories if item.category_id == category_id), None)

    def item(self, registry_name: str, item_id: str) -> RegistryDefinition | None:
        items = getattr(self, registry_name)
        return next((item for item in items if item.item_id == item_id), None)


def load_bootstrap_registry(repo_root: Path) -> CapabilityRegistrySnapshot:
    hub = CapabilityRegistryHub.load(repo_root / "config" / "registries" / "v4")
    frozen = hub.snapshot()
    categories = [
        CategoryDefinition(
            category_id=entry.id,
            name=entry.display_name,
            aliases=entry.aliases,
            enabled=entry.enabled,
            scope_eligible=entry.scope_eligible,
        )
        for entry in hub.registry("category").entries
    ]

    mapping = {
        "asset_roles": "asset_role",
        "visual_structures": "visual_structure",
        "operation_intents": "operation_intent",
        "claims": "claim",
        "group_types": "group_type",
        "configured_assets": "configured_asset",
    }
    projected: dict[str, list[RegistryDefinition]] = {}
    for field_name, registry_id in mapping.items():
        projected[field_name] = [
            RegistryDefinition(
                item_id=entry.id,
                enabled=entry.enabled,
                requires_category=bool(getattr(entry, "requires_category", False)),
            )
            for entry in hub.registry(registry_id).entries
        ]
    return CapabilityRegistrySnapshot(
        categories=categories,
        **projected,
        registry_versions={item.registry_id: item.version for item in frozen.registries},
        registry_hashes={item.registry_id: item.content_sha256 for item in frozen.registries},
    )

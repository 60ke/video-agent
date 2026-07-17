from __future__ import annotations

from pydantic import Field

from video_agent.contracts.v4.common import V4Contract


class CategoryDefinition(V4Contract):
    category_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = []
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

    def category(self, category_id: str) -> CategoryDefinition | None:
        return next((item for item in self.categories if item.category_id == category_id), None)

    def item(self, registry_name: str, item_id: str) -> RegistryDefinition | None:
        items = getattr(self, registry_name)
        return next((item for item in items if item.item_id == item_id), None)

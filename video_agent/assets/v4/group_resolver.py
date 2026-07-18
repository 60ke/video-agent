from __future__ import annotations

from video_agent.contracts.v4 import AssetGroup, AssetGroupMember

from .stage4_errors import Stage4Error


class GroupBindingTable:
    def __init__(self) -> None:
        self._bindings: dict[str, str] = {}
        self._meta: dict[str, tuple[str, str, str]] = {}

    @property
    def bindings(self) -> dict[str, str]:
        return dict(self._bindings)

    def get(self, alias: str) -> str | None:
        return self._bindings.get(alias)

    def bind(
        self,
        alias: str,
        group: AssetGroup,
        *,
        scene_id: str,
        slot_id: str,
    ) -> None:
        existing = self._bindings.get(alias)
        meta = (group.group_type, group.pattern_id, group.category_id)
        if existing is None:
            self._bindings[alias] = group.group_ref
            self._meta[alias] = meta
            return
        if existing != group.group_ref:
            raise Stage4Error(
                "incomplete_asset_group",
                f"alias {alias} already bound to {existing}, refused {group.group_ref}",
                scene_id=scene_id,
                slot_id=slot_id,
            )
        if self._meta[alias] != meta:
            raise Stage4Error(
                "incomplete_asset_group",
                f"alias {alias} meta mismatch for rebound group",
                scene_id=scene_id,
                slot_id=slot_id,
            )

    def require_compatible(
        self,
        alias: str,
        *,
        group_type: str,
        pattern_id: str,
        category_id: str | None,
        scene_id: str,
        slot_id: str,
    ) -> str:
        group_ref = self._bindings.get(alias)
        if group_ref is None:
            raise Stage4Error(
                "invalid_slot_source",
                f"group alias {alias} is not bound",
                scene_id=scene_id,
                slot_id=slot_id,
            )
        bound_type, bound_pattern, bound_category = self._meta[alias]
        if bound_type != group_type or bound_pattern != pattern_id:
            raise Stage4Error(
                "invalid_slot_source",
                f"alias {alias} bound as {bound_type}/{bound_pattern}, requested {group_type}/{pattern_id}",
                scene_id=scene_id,
                slot_id=slot_id,
            )
        if category_id is not None and bound_category != category_id:
            raise Stage4Error(
                "invalid_slot_source",
                f"alias {alias} category mismatch: bound={bound_category} requested={category_id}",
                scene_id=scene_id,
                slot_id=slot_id,
            )
        return group_ref


def member_from_group(
    group: AssetGroup,
    member_key: str,
    *,
    scene_id: str,
    slot_id: str,
) -> AssetGroupMember:
    for member in group.members:
        if member.member_key == member_key:
            return member
    raise Stage4Error(
        "incomplete_asset_group",
        f"group {group.group_ref} missing member_key={member_key}",
        scene_id=scene_id,
        slot_id=slot_id,
    )

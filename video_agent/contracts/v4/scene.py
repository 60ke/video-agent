from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import V4Contract


class AssetQuerySource(V4Contract):
    kind: Literal["asset_query"]


class AssetGroupQuerySource(V4Contract):
    kind: Literal["asset_group_query"]
    group_alias: str = Field(min_length=1)
    group_type: str = Field(min_length=1)
    pattern_id: str = Field(min_length=1)
    member_key: str = Field(min_length=1)


class GroupMemberSource(V4Contract):
    kind: Literal["group_member"]
    group_alias: str = Field(min_length=1)
    group_type: str = Field(min_length=1)
    pattern_id: str = Field(min_length=1)
    member_key: str = Field(min_length=1)


class SceneInputSource(V4Contract):
    kind: Literal["scene_input"]
    input_name: str = Field(min_length=1)


class RelationFromInputSource(V4Contract):
    kind: Literal["relation_from_input"]
    input_name: str = Field(min_length=1)
    group_alias: str = Field(min_length=1)
    group_type: str = Field(min_length=1)
    pattern_id: str = Field(min_length=1)
    member_key: str = Field(min_length=1)


class ConfiguredAssetSource(V4Contract):
    kind: Literal["configured_asset"]
    config_key: str = Field(min_length=1)


SlotSource = Annotated[
    AssetQuerySource | AssetGroupQuerySource | GroupMemberSource | SceneInputSource | RelationFromInputSource | ConfiguredAssetSource,
    Field(discriminator="kind"),
]


class MaterialSlot(V4Contract):
    slot_id: str = Field(min_length=1)
    anchor_phrase: str = Field(min_length=1)
    entry_policy: Literal["scene_start", "phrase_start"]
    hold_policy: Literal["until_next_slot", "scene_end"]
    category_id: str | None
    asset_role: str = Field(min_length=1)
    source: SlotSource
    subtitle_emphasis: Literal["none", "keyword"]


class SceneInput(V4Contract):
    input_name: str = Field(min_length=1)
    from_scene: str = Field(min_length=1)
    from_output: str = Field(min_length=1)
    required: bool


class SceneOutput(V4Contract):
    output_name: str = Field(min_length=1)
    bound_slot: str = Field(min_length=1)
    asset_role: str = Field(min_length=1)


class OperationEvent(V4Contract):
    event_id: str = Field(min_length=1)
    phrase: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    target_slot: str | None


class SceneClaim(V4Contract):
    claim_id: str = Field(min_length=1)
    phrase: str = Field(min_length=1)
    quantifier: Literal["any", "all"]
    supporting_slots: list[str] = Field(min_length=1)
    evidence_window: Literal["anchor", "scene_span"]


class SemanticScene(V4Contract):
    scene_id: str = Field(min_length=1)
    order: int = Field(ge=1)
    text: str = Field(min_length=1)
    visual_structure: str = Field(min_length=1)
    slots: list[MaterialSlot]
    events: list[OperationEvent]
    inputs: list[SceneInput]
    outputs: list[SceneOutput]
    claims: list[SceneClaim]
    no_asset: bool


class SceneSemanticPlan(V4Contract):
    scenes: list[SemanticScene] = Field(min_length=1)

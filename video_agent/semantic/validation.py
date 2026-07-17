from __future__ import annotations

from dataclasses import dataclass

from video_agent.contracts.v4.common import (
    DomainValidationError,
    ValidationIssue,
    normalize_frozen_text,
)
from video_agent.contracts.v4.scene import (
    AssetGroupQuerySource,
    ConfiguredAssetSource,
    GroupMemberSource,
    RelationFromInputSource,
    SceneInputSource,
    SceneSemanticPlan,
    SemanticScene,
)
from video_agent.contracts.v4.scope import VideoScope
from video_agent.registries import CapabilityRegistrySnapshot


@dataclass(frozen=True)
class SceneTextSpan:
    scene_id: str
    start: int
    end: int


@dataclass(frozen=True)
class SceneValidationResult:
    scene_spans: tuple[SceneTextSpan, ...]


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, message=message)


def _active_item(
    registry: CapabilityRegistrySnapshot,
    registry_name: str,
    item_id: str,
) -> bool:
    item = registry.item(registry_name, item_id)
    return bool(item and item.enabled)


def _ensure_unique(
    values: list[str],
    *,
    path: str,
    label: str,
    issues: list[ValidationIssue],
) -> None:
    seen: set[str] = set()
    for index, value in enumerate(values):
        if value in seen:
            issues.append(_issue("duplicate_id", f"{path}[{index}]", f"duplicate {label}: {value}"))
        seen.add(value)


def validate_video_scope(
    scope: VideoScope,
    *,
    frozen_narration: str,
    registry: CapabilityRegistrySnapshot,
    primary_required: bool = False,
) -> None:
    issues: list[ValidationIssue] = []
    category_ids = [item.category_id for item in scope.categories]
    _ensure_unique(category_ids, path="categories", label="category_id", issues=issues)

    primary_count = sum(1 for item in scope.categories if item.is_primary)
    if scope.scope_mode == "single_category":
        if len(scope.categories) != 1:
            issues.append(_issue("scope_cardinality", "categories", "single_category requires exactly one category"))
        if primary_count != 1:
            issues.append(_issue("primary_cardinality", "categories", "single_category requires one primary category"))
    else:
        if len(scope.categories) < 2:
            issues.append(_issue("scope_cardinality", "categories", "multi_category requires at least two categories"))
        if primary_count > 1:
            issues.append(_issue("primary_cardinality", "categories", "multi_category allows at most one primary category"))
        if primary_required and primary_count != 1:
            issues.append(_issue("primary_required", "categories", "the narration requires one primary category"))

    normalized_narration = normalize_frozen_text(frozen_narration)
    for index, item in enumerate(scope.categories):
        definition = registry.category(item.category_id)
        if not definition or not definition.enabled or not definition.scope_eligible:
            issues.append(
                _issue(
                    "unknown_or_disabled_category",
                    f"categories[{index}].category_id",
                    f"category is not an enabled scope category: {item.category_id}",
                )
            )
        for phrase_index, phrase in enumerate(item.mention_phrases):
            if normalize_frozen_text(phrase) not in normalized_narration:
                issues.append(
                    _issue(
                        "phrase_not_in_narration",
                        f"categories[{index}].mention_phrases[{phrase_index}]",
                        f"phrase is not copied from frozen narration: {phrase}",
                    )
                )

    if issues:
        raise DomainValidationError("VideoScope/v4.1", issues)


def _validate_registry_id(
    registry: CapabilityRegistrySnapshot,
    registry_name: str,
    item_id: str,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not _active_item(registry, registry_name, item_id):
        issues.append(
            _issue(
                "unknown_or_disabled_registry_id",
                path,
                f"{registry_name} does not contain an enabled ID: {item_id}",
            )
        )


def _validate_scene(
    scene: SemanticScene,
    *,
    scene_index: int,
    earlier_scenes: dict[str, SemanticScene],
    registry: CapabilityRegistrySnapshot,
    issues: list[ValidationIssue],
) -> None:
    base = f"scenes[{scene_index}]"
    _validate_registry_id(
        registry,
        "visual_structures",
        scene.visual_structure,
        f"{base}.visual_structure",
        issues,
    )

    slot_ids = [slot.slot_id for slot in scene.slots]
    event_ids = [event.event_id for event in scene.events]
    input_names = [item.input_name for item in scene.inputs]
    output_names = [item.output_name for item in scene.outputs]
    _ensure_unique(slot_ids, path=f"{base}.slots", label="slot_id", issues=issues)
    _ensure_unique(event_ids, path=f"{base}.events", label="event_id", issues=issues)
    _ensure_unique(input_names, path=f"{base}.inputs", label="input_name", issues=issues)
    _ensure_unique(output_names, path=f"{base}.outputs", label="output_name", issues=issues)

    if scene.no_asset:
        if scene.visual_structure != "no_asset_transition":
            issues.append(_issue("invalid_no_asset", f"{base}.visual_structure", "no_asset requires no_asset_transition"))
        for field_name in ("slots", "inputs", "outputs", "claims"):
            if getattr(scene, field_name):
                issues.append(_issue("invalid_no_asset", f"{base}.{field_name}", f"no_asset requires empty {field_name}"))
    elif not scene.slots:
        issues.append(_issue("missing_slots", f"{base}.slots", "a material scene requires at least one slot"))

    input_map = {item.input_name: item for item in scene.inputs}
    slot_map = {slot.slot_id: slot for slot in scene.slots}
    known_groups: dict[str, str] = {}

    for slot_index, slot in enumerate(scene.slots):
        slot_path = f"{base}.slots[{slot_index}]"
        if normalize_frozen_text(slot.anchor_phrase) not in normalize_frozen_text(scene.text):
            issues.append(_issue("phrase_not_in_scene", f"{slot_path}.anchor_phrase", "anchor phrase is not in scene text"))

        role = registry.item("asset_roles", slot.asset_role)
        if not role or not role.enabled:
            issues.append(_issue("unknown_or_disabled_registry_id", f"{slot_path}.asset_role", f"unknown asset role: {slot.asset_role}"))
        elif role.requires_category and slot.category_id is None:
            issues.append(_issue("category_required", f"{slot_path}.category_id", f"asset role requires a category: {slot.asset_role}"))

        if slot.category_id is not None:
            category = registry.category(slot.category_id)
            if not category or not category.enabled:
                issues.append(_issue("unknown_or_disabled_category", f"{slot_path}.category_id", f"unknown category: {slot.category_id}"))

        source = slot.source
        if isinstance(source, (AssetGroupQuerySource, GroupMemberSource, RelationFromInputSource)):
            _validate_registry_id(registry, "group_types", source.group_type, f"{slot_path}.source.group_type", issues)
        if isinstance(source, AssetGroupQuerySource):
            previous_type = known_groups.get(source.group_alias)
            if previous_type and previous_type != source.group_type:
                issues.append(_issue("group_type_mismatch", f"{slot_path}.source", "group alias changed type"))
            known_groups[source.group_alias] = source.group_type
        elif isinstance(source, GroupMemberSource):
            if known_groups.get(source.group_alias) != source.group_type:
                issues.append(_issue("unknown_group_alias", f"{slot_path}.source.group_alias", "group_member must reference an earlier group declaration in the scene"))
        elif isinstance(source, (SceneInputSource, RelationFromInputSource)):
            if source.input_name not in input_map:
                issues.append(_issue("unknown_scene_input", f"{slot_path}.source.input_name", f"unknown input: {source.input_name}"))
            if isinstance(source, RelationFromInputSource):
                previous_type = known_groups.get(source.group_alias)
                if previous_type and previous_type != source.group_type:
                    issues.append(_issue("group_type_mismatch", f"{slot_path}.source", "group alias changed type"))
                known_groups[source.group_alias] = source.group_type
        elif isinstance(source, ConfiguredAssetSource):
            _validate_registry_id(registry, "configured_assets", source.config_key, f"{slot_path}.source.config_key", issues)

    for input_index, scene_input in enumerate(scene.inputs):
        input_path = f"{base}.inputs[{input_index}]"
        source_scene = earlier_scenes.get(scene_input.from_scene)
        if not source_scene:
            issues.append(_issue("invalid_scene_dependency", f"{input_path}.from_scene", "input must reference an earlier scene"))
            continue
        source_outputs = {item.output_name for item in source_scene.outputs}
        if scene_input.from_output not in source_outputs:
            issues.append(_issue("unknown_scene_output", f"{input_path}.from_output", f"unknown output on {scene_input.from_scene}: {scene_input.from_output}"))

    for output_index, output in enumerate(scene.outputs):
        output_path = f"{base}.outputs[{output_index}]"
        bound_slot = slot_map.get(output.bound_slot)
        if not bound_slot:
            issues.append(_issue("unknown_slot", f"{output_path}.bound_slot", f"unknown slot: {output.bound_slot}"))
        elif output.asset_role != bound_slot.asset_role:
            issues.append(_issue("output_role_mismatch", f"{output_path}.asset_role", "output role must match its bound slot"))
        _validate_registry_id(registry, "asset_roles", output.asset_role, f"{output_path}.asset_role", issues)

    for event_index, event in enumerate(scene.events):
        event_path = f"{base}.events[{event_index}]"
        if normalize_frozen_text(event.phrase) not in normalize_frozen_text(scene.text):
            issues.append(_issue("phrase_not_in_scene", f"{event_path}.phrase", "event phrase is not in scene text"))
        _validate_registry_id(registry, "operation_intents", event.intent, f"{event_path}.intent", issues)
        if event.target_slot is not None and event.target_slot not in slot_map:
            issues.append(_issue("unknown_slot", f"{event_path}.target_slot", f"unknown slot: {event.target_slot}"))

    for claim_index, claim in enumerate(scene.claims):
        claim_path = f"{base}.claims[{claim_index}]"
        if normalize_frozen_text(claim.phrase) not in normalize_frozen_text(scene.text):
            issues.append(_issue("phrase_not_in_scene", f"{claim_path}.phrase", "claim phrase is not in scene text"))
        _validate_registry_id(registry, "claims", claim.claim_id, f"{claim_path}.claim_id", issues)
        for supporting_slot in claim.supporting_slots:
            if supporting_slot not in slot_map:
                issues.append(_issue("unknown_slot", f"{claim_path}.supporting_slots", f"unknown slot: {supporting_slot}"))

    if scene.visual_structure == "gallery":
        _validate_gallery(scene, base, issues)
    elif scene.visual_structure in {"sequence", "comparison"}:
        relation_kinds = {"asset_group_query", "group_member", "scene_input", "relation_from_input"}
        if any(slot.source.kind not in relation_kinds for slot in scene.slots):
            issues.append(_issue("unrelated_structured_slots", f"{base}.slots", f"{scene.visual_structure} cannot use unrelated asset queries"))
        if not any(slot.source.kind in {"asset_group_query", "group_member", "relation_from_input"} for slot in scene.slots):
            issues.append(_issue("missing_relation_source", f"{base}.slots", f"{scene.visual_structure} requires a group or relation source"))


def _validate_gallery(scene: SemanticScene, base: str, issues: list[ValidationIssue]) -> None:
    cursor = 0
    normalized_text = normalize_frozen_text(scene.text)
    for index, slot in enumerate(scene.slots):
        slot_path = f"{base}.slots[{index}]"
        position = normalized_text.find(normalize_frozen_text(slot.anchor_phrase), cursor)
        if position < 0:
            issues.append(_issue("gallery_anchor_order", f"{slot_path}.anchor_phrase", "gallery anchors must follow narration order"))
        else:
            cursor = position + len(normalize_frozen_text(slot.anchor_phrase))
        expected_hold = "scene_end" if index == len(scene.slots) - 1 else "until_next_slot"
        if slot.hold_policy != expected_hold:
            issues.append(_issue("gallery_hold_policy", f"{slot_path}.hold_policy", f"expected {expected_hold}"))
        if slot.entry_policy != "phrase_start":
            issues.append(_issue("gallery_entry_policy", f"{slot_path}.entry_policy", "gallery slots must enter at phrase_start"))


def validate_scene_semantic_plan(
    plan: SceneSemanticPlan,
    *,
    frozen_narration: str,
    registry: CapabilityRegistrySnapshot,
) -> SceneValidationResult:
    issues: list[ValidationIssue] = []
    ordered = sorted(plan.scenes, key=lambda scene: scene.order)
    if [scene.order for scene in ordered] != list(range(1, len(ordered) + 1)):
        issues.append(_issue("non_contiguous_order", "scenes", "scene order must be contiguous and start at 1"))

    scene_ids = [scene.scene_id for scene in plan.scenes]
    _ensure_unique(scene_ids, path="scenes", label="scene_id", issues=issues)

    combined = "".join(scene.text for scene in ordered)
    if normalize_frozen_text(combined) != normalize_frozen_text(frozen_narration):
        issues.append(_issue("narration_coverage", "scenes", "ordered scene text must exactly cover frozen narration"))

    spans: list[SceneTextSpan] = []
    offset = 0
    earlier_scenes: dict[str, SemanticScene] = {}
    for scene_index, scene in enumerate(ordered):
        normalized_scene = normalize_frozen_text(scene.text)
        spans.append(SceneTextSpan(scene_id=scene.scene_id, start=offset, end=offset + len(normalized_scene)))
        offset += len(normalized_scene)
        _validate_scene(
            scene,
            scene_index=scene_index,
            earlier_scenes=earlier_scenes,
            registry=registry,
            issues=issues,
        )
        earlier_scenes[scene.scene_id] = scene

    if issues:
        raise DomainValidationError("SceneSemanticPlan/v4.1", issues)
    return SceneValidationResult(scene_spans=tuple(spans))

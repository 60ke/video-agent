"""Deterministic structural repairs for SceneSemanticPlan drafts.

Unit2 allows prompt + validator + deterministic correction. These repairs fix
common model mistakes that violate relation-boundary rules without hardcoding
Stage0 case IDs or frozen narration branches.
"""

from __future__ import annotations

import copy
from typing import Any

from video_agent.contracts.v4 import SceneSemanticPlan


RELATION_KINDS = frozenset({"asset_group_query", "group_member", "scene_input", "relation_from_input"})
INDEPENDENT_KINDS = frozenset({"asset_query", "configured_asset"})


def apply_deterministic_scene_repairs(plan: SceneSemanticPlan) -> SceneSemanticPlan:
    payload = plan.model_dump(mode="json")
    payload = repair_scene_plan_payload(payload)
    return SceneSemanticPlan.model_validate(payload)


def repair_scene_plan_payload(payload: dict[str, Any]) -> dict[str, Any]:
    scenes = [copy.deepcopy(scene) for scene in payload.get("scenes") or []]
    repaired: list[dict[str, Any]] = []

    for scene in scenes:
        repaired.extend(_expand_scene(scene))

    # Re-number orders/ids, then rewrite input.from_scene when an output moved.
    id_remap: dict[str, str] = {}
    old_ids = [str(scene.get("scene_id") or "") for scene in repaired]
    for index, scene in enumerate(repaired, start=1):
        old_id = str(scene.get("scene_id") or f"s{index:03d}")
        new_id = f"s{index:03d}"
        id_remap[old_id] = new_id
        scene["scene_id"] = new_id
        scene["order"] = index

    # Map (old_scene, output_name) -> new scene id. Result splits use "<id>__result".
    owned: dict[tuple[str, str], str] = {}
    for old_id, scene in zip(old_ids, repaired, strict=True):
        new_id = str(scene["scene_id"])
        for output in scene.get("outputs") or []:
            name = str(output.get("output_name") or "")
            owned[(old_id, name)] = new_id
            if old_id.endswith("__result"):
                owned[(old_id[: -len("__result")], name)] = new_id

    for scene in repaired:
        for item in scene.get("inputs") or []:
            from_scene = str(item.get("from_scene") or "")
            from_output = str(item.get("from_output") or "")
            key = (from_scene, from_output)
            if key in owned:
                item["from_scene"] = owned[key]
            elif from_scene in id_remap:
                item["from_scene"] = id_remap[from_scene]

    for scene in repaired:
        _repair_reference_result_plan_sources(scene)
        _repair_editor_sequence_sources(scene)
        _repair_hold_policies(scene)

    return {"scenes": repaired}


def _expand_scene(scene: dict[str, Any]) -> list[dict[str, Any]]:
    structure = scene.get("visual_structure")
    slots = list(scene.get("slots") or [])
    if structure not in {"sequence", "comparison"} or len(slots) < 2:
        return [scene]

    kinds = [str((slot.get("source") or {}).get("kind") or "") for slot in slots]
    has_relation = any(kind in RELATION_KINDS for kind in kinds)
    has_independent = any(kind in INDEPENDENT_KINDS for kind in kinds)

    # Causal reference mixes must be rewritten in-place, never split into independent queries.
    if any(slot.get("asset_role") == "reference_image" and (slot.get("source") or {}).get("kind") == "asset_query" for slot in slots) and any(
        (slot.get("source") or {}).get("pattern_id") == "reference_result_plan" for slot in slots
    ):
        _repair_reference_result_plan_sources(scene)
        return [scene]

    if not (has_relation and has_independent):
        # Still normalize pure causal/editor shapes.
        if any((slot.get("source") or {}).get("pattern_id") == "reference_result_plan" for slot in slots):
            _repair_reference_result_plan_sources(scene)
        if any((slot.get("source") or {}).get("pattern_id") == "editor_sequence" for slot in slots):
            _repair_editor_sequence_sources(scene)
        return [scene]

    first_relation = next((index for index, kind in enumerate(kinds) if kind in RELATION_KINDS), None)
    if first_relation is not None and first_relation > 0 and all(kind == "asset_query" for kind in kinds[:first_relation]):
        head_slots = slots[:first_relation]
        tail_slots = slots[first_relation:]
        head_text, tail_text = _split_text_before_phrase(
            scene.get("text") or "",
            str(tail_slots[0].get("anchor_phrase") or ""),
        )
        head = _scene_with_slots(
            scene,
            head_slots,
            text=head_text or (scene.get("text") or ""),
            structure="single",
            outputs=[],
            inputs=[],
        )
        tail = _scene_with_slots(
            scene,
            tail_slots,
            text=tail_text or (scene.get("text") or ""),
            structure=structure,
        )
        return _expand_scene(head) + _expand_scene(tail)

    last_relation = max((index for index, kind in enumerate(kinds) if kind in RELATION_KINDS), default=-1)
    trailing = slots[last_relation + 1 :]
    if (
        last_relation >= 0
        and trailing
        and all(str((slot.get("source") or {}).get("kind")) == "asset_query" for slot in trailing)
        and all(slot.get("asset_role") == "result_image" for slot in trailing)
    ):
        head_slots = slots[: last_relation + 1]
        _ensure_parameter_final_role(head_slots)
        head_text, tail_text = _split_text_before_phrase(
            scene.get("text") or "",
            str(trailing[0].get("anchor_phrase") or ""),
        )
        if not head_text or not tail_text:
            # Do not duplicate narration across scenes; leave for rebuild/validator.
            return [scene]
        result_slot = trailing[0]
        output_name = "primary_result"
        for output in scene.get("outputs") or []:
            if output.get("bound_slot") == result_slot.get("slot_id"):
                output_name = str(output.get("output_name") or output_name)
                break
        head = _scene_with_slots(
            scene,
            head_slots,
            text=head_text or (scene.get("text") or ""),
            structure="sequence",
            outputs=[],
            events=[event for event in (scene.get("events") or []) if event.get("target_slot") in {slot.get("slot_id") for slot in head_slots}],
            claims=[],
        )
        tail = _scene_with_slots(
            scene,
            trailing,
            text=tail_text or (scene.get("text") or ""),
            structure="single",
            outputs=[{"output_name": output_name, "bound_slot": result_slot.get("slot_id"), "asset_role": "result_image"}],
            events=[event for event in (scene.get("events") or []) if event.get("target_slot") == result_slot.get("slot_id")],
            claims=[
                claim
                for claim in (scene.get("claims") or [])
                if result_slot.get("slot_id") in (claim.get("supporting_slots") or [])
            ],
            inputs=[],
        )
        # Preserve old head id; mark tail so output ownership remaps away from head.
        tail["scene_id"] = f"{scene.get('scene_id')}__result"
        return [head, tail]

    if any(slot.get("asset_role") == "reference_image" and (slot.get("source") or {}).get("kind") == "asset_query" for slot in slots):
        _repair_reference_result_plan_sources(scene)
        return [scene]

    return [scene]


def _ensure_parameter_final_role(slots: list[dict[str, Any]]) -> None:
    for slot in slots:
        source = slot.get("source") or {}
        if source.get("pattern_id") == "parameter_callout_sequence" and source.get("member_key") == "final":
            slot["asset_role"] = "parameter_panel"


def _repair_reference_result_plan_sources(scene: dict[str, Any]) -> None:
    slots = scene.get("slots") or []
    if not slots:
        return
    relation_slot = next(
        (
            slot
            for slot in slots
            if (slot.get("source") or {}).get("pattern_id") == "reference_result_plan"
            and (slot.get("source") or {}).get("kind") in {"asset_group_query", "group_member", "relation_from_input"}
        ),
        None,
    )
    if relation_slot is None:
        return
    binding = relation_slot["source"]
    group_alias = binding.get("group_alias")
    group_type = binding.get("group_type") or "causal"
    pattern_id = binding.get("pattern_id")
    input_name = binding.get("input_name")
    repaired_slots: list[dict[str, Any]] = []
    first = True
    for slot in slots:
        source = dict(slot.get("source") or {})
        role = slot.get("asset_role")
        if role == "reference_image" and source.get("kind") == "asset_query":
            member_key = "reference_image"
        elif source.get("pattern_id") == "reference_result_plan":
            member_key = source.get("member_key") or role
        else:
            repaired_slots.append(slot)
            continue
        if input_name or source.get("kind") == "relation_from_input":
            source = {
                "kind": "relation_from_input",
                "input_name": source.get("input_name") or input_name,
                "group_alias": group_alias,
                "group_type": group_type,
                "pattern_id": pattern_id,
                "member_key": member_key,
            }
        else:
            source = {
                "kind": "asset_group_query" if first else "group_member",
                "group_alias": group_alias,
                "group_type": group_type,
                "pattern_id": pattern_id,
                "member_key": member_key,
            }
            first = False
        slot = dict(slot)
        slot["source"] = source
        repaired_slots.append(slot)
    scene["slots"] = repaired_slots
    if group_type == "causal":
        scene["visual_structure"] = "comparison"


def _repair_editor_sequence_sources(scene: dict[str, Any]) -> None:
    slots = scene.get("slots") or []
    if not any((slot.get("source") or {}).get("pattern_id") == "editor_sequence" for slot in slots):
        return
    inputs = scene.get("inputs") or []
    if not inputs:
        return
    input_name = str(inputs[0].get("input_name") or "")
    binding = next(
        (slot.get("source") for slot in slots if (slot.get("source") or {}).get("pattern_id") == "editor_sequence"),
        None,
    )
    if not isinstance(binding, dict):
        return
    group_alias = binding.get("group_alias")
    group_type = binding.get("group_type") or "process"
    repaired: list[dict[str, Any]] = []
    for slot in slots:
        source = dict(slot.get("source") or {})
        role = str(slot.get("asset_role") or "")
        member_key = source.get("member_key")
        if role == "result_image" and source.get("kind") in {"scene_input", "asset_query"}:
            member_key = "source_result"
        if source.get("pattern_id") == "editor_sequence" or member_key in {"source_result", "editor_page", "edited_result"} or (
            role in {"result_image", "editor_page", "edited_result"} and source.get("kind") in {"scene_input", "group_member", "relation_from_input"}
        ):
            if not member_key:
                member_key = {
                    "result_image": "source_result",
                    "editor_page": "editor_page",
                    "edited_result": "edited_result",
                }.get(role, role)
            slot = dict(slot)
            slot["source"] = {
                "kind": "relation_from_input",
                "input_name": source.get("input_name") or input_name,
                "group_alias": group_alias,
                "group_type": group_type,
                "pattern_id": "editor_sequence",
                "member_key": member_key,
            }
            if member_key == "source_result":
                slot["asset_role"] = "result_image"
            repaired.append(slot)
            continue
        repaired.append(slot)
    scene["slots"] = repaired
    scene["visual_structure"] = "sequence"


def _repair_hold_policies(scene: dict[str, Any]) -> None:
    slots = scene.get("slots") or []
    if len(slots) <= 1:
        if slots:
            slots[0]["hold_policy"] = "scene_end"
        return
    for index, slot in enumerate(slots):
        slot["hold_policy"] = "scene_end" if index == len(slots) - 1 else "until_next_slot"


def _scene_with_slots(
    scene: dict[str, Any],
    slots: list[dict[str, Any]],
    *,
    text: str,
    structure: str,
    outputs: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    inputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    slot_ids = {slot.get("slot_id") for slot in slots}
    if events is None:
        events = [event for event in (scene.get("events") or []) if event.get("target_slot") in slot_ids]
    if claims is None:
        claims = [
            claim
            for claim in (scene.get("claims") or [])
            if set(claim.get("supporting_slots") or []).issubset(slot_ids)
        ]
    if outputs is None:
        outputs = [output for output in (scene.get("outputs") or []) if output.get("bound_slot") in slot_ids]
    if inputs is None:
        inputs = list(scene.get("inputs") or []) if structure in {"sequence", "comparison"} else []
    result = copy.deepcopy(scene)
    result["text"] = text
    result["visual_structure"] = structure
    result["slots"] = copy.deepcopy(slots)
    result["events"] = copy.deepcopy(events)
    result["claims"] = copy.deepcopy(claims)
    result["outputs"] = copy.deepcopy(outputs)
    result["inputs"] = copy.deepcopy(inputs)
    result["no_asset"] = False
    _repair_hold_policies(result)
    return result


def _split_text_before_phrase(text: str, phrase: str) -> tuple[str, str]:
    if not text:
        return "", ""
    if not phrase:
        return text, ""
    index = text.find(phrase)
    if index < 0:
        for size in range(min(len(phrase), 12), 3, -1):
            part = phrase[:size]
            index = text.find(part)
            if index >= 0:
                return text[:index], text[index:]
        return text, ""
    return text[:index], text[index:]

"""Deterministic structural repairs for SceneSemanticPlan drafts.

Unit2 allows prompt + validator + deterministic correction. These repairs fix
common model mistakes that violate relation-boundary rules without hardcoding
Stage0 case IDs or frozen narration branches.
"""

from __future__ import annotations

import copy
from typing import Any

from video_agent.assets.v4.category_fallbacks import (
    CATEGORY_INVENTORY_FALLBACKS,
    REFERENCE_RESULT_STOCKED_CATEGORIES,
)
from video_agent.contracts.v4 import SceneSemanticPlan
from video_agent.contracts.v4.common import normalize_frozen_text


CATEGORY_REQUIRED_ROLES = frozenset(
    {
        "feature_entry",
        "parameter_panel",
        "result_image",
        "reference_image",
        "flat_plan",
        "editor_page",
        "editor_modal",
        "edited_result",
    }
)


def apply_deterministic_scene_repairs(
    plan: SceneSemanticPlan,
    *,
    frozen_narration: str | None = None,
    category_ids: list[str] | None = None,
    primary_category_id: str | None = None,
) -> SceneSemanticPlan:
    payload = plan.model_dump(mode="json")
    payload = repair_scene_plan_payload(
        payload,
        frozen_narration=frozen_narration,
        category_ids=category_ids,
        primary_category_id=primary_category_id,
    )
    return SceneSemanticPlan.model_validate(payload)


def repair_scene_plan_payload(
    payload: dict[str, Any],
    *,
    frozen_narration: str | None = None,
    category_ids: list[str] | None = None,
    primary_category_id: str | None = None,
) -> dict[str, Any]:
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
        _repair_gallery_outputs(scene)
        _repair_gallery_asset_roles(scene)
        _repair_product_feature_entry_slots(scene)
        _repair_category_inventory_fallbacks(scene)
        _repair_unstocked_reference_result_plan(scene)
        _repair_output_bindings(scene)
        _repair_missing_categories(
            scene,
            category_ids=category_ids or [],
            primary_category_id=primary_category_id,
        )

    if frozen_narration:
        _repair_narration_coverage(repaired, frozen_narration)

    for scene in repaired:
        _repair_claim_and_event_phrases(scene)
        _repair_claims_to_factual_slots(scene)

    _repair_cross_scene_result_links(repaired)
    _repair_reference_result_inherit_from_prior_result(repaired)
    for scene in repaired:
        _repair_gallery_outputs(scene)
        _repair_claims_to_factual_slots(scene)

    _ensure_terminal_default_outro(repaired)
    _repair_pre_terminal_empty_close(repaired)

    return {"scenes": repaired}


DEFAULT_OUTRO_CONFIG_KEY = "default_outro"


def _is_default_outro_slot(slot: dict[str, Any]) -> bool:
    source = slot.get("source") or {}
    return (
        slot.get("asset_role") == "outro"
        and source.get("kind") == "configured_asset"
        and source.get("config_key") == DEFAULT_OUTRO_CONFIG_KEY
    )


def _scene_has_default_outro(scene: dict[str, Any]) -> bool:
    return any(_is_default_outro_slot(slot) for slot in scene.get("slots") or [])


def _outro_anchor_phrase(text: str) -> str:
    """Pick a substring of scene text for the outro slot anchor (must stay in-text)."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for sep in ("，", "。", "！", "？", ",", ".", "!", "?"):
        if sep in cleaned:
            head = cleaned.split(sep, 1)[0].strip()
            if head:
                return head
    return cleaned[: min(len(cleaned), 16)]


def _default_outro_slot(text: str) -> dict[str, Any]:
    return {
        "slot_id": "outro",
        "anchor_phrase": _outro_anchor_phrase(text),
        "entry_policy": "scene_start",
        "hold_policy": "scene_end",
        "category_id": None,
        "asset_role": "outro",
        "source": {"kind": "configured_asset", "config_key": DEFAULT_OUTRO_CONFIG_KEY},
        "subtitle_emphasis": "none",
    }


def _convert_scene_to_default_outro(scene: dict[str, Any]) -> None:
    text = str(scene.get("text") or "")
    converted = _scene_with_slots(
        scene,
        [_default_outro_slot(text)],
        text=text,
        structure="single",
        outputs=[],
        events=[],
        claims=[],
        inputs=[],
    )
    scene.clear()
    scene.update(converted)


def _strip_nonterminal_outro(scene: dict[str, Any]) -> None:
    """Remove default_outro from non-terminal scenes so the ending is unique."""
    slots = list(scene.get("slots") or [])
    remaining = [slot for slot in slots if not _is_default_outro_slot(slot)]
    if len(remaining) == len(slots):
        return
    if remaining:
        scene["slots"] = remaining
        scene["no_asset"] = False
        if scene.get("visual_structure") == "no_asset_transition":
            scene["visual_structure"] = "single" if len(remaining) == 1 else scene.get("visual_structure") or "single"
        _repair_hold_policies(scene)
        _repair_output_bindings(scene)
        return
    _fill_brand_close_visual(scene)


def _fill_brand_close_visual(scene: dict[str, Any]) -> None:
    """Replace empty close with a generic brand/home query (never invent narration)."""
    text = str(scene.get("text") or "")
    anchor = _outro_anchor_phrase(text) or text[: min(len(text), 12)] or text
    scene["visual_structure"] = "single"
    scene["no_asset"] = False
    scene["slots"] = [
        {
            "slot_id": "brand_close",
            "anchor_phrase": anchor,
            "entry_policy": "scene_start",
            "hold_policy": "scene_end",
            "category_id": None,
            "asset_role": "site_home",
            "source": {"kind": "asset_query"},
            "subtitle_emphasis": "none",
        }
    ]
    scene["events"] = []
    scene["outputs"] = []
    scene["claims"] = []
    scene["inputs"] = []


def _fill_close_with_scene_input(
    scene: dict[str, Any],
    from_scene: dict[str, Any],
    from_output: dict[str, Any],
) -> None:
    """Replace empty close with a scene_input reuse of a prior output.

    Keeps visual continuity by reusing the upstream result image rather
    than forcing a site_home query that may be unstocked.
    """
    text = str(scene.get("text") or "")
    anchor = _outro_anchor_phrase(text) or text[: min(len(text), 12)] or text
    input_name = "prev_result"
    from_scene_id = str(from_scene.get("scene_id") or "")
    from_output_name = str(from_output.get("output_name") or "primary_result")
    asset_role = str(from_output.get("asset_role") or "result_image")
    scene["visual_structure"] = "single"
    scene["no_asset"] = False
    scene["slots"] = [
        {
            "slot_id": "brand_close",
            "anchor_phrase": anchor,
            "entry_policy": "scene_start",
            "hold_policy": "scene_end",
            "asset_role": asset_role,
            "source": {"kind": "scene_input", "input_name": input_name},
            "subtitle_emphasis": "none",
        }
    ]
    scene["events"] = []
    scene["outputs"] = []
    scene["claims"] = []
    scene["inputs"] = [
        {
            "input_name": input_name,
            "from_scene": from_scene_id,
            "from_output": from_output_name,
            "required": True,
        }
    ]


def _ensure_terminal_default_outro(scenes: list[dict[str, Any]]) -> None:
    """Guarantee the timeline ends with configured default_outro (script-agnostic).

    Does not invent narration: the last scene keeps its text and becomes the
    outro carrier. Earlier duplicate outros are stripped so the ending is unique.
    """
    if not scenes:
        return
    ordered = sorted(scenes, key=lambda scene: int(scene.get("order") or 0))
    for scene in ordered[:-1]:
        if _scene_has_default_outro(scene):
            _strip_nonterminal_outro(scene)
    last = ordered[-1]
    if not _scene_has_default_outro(last):
        _convert_scene_to_default_outro(last)
    elif not all(_is_default_outro_slot(slot) for slot in last.get("slots") or []):
        # Last scene mixes outro with other slots — collapse to the configured carrier.
        _convert_scene_to_default_outro(last)


def _repair_pre_terminal_empty_close(scenes: list[dict[str, Any]]) -> None:
    """Brand/CTA close immediately before outro must not be an empty transition.

    Prefers reusing the prior scene's output via scene_input so the brand
    close keeps visual continuity. Falls back to site_home only when no
    prior output exists (avoiding a hard gap if site_home is unstocked).
    """
    if len(scenes) < 2:
        return
    ordered = sorted(scenes, key=lambda scene: int(scene.get("order") or 0))
    if not _scene_has_default_outro(ordered[-1]):
        return
    penultimate = ordered[-2]
    is_empty = (
        penultimate.get("no_asset")
        or penultimate.get("visual_structure") == "no_asset_transition"
        or not (penultimate.get("slots") or [])
    )
    if not is_empty:
        return
    # Try to find a prior scene with a usable output for scene_input reuse.
    prior = ordered[:-2] if len(ordered) >= 3 else []
    reuse_scene: dict[str, Any] | None = None
    reuse_output: dict[str, Any] | None = None
    for candidate in reversed(prior):
        for output in candidate.get("outputs") or []:
            if str(output.get("asset_role") or "") in {"result_image", "edited_result"}:
                reuse_scene = candidate
                reuse_output = output
                break
        if reuse_output:
            break
    if reuse_scene and reuse_output:
        _fill_close_with_scene_input(penultimate, reuse_scene, reuse_output)
    else:
        _fill_brand_close_visual(penultimate)


def _expand_scene(scene: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize relation sources in-place; do NOT split mixed sequences.

    The prompt explicitly allows sequences to freely mix asset_query with
    relation-bound sources (e.g. parameter_panel → result_image). Splitting
    such scenes contradicts the prompt and breaks the model's intent.
    Only causal reference mixes (reference_image asset_query mixed with
    reference_result_plan) get rewritten in-place.
    """
    structure = scene.get("visual_structure")
    slots = list(scene.get("slots") or [])
    if structure not in {"sequence", "comparison"} or len(slots) < 2:
        return [scene]

    # Causal reference mixes must be rewritten in-place, never split into independent queries.
    if any(slot.get("asset_role") == "reference_image" and (slot.get("source") or {}).get("kind") == "asset_query" for slot in slots) and any(
        (slot.get("source") or {}).get("pattern_id") == "reference_result_plan" for slot in slots
    ):
        _repair_reference_result_plan_sources(scene)
        return [scene]

    # Normalize pure causal/editor shapes in-place (no splitting).
    if any((slot.get("source") or {}).get("pattern_id") == "reference_result_plan" for slot in slots):
        _repair_reference_result_plan_sources(scene)
    if any((slot.get("source") or {}).get("pattern_id") == "editor_sequence" for slot in slots):
        _repair_editor_sequence_sources(scene)

    return [scene]


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


def _repair_reference_result_inherit_from_prior_result(scenes: list[dict[str, Any]]) -> None:
    ordered = sorted(scenes, key=lambda scene: int(scene.get("order") or 0))

    def established_result_before(order: int) -> tuple[dict[str, Any], str] | None:
        for earlier in ordered:
            if int(earlier.get("order") or 0) >= order:
                break
            if earlier.get("visual_structure") == "gallery":
                continue
            query_slots = [
                slot
                for slot in earlier.get("slots") or []
                if slot.get("asset_role") == "result_image" and (slot.get("source") or {}).get("kind") == "asset_query"
            ]
            if not query_slots:
                continue
            outputs = list(earlier.get("outputs") or [])
            existing = next((item for item in outputs if item.get("asset_role") == "result_image"), None)
            if existing is None:
                output_name = "primary_result"
                outputs.append(
                    {
                        "output_name": output_name,
                        "bound_slot": query_slots[0].get("slot_id"),
                        "asset_role": "result_image",
                    }
                )
                earlier["outputs"] = outputs
                return earlier, output_name
            return earlier, str(existing.get("output_name") or "primary_result")
        return None

    for scene in ordered:
        slots = list(scene.get("slots") or [])
        query_binding = next(
            (
                slot.get("source")
                for slot in slots
                if (slot.get("source") or {}).get("pattern_id") == "reference_result_plan"
                and (slot.get("source") or {}).get("kind") == "asset_group_query"
            ),
            None,
        )
        if not isinstance(query_binding, dict):
            continue
        established = established_result_before(int(scene.get("order") or 0))
        if established is None:
            continue
        earlier, output_name = established
        group_alias = query_binding.get("group_alias")
        input_name = "inherited_result"
        inputs = list(scene.get("inputs") or [])
        matched = next(
            (
                item
                for item in inputs
                if item.get("from_scene") == earlier.get("scene_id") and item.get("from_output") == output_name
            ),
            None,
        )
        if matched is None:
            inputs.append(
                {
                    "input_name": input_name,
                    "from_scene": earlier.get("scene_id"),
                    "from_output": output_name,
                    "required": True,
                }
            )
        else:
            input_name = str(matched.get("input_name") or input_name)
        scene["inputs"] = inputs
        for slot in slots:
            source = dict(slot.get("source") or {})
            if source.get("pattern_id") != "reference_result_plan":
                continue
            member_key = source.get("member_key") or slot.get("asset_role")
            slot["source"] = {
                "kind": "relation_from_input",
                "input_name": input_name,
                "group_alias": group_alias,
                "group_type": source.get("group_type") or "causal",
                "pattern_id": "reference_result_plan",
                "member_key": member_key,
            }
        scene["slots"] = slots
        scene["visual_structure"] = "comparison"

        # Align later scenes that reuse the same group alias onto the same upstream result.
        for later in ordered:
            if int(later.get("order") or 0) <= int(scene.get("order") or 0):
                continue
            later_slots = list(later.get("slots") or [])
            if not any(
                (slot.get("source") or {}).get("group_alias") == group_alias
                and (slot.get("source") or {}).get("pattern_id") == "reference_result_plan"
                for slot in later_slots
            ):
                continue
            later_inputs = list(later.get("inputs") or [])
            matched_later = next(
                (
                    item
                    for item in later_inputs
                    if item.get("from_scene") == earlier.get("scene_id") and item.get("from_output") == output_name
                ),
                None,
            )
            if matched_later is None:
                later_inputs.append(
                    {
                        "input_name": input_name,
                        "from_scene": earlier.get("scene_id"),
                        "from_output": output_name,
                        "required": True,
                    }
                )
                later_input_name = input_name
            else:
                later_input_name = str(matched_later.get("input_name") or input_name)
            later["inputs"] = later_inputs
            for slot in later_slots:
                source = dict(slot.get("source") or {})
                if source.get("group_alias") != group_alias or source.get("pattern_id") != "reference_result_plan":
                    continue
                member_key = source.get("member_key") or slot.get("asset_role")
                slot["source"] = {
                    "kind": "relation_from_input",
                    "input_name": later_input_name,
                    "group_alias": group_alias,
                    "group_type": source.get("group_type") or "causal",
                    "pattern_id": "reference_result_plan",
                    "member_key": member_key,
                }
            later["slots"] = later_slots


def _repair_cross_scene_result_links(scenes: list[dict[str, Any]]) -> None:
    by_id = {str(scene.get("scene_id") or ""): scene for scene in scenes}
    ordered = sorted(scenes, key=lambda scene: int(scene.get("order") or 0))

    def ensure_result_output(scene: dict[str, Any], output_name: str) -> bool:
        if scene.get("visual_structure") == "gallery":
            return False
        outputs = list(scene.get("outputs") or [])
        if any(str(item.get("output_name") or "") == output_name for item in outputs):
            return True
        query_slots = [
            slot
            for slot in scene.get("slots") or []
            if slot.get("asset_role") == "result_image" and (slot.get("source") or {}).get("kind") == "asset_query"
        ]
        if not query_slots:
            return False
        outputs.append(
            {
                "output_name": output_name,
                "bound_slot": query_slots[0].get("slot_id"),
                "asset_role": "result_image",
            }
        )
        scene["outputs"] = outputs
        return True

    def find_established_result(before_order: int, preferred_name: str) -> tuple[str, str] | None:
        for earlier in ordered:
            if int(earlier.get("order") or 0) >= before_order:
                break
            for output in earlier.get("outputs") or []:
                if output.get("asset_role") == "result_image":
                    return str(earlier.get("scene_id") or ""), str(output.get("output_name") or preferred_name)
            if ensure_result_output(earlier, preferred_name):
                return str(earlier.get("scene_id") or ""), preferred_name
        return None

    for scene in ordered:
        for item in scene.get("inputs") or []:
            from_scene_id = str(item.get("from_scene") or "")
            from_output = str(item.get("from_output") or "primary_result")
            source = by_id.get(from_scene_id)
            if source is None:
                continue
            existing = {str(output.get("output_name") or "") for output in source.get("outputs") or []}
            if from_output in existing:
                continue
            if ensure_result_output(source, from_output):
                continue
            established = find_established_result(int(source.get("order") or 0), from_output)
            if established is None:
                established = find_established_result(int(scene.get("order") or 0), from_output)
            if established is None:
                continue
            item["from_scene"] = established[0]
            item["from_output"] = established[1]


def _verbatim_phrase_in_scene_text(scene_text: str, phrase: str) -> str | None:
    """Return a substring of scene_text that matches phrase under frozen-text normalization.

    Stage6 requires literal containment (`phrase in scene.text`). Models often emit
    NFKC-equivalent punctuation (e.g. fullwidth `，` vs ASCII `,`); rewrite to the
    exact scene span when only representation differs.
    """
    if not phrase:
        return None
    if phrase in scene_text:
        return phrase
    needle = normalize_frozen_text(phrase)
    if not needle:
        return None
    if normalize_frozen_text(scene_text) == needle:
        stripped = scene_text.strip()
        return stripped if stripped else None
    # Scene texts are short; exhaustive span search is fine and keeps mapping exact.
    for start in range(len(scene_text)):
        for end in range(start + 1, len(scene_text) + 1):
            span = scene_text[start:end]
            if normalize_frozen_text(span) == needle:
                return span
    return None


def _repair_claim_and_event_phrases(scene: dict[str, Any]) -> None:
    scene_text = str(scene.get("text") or "")
    slot_map = {str(slot.get("slot_id") or ""): slot for slot in scene.get("slots") or []}

    def fallback_phrase(preferred: str | None = None) -> str | None:
        if preferred:
            canonical = _verbatim_phrase_in_scene_text(scene_text, preferred)
            if canonical is not None:
                return canonical
        for slot in scene.get("slots") or []:
            anchor = str(slot.get("anchor_phrase") or "")
            canonical = _verbatim_phrase_in_scene_text(scene_text, anchor)
            if canonical is not None:
                return canonical
        return None

    for slot in scene.get("slots") or []:
        anchor = str(slot.get("anchor_phrase") or "")
        canonical = _verbatim_phrase_in_scene_text(scene_text, anchor)
        if canonical is not None and canonical != anchor:
            slot["anchor_phrase"] = canonical

    repaired_claims: list[dict[str, Any]] = []
    for claim in scene.get("claims") or []:
        phrase = str(claim.get("phrase") or "")
        canonical = _verbatim_phrase_in_scene_text(scene_text, phrase)
        if canonical is not None:
            if canonical != phrase:
                claim = dict(claim)
                claim["phrase"] = canonical
            repaired_claims.append(claim)
            continue
        support = claim.get("supporting_slots") or []
        support_phrase = None
        for slot_id in support:
            slot = slot_map.get(str(slot_id))
            if slot is None:
                continue
            anchor = str(slot.get("anchor_phrase") or "")
            support_phrase = _verbatim_phrase_in_scene_text(scene_text, anchor)
            if support_phrase is not None:
                break
        replacement = support_phrase or fallback_phrase()
        if replacement is None:
            continue
        claim = dict(claim)
        claim["phrase"] = replacement
        repaired_claims.append(claim)
    scene["claims"] = repaired_claims

    repaired_events: list[dict[str, Any]] = []
    for event in scene.get("events") or []:
        phrase = str(event.get("phrase") or "")
        canonical = _verbatim_phrase_in_scene_text(scene_text, phrase)
        if canonical is not None:
            if canonical != phrase:
                event = dict(event)
                event["phrase"] = canonical
            repaired_events.append(event)
            continue
        target = event.get("target_slot")
        target_phrase = None
        if target is not None and str(target) in slot_map:
            target_phrase = str(slot_map[str(target)].get("anchor_phrase") or "") or None
        replacement = fallback_phrase(target_phrase)
        if replacement is None:
            continue
        event = dict(event)
        event["phrase"] = replacement
        repaired_events.append(event)
    scene["events"] = repaired_events


def _repair_gallery_outputs(scene: dict[str, Any]) -> None:
    if scene.get("visual_structure") == "gallery":
        scene["outputs"] = []


def _repair_gallery_asset_roles(scene: dict[str, Any]) -> None:
    """Gallery enumeration must query result images, not website feature entries."""
    if scene.get("visual_structure") != "gallery":
        return
    for slot in scene.get("slots") or []:
        source = slot.get("source") or {}
        if source.get("kind") != "asset_query":
            continue
        if slot.get("asset_role") in {"feature_entry", "feature_list", "site_home", "parameter_panel"}:
            slot["asset_role"] = "result_image"


def _repair_product_feature_entry_slots(scene: dict[str, Any]) -> None:
    """文生图 product categories do not stock website feature_entry screenshots."""
    for slot in scene.get("slots") or []:
        category_id = str(slot.get("category_id") or "")
        source = slot.get("source") or {}
        if slot.get("asset_role") != "feature_entry":
            continue
        if source.get("kind") != "asset_query":
            continue
        if category_id.startswith("文生图/"):
            slot["asset_role"] = "result_image"


def _repair_category_inventory_fallbacks(scene: dict[str, Any]) -> None:
    for slot in scene.get("slots") or []:
        category_id = slot.get("category_id")
        if category_id in CATEGORY_INVENTORY_FALLBACKS:
            slot["category_id"] = CATEGORY_INVENTORY_FALLBACKS[category_id]


def _prune_bindings_to_slots(scene: dict[str, Any], slot_ids: set[str]) -> None:
    """Drop events/claims/outputs that still point at removed slots."""
    scene["events"] = [
        event
        for event in scene.get("events") or []
        if event.get("target_slot") is None or str(event.get("target_slot") or "") in slot_ids
    ]
    repaired_claims: list[dict[str, Any]] = []
    for claim in scene.get("claims") or []:
        supports = [str(slot_id) for slot_id in (claim.get("supporting_slots") or []) if str(slot_id) in slot_ids]
        if not supports:
            continue
        claim = dict(claim)
        claim["supporting_slots"] = supports
        repaired_claims.append(claim)
    scene["claims"] = repaired_claims
    scene["outputs"] = [
        output for output in scene.get("outputs") or [] if str(output.get("bound_slot") or "") in slot_ids
    ]


def _repair_unstocked_reference_result_plan(scene: dict[str, Any]) -> None:
    slots = list(scene.get("slots") or [])
    if not any((slot.get("source") or {}).get("pattern_id") == "reference_result_plan" for slot in slots):
        return
    category_id = next((str(slot.get("category_id") or "") for slot in slots if slot.get("category_id")), "")
    if category_id in REFERENCE_RESULT_STOCKED_CATEGORIES:
        return
    result_slot = next((slot for slot in slots if slot.get("asset_role") == "result_image"), None)
    if result_slot is None:
        return
    slot_id = str(result_slot.get("slot_id") or "result")
    scene["visual_structure"] = "single"
    scene["inputs"] = []
    scene["slots"] = [
        {
            **dict(result_slot),
            "slot_id": slot_id,
            "asset_role": "result_image",
            "source": {"kind": "asset_query"},
            "hold_policy": "scene_end",
            "entry_policy": result_slot.get("entry_policy") or "phrase_start",
        }
    ]
    scene["outputs"] = [
        {
            "output_name": "primary_result",
            "bound_slot": slot_id,
            "asset_role": "result_image",
        }
    ]
    _prune_bindings_to_slots(scene, {slot_id})


CLAIM_ALLOWED_ROLES: dict[str, frozenset[str]] = {
    "feature_can_generate_result": frozenset({"result_image", "edited_result"}),
    "real_website_screenshot": frozenset({"site_home", "feature_entry"}),
}
DEFAULT_FACTUAL_ROLES = frozenset({
    "result_image",
    "reference_image",
    "site_home",
    "feature_entry",
    "edited_result",
    "flat_plan",
})


def _repair_claims_to_factual_slots(scene: dict[str, Any]) -> None:
    """Remap claim supporting_slots to role-compatible slots.

    ``feature_can_generate_result`` only supports result/edited-result slots;
    ``real_website_screenshot`` only supports website-interface slots. Other
    claims fall back to the general factual-role set.
    """
    slot_roles = {str(slot.get("slot_id") or ""): str(slot.get("asset_role") or "") for slot in scene.get("slots") or []}
    repaired: list[dict[str, Any]] = []
    for claim in scene.get("claims") or []:
        claim_id = str(claim.get("claim_id") or "")
        allowed = CLAIM_ALLOWED_ROLES.get(claim_id, DEFAULT_FACTUAL_ROLES)
        compatible_slot_ids = [sid for sid, role in slot_roles.items() if role in allowed]
        supports = [str(sid) for sid in (claim.get("supporting_slots") or []) if slot_roles.get(str(sid)) in allowed]
        if not supports:
            if not compatible_slot_ids:
                continue
            supports = [compatible_slot_ids[0]]
        claim = dict(claim)
        claim["supporting_slots"] = supports
        repaired.append(claim)
    scene["claims"] = repaired


def _repair_output_bindings(scene: dict[str, Any]) -> None:
    slots = list(scene.get("slots") or [])
    slot_ids = {str(slot.get("slot_id") or "") for slot in slots}
    query_result_slots = [
        str(slot.get("slot_id") or "")
        for slot in slots
        if slot.get("asset_role") == "result_image" and (slot.get("source") or {}).get("kind") == "asset_query"
    ]
    repaired_outputs: list[dict[str, Any]] = []
    for output in scene.get("outputs") or []:
        bound = str(output.get("bound_slot") or "")
        role = output.get("asset_role")
        if bound not in slot_ids:
            if role == "result_image" and query_result_slots:
                output = dict(output)
                output["bound_slot"] = query_result_slots[0]
                bound = query_result_slots[0]
            else:
                continue
        if role == "result_image":
            bound_slot = next((slot for slot in slots if str(slot.get("slot_id") or "") == bound), None)
            if bound_slot is None:
                continue
            if (bound_slot.get("source") or {}).get("kind") != "asset_query":
                if query_result_slots:
                    output = dict(output)
                    output["bound_slot"] = query_result_slots[0]
                    output["asset_role"] = "result_image"
                else:
                    continue
        repaired_outputs.append(output)
    scene["outputs"] = repaired_outputs


def _repair_missing_categories(
    scene: dict[str, Any],
    *,
    category_ids: list[str],
    primary_category_id: str | None,
) -> None:
    if not category_ids and not primary_category_id:
        return
    text = str(scene.get("text") or "")
    inferred = _infer_category_id(text, category_ids=category_ids, primary_category_id=primary_category_id)
    if inferred is None:
        return
    for slot in scene.get("slots") or []:
        if slot.get("category_id") is not None:
            continue
        if slot.get("asset_role") in CATEGORY_REQUIRED_ROLES:
            slot["category_id"] = inferred


def _infer_category_id(
    scene_text: str,
    *,
    category_ids: list[str],
    primary_category_id: str | None,
) -> str | None:
    for category_id in category_ids:
        leaf = category_id.rsplit("/", 1)[-1]
        if leaf and leaf in scene_text:
            return category_id
    if primary_category_id:
        return primary_category_id
    return category_ids[0] if category_ids else None


def _repair_narration_coverage(scenes: list[dict[str, Any]], frozen_narration: str) -> None:
    frozen = normalize_frozen_text(frozen_narration)
    if not frozen or not scenes:
        return
    ordered = sorted(scenes, key=lambda scene: int(scene.get("order") or 0))
    combined = "".join(str(scene.get("text") or "") for scene in ordered)
    if normalize_frozen_text(combined) == frozen:
        return
    parts = _partition_frozen_by_scene_hints(frozen, [str(scene.get("text") or "") for scene in ordered])
    if parts is None:
        return
    for scene, part in zip(ordered, parts, strict=True):
        scene["text"] = part


def _partition_frozen_by_scene_hints(frozen: str, scene_texts: list[str]) -> list[str] | None:
    if not scene_texts:
        return []
    starts: list[int] = []
    cursor = 0
    for text in scene_texts:
        needle = normalize_frozen_text(text)
        if not needle:
            return None
        index = frozen.find(needle, cursor)
        if index < 0:
            index = -1
            for size in range(min(len(needle), 24), 3, -1):
                pos = frozen.find(needle[:size], cursor)
                if pos >= 0:
                    index = pos
                    break
        if index < 0:
            return None
        starts.append(index)
        cursor = index + max(1, min(4, len(needle)))
    parts: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(frozen)
        if end <= start:
            return None
        parts.append(frozen[start:end])
    if "".join(parts) != frozen:
        return None
    return parts

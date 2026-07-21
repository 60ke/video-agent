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


RELATION_KINDS = frozenset({"asset_group_query", "group_member", "scene_input", "relation_from_input"})
INDEPENDENT_KINDS = frozenset({"asset_query", "configured_asset"})
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
        _promote_standalone_editor_queries(scene)
        _repair_hold_policies(scene)
        _repair_gallery_outputs(scene)
        _repair_gallery_asset_roles(scene)
        _repair_product_feature_entry_slots(scene)
        _repair_category_inventory_fallbacks(scene)
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
    _promote_standalone_dependent_queries(repaired)
    _repair_cross_scene_result_links(repaired)
    for scene in repaired:
        _repair_gallery_outputs(scene)
        _repair_claims_to_factual_slots(scene)

    # Empty / unknown visuals → result_image | site_home | hold-prior+push.
    # Never leave no_asset, and never force default_outro as a filler.
    _repair_empty_unknown_visuals(repaired, primary_category_id=primary_category_id)

    return {"scenes": repaired}


DEFAULT_OUTRO_CONFIG_KEY = "default_outro"
HOLD_EXTEND_OUTPUT = "hold_extend_visual"

# Brand / product surface — prefer website home when the line itself is the subject.
_SITE_HOME_MARKERS = (
    "网站",
    "智能体",
    "柯幻熊猫",
    "专为广告",
    "品牌",
    "是真的可以",
    "AI是真的",
)
# Generation / delivery payoff — prefer a category result still.
_RESULT_MARKERS = (
    "效果图",
    "效果",
    "方案",
    "生成",
    "搞定",
    "出稿",
    "详情页",
    "交付",
    "结果",
)
# Soft / rhetorical / transition lines — extend the prior frame with a slow push.
_HOLD_EXTEND_MARKERS = (
    "简单好上手",
    "好上手",
    "要多久",
    "都不在话下",
    "今天就试试",
    "无需设计师",
    "快速出稿",
    "常见主题都可生成",
)


def _is_default_outro_slot(slot: dict[str, Any]) -> bool:
    source = slot.get("source") or {}
    return (
        slot.get("asset_role") == "outro"
        and source.get("kind") == "configured_asset"
        and source.get("config_key") == DEFAULT_OUTRO_CONFIG_KEY
    )


def _scene_has_default_outro(scene: dict[str, Any]) -> bool:
    return any(_is_default_outro_slot(slot) for slot in scene.get("slots") or [])


def _is_explicit_search_outro_text(text: str) -> bool:
    """Only keep configured outro when the line is an explicit search CTA."""
    normalized = normalize_frozen_text(text)
    return "搜索" in normalized and ("柯幻" in normalized or "熊猫" in normalized)


def _anchor_phrase_from_text(text: str) -> str:
    """Pick a substring of scene text for a slot anchor (must stay in-text)."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for sep in ("，", "。", "！", "？", ",", ".", "!", "?"):
        if sep in cleaned:
            head = cleaned.split(sep, 1)[0].strip()
            if head:
                return head
    return cleaned[: min(len(cleaned), 16)]


def _text_has_any(text: str, markers: tuple[str, ...]) -> bool:
    normalized = normalize_frozen_text(text)
    return any(marker in normalized for marker in markers)


def _scene_needs_visual_fallback(scene: dict[str, Any]) -> bool:
    """True when the scene has no usable visual (empty, no_asset, or non-CTA outro only)."""
    if scene.get("no_asset") or scene.get("visual_structure") == "no_asset_transition":
        return True
    slots = list(scene.get("slots") or [])
    if not slots:
        return True
    if all(_is_default_outro_slot(slot) for slot in slots) and not _is_explicit_search_outro_text(
        str(scene.get("text") or "")
    ):
        return True
    return False


def _strip_default_outro_slots(scene: dict[str, Any]) -> None:
    """Drop default_outro fillers; leave empty so the 3-way fallback can run."""
    slots = list(scene.get("slots") or [])
    remaining = [slot for slot in slots if not _is_default_outro_slot(slot)]
    if len(remaining) == len(slots):
        return
    scene["slots"] = remaining
    if not remaining:
        scene["no_asset"] = True
        scene["visual_structure"] = "no_asset_transition"
        scene["inputs"] = []
        scene["outputs"] = []
        scene["events"] = []
        scene["claims"] = []
        return
    scene["no_asset"] = False
    if scene.get("visual_structure") == "no_asset_transition":
        scene["visual_structure"] = "single" if len(remaining) == 1 else scene.get("visual_structure") or "single"
    _repair_hold_policies(scene)
    _repair_output_bindings(scene)


def _fill_site_home_visual(scene: dict[str, Any]) -> None:
    text = str(scene.get("text") or "")
    scene_id = scene.get("scene_id")
    order = scene.get("order")
    anchor = _anchor_phrase_from_text(text) or text[: min(len(text), 12)] or text
    scene.clear()
    scene.update(
        _scene_with_slots(
            {"scene_id": scene_id, "order": order, "text": text},
            [
                {
                    "slot_id": "site_home",
                    "anchor_phrase": anchor,
                    "entry_policy": "scene_start",
                    "hold_policy": "scene_end",
                    "category_id": None,
                    "asset_role": "site_home",
                    "source": {"kind": "asset_query"},
                    "subtitle_emphasis": "none",
                }
            ],
            text=text,
            structure="single",
            outputs=[],
            events=[],
            claims=[],
            inputs=[],
        )
    )


def _fill_result_visual(scene: dict[str, Any], *, category_id: str | None) -> None:
    text = str(scene.get("text") or "")
    scene_id = scene.get("scene_id")
    order = scene.get("order")
    anchor = _anchor_phrase_from_text(text) or text[: min(len(text), 12)] or text
    scene.clear()
    scene.update(
        _scene_with_slots(
            {"scene_id": scene_id, "order": order, "text": text},
            [
                {
                    "slot_id": "result_fill",
                    "anchor_phrase": anchor,
                    "entry_policy": "scene_start",
                    "hold_policy": "scene_end",
                    "category_id": category_id,
                    "asset_role": "result_image",
                    "source": {"kind": "asset_query"},
                    "subtitle_emphasis": "none",
                }
            ],
            text=text,
            structure="single",
            outputs=[],
            events=[],
            claims=[],
            inputs=[],
        )
    )


def _ensure_hold_output(scene: dict[str, Any], slot: dict[str, Any]) -> str:
    """Ensure the prior scene exports a reusable visual for hold-extend."""
    outputs = list(scene.get("outputs") or [])
    slot_id = str(slot.get("slot_id") or "")
    for output in outputs:
        if str(output.get("bound_slot") or "") == slot_id:
            name = str(output.get("output_name") or "")
            if name:
                return name
    for output in outputs:
        name = str(output.get("output_name") or "")
        if name:
            return name
    outputs.append(
        {
            "output_name": HOLD_EXTEND_OUTPUT,
            "bound_slot": slot_id,
            "asset_role": str(slot.get("asset_role") or "result_image"),
        }
    )
    scene["outputs"] = outputs
    return HOLD_EXTEND_OUTPUT


def _pick_holdable_slot(scene: dict[str, Any]) -> dict[str, Any] | None:
    slots = [slot for slot in (scene.get("slots") or []) if not _is_default_outro_slot(slot)]
    if not slots:
        return None
    for preferred in ("result_image", "site_home", "feature_entry", "parameter_panel", "other"):
        for slot in reversed(slots):
            if slot.get("asset_role") == preferred:
                return slot
    return slots[-1]


def _find_holdable_prior(
    scenes: list[dict[str, Any]],
    *,
    before_order: int,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    ordered = sorted(scenes, key=lambda item: int(item.get("order") or 0))
    for earlier in reversed(ordered):
        order = int(earlier.get("order") or 0)
        if order >= before_order:
            continue
        if earlier.get("no_asset") or earlier.get("visual_structure") == "no_asset_transition":
            continue
        # Galleries must not export outputs for inheritance.
        if earlier.get("visual_structure") == "gallery":
            continue
        slot = _pick_holdable_slot(earlier)
        if slot is None:
            continue
        return earlier, slot
    return None


def _fill_hold_extend_visual(
    scene: dict[str, Any],
    *,
    prior: dict[str, Any],
    prior_slot: dict[str, Any],
    output_name: str,
) -> None:
    text = str(scene.get("text") or "")
    scene_id = scene.get("scene_id")
    order = scene.get("order")
    anchor = _anchor_phrase_from_text(text) or text[: min(len(text), 12)] or text
    role = str(prior_slot.get("asset_role") or "result_image")
    category_id = prior_slot.get("category_id")
    scene.clear()
    scene.update(
        _scene_with_slots(
            {"scene_id": scene_id, "order": order, "text": text},
            [
                {
                    "slot_id": "hold_extend",
                    "anchor_phrase": anchor,
                    "entry_policy": "scene_start",
                    "hold_policy": "scene_end",
                    "category_id": category_id,
                    "asset_role": role,
                    "source": {"kind": "scene_input", "input_name": "hold_visual"},
                    "subtitle_emphasis": "none",
                }
            ],
            text=text,
            structure="single",
            outputs=[],
            events=[],
            claims=[],
            inputs=[
                {
                    "input_name": "hold_visual",
                    "from_scene": str(prior.get("scene_id") or ""),
                    "from_output": output_name,
                    "required": True,
                }
            ],
        )
    )


def _choose_empty_visual_mode(
    text: str,
    *,
    has_prior: bool,
) -> str:
    """Return one of: hold_extend | site_home | result_image."""
    if _text_has_any(text, _HOLD_EXTEND_MARKERS) and has_prior:
        return "hold_extend"
    if _text_has_any(text, _SITE_HOME_MARKERS):
        return "site_home"
    if _text_has_any(text, _RESULT_MARKERS):
        return "result_image"
    if has_prior:
        return "hold_extend"
    return "site_home"


def _apply_empty_visual_fallback(
    scene: dict[str, Any],
    *,
    scenes: list[dict[str, Any]],
    primary_category_id: str | None,
) -> None:
    text = str(scene.get("text") or "")
    order = int(scene.get("order") or 0)
    prior_pack = _find_holdable_prior(scenes, before_order=order)
    mode = _choose_empty_visual_mode(text, has_prior=prior_pack is not None)
    if mode == "hold_extend" and prior_pack is not None:
        prior, prior_slot = prior_pack
        output_name = _ensure_hold_output(prior, prior_slot)
        _fill_hold_extend_visual(scene, prior=prior, prior_slot=prior_slot, output_name=output_name)
        return
    if mode == "result_image":
        category = primary_category_id
        if prior_pack is not None:
            category = prior_pack[1].get("category_id") or category
        if category:
            _fill_result_visual(scene, category_id=category)
            return
    _fill_site_home_visual(scene)


def _repair_empty_unknown_visuals(
    scenes: list[dict[str, Any]],
    *,
    primary_category_id: str | None = None,
) -> None:
    """Fill every empty/unknown shot with result | site_home | hold-prior push.

    Applies to all scenes (not only the terminal line). Explicit search-CTA
    outro lines are preserved; every other default_outro filler is stripped
    and replaced by the three-way policy.
    """
    if not scenes:
        return
    ordered = sorted(scenes, key=lambda scene: int(scene.get("order") or 0))
    for scene in ordered:
        if _scene_has_default_outro(scene) and not _is_explicit_search_outro_text(str(scene.get("text") or "")):
            _strip_default_outro_slots(scene)
        if _scene_needs_visual_fallback(scene):
            _apply_empty_visual_fallback(
                scene,
                scenes=ordered,
                primary_category_id=primary_category_id,
            )


def _ensure_terminal_default_outro(scenes: list[dict[str, Any]]) -> None:
    """Deprecated compatibility shim: empty/unknown → 3-way visual, not outro.

    Kept so older call sites keep working after the product rule change:
    empty shots use result_image / site_home / hold-extend instead of
    forcing configured default_outro onto the last spoken line.
    """
    _repair_empty_unknown_visuals(scenes)


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


def _promote_standalone_editor_queries(scene: dict[str, Any]) -> None:
    """Rewrite editor_page/edited_result asset_query pairs into editor_sequence.

    Stage4 only derives editor roles via relation_from_input + editor_sequence.
    Models often emit bare asset_query pairs; promote them in-place when the
    scene already has (or can reuse) a prior result as source_result.
    """
    slots = list(scene.get("slots") or [])
    if not slots:
        return
    if any((slot.get("source") or {}).get("pattern_id") == "editor_sequence" for slot in slots):
        return
    editor_roles = {str(slot.get("asset_role") or "") for slot in slots}
    if "editor_page" not in editor_roles and "edited_result" not in editor_roles:
        return
    if not all((slot.get("source") or {}).get("kind") in {"asset_query", "scene_input", None} for slot in slots):
        # Mixed relation shapes — leave to the dedicated editor_sequence repair.
        if any((slot.get("source") or {}).get("kind") in {"relation_from_input", "group_member", "asset_group_query"} for slot in slots):
            return

    alias = f"editor_{scene.get('scene_id') or 'scene'}"
    input_name = "source_result"
    has_source = any(str(slot.get("asset_role") or "") == "result_image" for slot in slots)
    rebuilt: list[dict[str, Any]] = []
    if not has_source:
        # Inject a source_result query so the process group can bind.
        first = slots[0]
        category = first.get("category_id")
        anchor = str(first.get("anchor_phrase") or scene.get("text") or "结果")
        rebuilt.append(
            {
                "slot_id": "source_result",
                "anchor_phrase": anchor[: min(len(anchor), 16)] or "结果",
                "entry_policy": "scene_start",
                "hold_policy": "until_next_slot",
                "category_id": category,
                "asset_role": "result_image",
                "source": {
                    "kind": "relation_from_input",
                    "input_name": input_name,
                    "group_alias": alias,
                    "group_type": "process",
                    "pattern_id": "editor_sequence",
                    "member_key": "source_result",
                },
                "subtitle_emphasis": "none",
            }
        )
    for slot in slots:
        role = str(slot.get("asset_role") or "")
        member_key = {
            "result_image": "source_result",
            "editor_page": "editor_page",
            "edited_result": "edited_result",
        }.get(role)
        if member_key is None:
            rebuilt.append(slot)
            continue
        item = dict(slot)
        item["source"] = {
            "kind": "relation_from_input",
            "input_name": input_name,
            "group_alias": alias,
            "group_type": "process",
            "pattern_id": "editor_sequence",
            "member_key": member_key,
        }
        if member_key == "source_result":
            item["asset_role"] = "result_image"
        rebuilt.append(item)

    # Ensure a process input exists; cross-scene linker fills from_scene later.
    inputs = list(scene.get("inputs") or [])
    if not any(str(item.get("input_name") or "") == input_name for item in inputs):
        inputs.append(
            {
                "input_name": input_name,
                "from_scene": "",  # filled by _repair_cross_scene_result_links
                "from_output": "primary_result",
                "required": True,
            }
        )
    scene["slots"] = rebuilt
    scene["inputs"] = inputs
    scene["visual_structure"] = "sequence"
    scene["no_asset"] = False
    _repair_hold_policies(scene)
    _repair_output_bindings(scene)


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
                if from_scene_id:
                    continue
                established = find_established_result(int(scene.get("order") or 0), from_output)
                if established is None:
                    continue
                item["from_scene"] = established[0]
                item["from_output"] = established[1]
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


def _promote_standalone_dependent_queries(scenes: list[dict[str, Any]]) -> None:
    """Compile dependency-sensitive asset queries into executable relations.

    Scene AI describes the desired visual role. Editor and flat-plan assets,
    however, can only be derived from an already established result identity.
    Bind those roles to the nearest prior non-gallery result so Stage4 never
    receives an impossible zero-parent derivation request.
    """

    ordered = sorted(scenes, key=lambda scene: int(scene.get("order") or 0))

    def result_output_before(scene: dict[str, Any], category_id: str | None) -> tuple[str, str] | None:
        candidates: list[tuple[bool, int, str, str]] = []
        current_order = int(scene.get("order") or 0)
        for earlier in ordered:
            earlier_order = int(earlier.get("order") or 0)
            if earlier_order >= current_order or earlier.get("visual_structure") == "gallery":
                continue
            slot_by_id = {
                str(slot.get("slot_id") or ""): slot for slot in earlier.get("slots") or []
            }
            for output in earlier.get("outputs") or []:
                if output.get("asset_role") != "result_image":
                    continue
                bound = slot_by_id.get(str(output.get("bound_slot") or ""))
                if bound is None:
                    continue
                same_category = bool(category_id and bound.get("category_id") == category_id)
                candidates.append(
                    (
                        same_category,
                        earlier_order,
                        str(earlier.get("scene_id") or ""),
                        str(output.get("output_name") or "primary_result"),
                    )
                )
        if not candidates:
            return None
        _, _, scene_id, output_name = max(candidates, key=lambda item: (item[0], item[1]))
        return scene_id, output_name

    for scene in ordered:
        slots = list(scene.get("slots") or [])
        dependent = [
            slot
            for slot in slots
            if slot.get("asset_role") in {"editor_page", "edited_result", "flat_plan"}
            and (slot.get("source") or {}).get("kind") == "asset_query"
        ]
        if not dependent:
            continue
        category_id = next(
            (str(slot.get("category_id")) for slot in dependent if slot.get("category_id")),
            None,
        )
        upstream = result_output_before(scene, category_id)
        if upstream is None:
            # Leave the original query intact. Domain validation reports the
            # missing dependency with scene/slot context instead of inventing a
            # parent or silently changing the requested visual.
            continue

        input_name = "source_result"
        inputs = list(scene.get("inputs") or [])
        existing_input = next(
            (
                item
                for item in inputs
                if item.get("from_scene") == upstream[0]
                and item.get("from_output") == upstream[1]
            ),
            None,
        )
        if existing_input is None:
            used_names = {str(item.get("input_name") or "") for item in inputs}
            suffix = 2
            while input_name in used_names:
                input_name = f"source_result_{suffix}"
                suffix += 1
            inputs.append(
                {
                    "input_name": input_name,
                    "from_scene": upstream[0],
                    "from_output": upstream[1],
                    "required": True,
                }
            )
        else:
            input_name = str(existing_input.get("input_name") or input_name)

        editor_alias = f"editor_{scene.get('scene_id') or 'scene'}"
        causal_alias = f"reference_{scene.get('scene_id') or 'scene'}"
        for slot in dependent:
            role = str(slot.get("asset_role") or "")
            if role in {"editor_page", "edited_result"}:
                group_type = "process"
                pattern_id = "editor_sequence"
                group_alias = editor_alias
                member_key = role
            else:
                group_type = "causal"
                pattern_id = "reference_result_plan"
                group_alias = causal_alias
                member_key = "flat_plan"
            slot["source"] = {
                "kind": "relation_from_input",
                "input_name": input_name,
                "group_alias": group_alias,
                "group_type": group_type,
                "pattern_id": pattern_id,
                "member_key": member_key,
            }
        scene["inputs"] = inputs
        scene["no_asset"] = False
        if any(slot.get("asset_role") in {"editor_page", "edited_result"} for slot in dependent):
            scene["visual_structure"] = "sequence"


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


def _repair_claims_to_factual_slots(scene: dict[str, Any]) -> None:
    factual_roles = {
        "result_image",
        "reference_image",
        "site_home",
        "feature_entry",
        "edited_result",
        "flat_plan",
    }
    slot_roles = {str(slot.get("slot_id") or ""): str(slot.get("asset_role") or "") for slot in scene.get("slots") or []}
    factual_slot_ids = [slot_id for slot_id, role in slot_roles.items() if role in factual_roles]
    repaired: list[dict[str, Any]] = []
    for claim in scene.get("claims") or []:
        supports = [str(slot_id) for slot_id in (claim.get("supporting_slots") or []) if slot_roles.get(str(slot_id)) in factual_roles]
        if not supports:
            if not factual_slot_ids:
                continue
            supports = [factual_slot_ids[0]]
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

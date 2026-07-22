from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    EffectBinding,
    EffectEntry,
    EffectEventIntent,
    ResolvedAssetPlan,
    ResolvedSceneAssets,
    SceneMotionIntent,
    SceneSemanticPlan,
    SemanticScene,
)
from video_agent.contracts.v4.motion_audio import MotionDirection
from video_agent.registries import CapabilityRegistryHub

from .errors import Stage5Error
from .timing_budget import frames_to_ms, scene_budget_ms


LAYOUT_BY_STRUCTURE = {
    "gallery": "douyin_gallery_safe",
    "single": "douyin_safe",
    "sequence": "douyin_sequence_safe",
    "comparison": "douyin_comparison_safe",
    "no_asset_transition": "douyin_transition_safe",
}

_STRONG_EFFECTS = frozenset(
    {
        "card_flip_3d",
        "paper_curl_flip",
        "spring_card_pop",
        "slide_gallery",
        "card_stack",
        "before_after",
        "grid_reveal",
    }
)

_DIRECTIONAL_EFFECTS = frozenset({"slide_gallery", "card_stack", "before_after"})


@dataclass(frozen=True)
class _FrozenGroupState:
    effect_id: str
    effect_version: str
    layout_profile_id: str
    direction: MotionDirection
    parameters: dict[str, str | int | float | bool]


def assign_scene_motion(
    scene_plan: SceneSemanticPlan,
    resolved: ResolvedAssetPlan,
    anchored_timing: AnchoredTimingPlan,
    *,
    registry: CapabilityRegistryHub,
    run_seed: str,
) -> list[SceneMotionIntent]:
    resolved_by_id = {scene.scene_id: scene for scene in resolved.scenes}
    ordered = sorted(scene_plan.scenes, key=lambda item: item.order)
    group_state: dict[str, _FrozenGroupState] = {}
    previous_independent_effect: str | None = None
    previous_structure: str | None = None
    previous_group_id: str | None = None
    results: list[SceneMotionIntent] = []

    for scene in ordered:
        resolved_scene = resolved_by_id.get(scene.scene_id)
        if resolved_scene is None:
            raise Stage5Error(
                "motion_assignment_failed",
                "resolved assets missing scene",
                scene_id=scene.scene_id,
            )
        continuity_id = _continuity_group_id(scene, previous_structure, previous_group_id)
        budget_ms = scene_budget_ms(anchored_timing, scene.scene_id)
        item_count = _item_count(scene, resolved_scene)
        roles = _scene_roles(scene, resolved_scene)
        orientations = _scene_orientations(resolved_scene)  # may be empty for no-asset

        if continuity_id and continuity_id in group_state:
            frozen = group_state[continuity_id]
            entry = registry.entry("effect", frozen.effect_id)
            if not isinstance(entry, EffectEntry):
                raise Stage5Error(
                    "missing_effect_capability",
                    f"unknown frozen effect {frozen.effect_id}",
                    scene_id=scene.scene_id,
                )
            binding = EffectBinding(
                effect_id=frozen.effect_id,
                effect_version=frozen.effect_version,
                layout_profile_id=frozen.layout_profile_id,
                direction=frozen.direction,
                parameters=dict(frozen.parameters),
            )
        else:
            candidates = _filter_effects(
                registry,
                visual_structure=scene.visual_structure,
                roles=roles,
                item_count=item_count,
                orientations=orientations,
                budget_ms=budget_ms,
                fps=anchored_timing.fps,
            )
            if previous_independent_effect and continuity_id is None:
                preferred = [
                    item
                    for item in candidates
                    if item.id != previous_independent_effect or item.id not in _STRONG_EFFECTS
                ]
                if preferred:
                    candidates = preferred
            chosen = _select_effect(
                candidates,
                run_seed=run_seed,
                scene_id=scene.scene_id,
                preferred_effect_id=_preferred_effect_id(scene),
            )
            if chosen is None:
                raise Stage5Error(
                    "missing_effect_capability",
                    (
                        f"no effect candidates for structure={scene.visual_structure} "
                        f"roles={sorted(roles)} items={item_count} budget_ms={budget_ms}"
                    ),
                    scene_id=scene.scene_id,
                )
            direction = _select_direction(chosen, run_seed=run_seed, scene_id=scene.scene_id)
            layout = LAYOUT_BY_STRUCTURE.get(scene.visual_structure, "douyin_safe")
            binding = EffectBinding(
                effect_id=chosen.id,
                effect_version=str(chosen.schema_version),
                layout_profile_id=layout,
                direction=direction,
                parameters={},
            )
            if continuity_id:
                group_state[continuity_id] = _FrozenGroupState(
                    effect_id=binding.effect_id,
                    effect_version=binding.effect_version,
                    layout_profile_id=binding.layout_profile_id,
                    direction=binding.direction,
                    parameters=dict(binding.parameters),
                )

        entry = registry.entry("effect", binding.effect_id)
        if not isinstance(entry, EffectEntry):
            raise Stage5Error(
                "missing_effect_capability",
                f"effect missing after selection: {binding.effect_id}",
                scene_id=scene.scene_id,
            )
        events = _event_intents(scene, resolved_scene, entry)
        results.append(
            SceneMotionIntent(
                scene_id=scene.scene_id,
                continuity_group_id=continuity_id,
                effect=binding,
                event_intents=events,
            )
        )
        if continuity_id is None:
            previous_independent_effect = binding.effect_id
        previous_structure = scene.visual_structure
        previous_group_id = continuity_id

    return results


def _continuity_group_id(
    scene: SemanticScene,
    previous_structure: str | None,
    previous_group_id: str | None,
) -> str | None:
    structure = scene.visual_structure
    alias = _primary_group_alias(scene)
    if structure == "gallery":
        if previous_structure == "gallery" and previous_group_id and previous_group_id.startswith("gallery:"):
            return previous_group_id
        return f"gallery:{scene.scene_id}"
    if structure == "sequence":
        return f"sequence:{alias or scene.scene_id}"
    if structure == "comparison":
        return f"comparison:{alias or scene.scene_id}"
    return None


def _primary_group_alias(scene: SemanticScene) -> str | None:
    for slot in scene.slots:
        source = slot.source
        alias = getattr(source, "group_alias", None)
        if isinstance(alias, str) and alias:
            return alias
    return None


def _item_count(scene: SemanticScene, resolved: ResolvedSceneAssets) -> int:
    if scene.no_asset or scene.visual_structure == "no_asset_transition":
        return 0
    return sum(1 for slot in resolved.slots if slot.status != "resolved_no_asset")


def _scene_roles(scene: SemanticScene, resolved: ResolvedSceneAssets) -> set[str]:
    if scene.no_asset or not scene.slots:
        if scene.visual_structure == "no_asset_transition":
            return {"brand_logo", "outro", "result_image"}
        return set()
    roles = {slot.asset_role for slot in scene.slots}
    # Keep only roles that actually resolved when available.
    resolved_slot_ids = {slot.slot_id for slot in resolved.slots if slot.status != "resolved_no_asset"}
    if resolved_slot_ids:
        roles = {slot.asset_role for slot in scene.slots if slot.slot_id in resolved_slot_ids} or roles
    return roles


def _scene_orientations(resolved: ResolvedSceneAssets) -> set[str]:
    # Orientation is soft; Stage5 does not re-query assets here. Empty means any.
    _ = resolved
    return set()


def _filter_effects(
    registry: CapabilityRegistryHub,
    *,
    visual_structure: str,
    roles: set[str],
    item_count: int,
    orientations: set[str],
    budget_ms: int,
    fps: int,
) -> list[EffectEntry]:
    document = registry.registry("effect")
    entries = [
        entry
        for entry in document.entries
        if isinstance(entry, EffectEntry) and entry.enabled
    ]
    matched: list[EffectEntry] = []
    for entry in entries:
        caps = entry.capabilities
        if visual_structure not in caps.visual_structures:
            continue
        if roles and not (roles & set(caps.asset_roles)):
            continue
        if item_count < caps.minimum_items:
            continue
        if caps.maximum_items is not None and item_count > caps.maximum_items:
            continue
        if orientations and not caps.supports_mixed_orientation:
            if len(orientations) > 1:
                continue
            if orientations and not orientations.issubset(set(caps.orientations)):
                continue
        required_ms = frames_to_ms(caps.minimum_scene_frames, fps)
        if required_ms > budget_ms:
            continue
        matched.append(entry)
    if matched:
        return matched
    # Fallback chain exploration from all structure-compatible entries.
    seed = [
        entry
        for entry in entries
        if visual_structure in entry.capabilities.visual_structures
        and (not roles or (roles & set(entry.capabilities.asset_roles)))
        and item_count >= entry.capabilities.minimum_items
        and (
            entry.capabilities.maximum_items is None
            or item_count <= entry.capabilities.maximum_items
        )
    ]
    seen: set[str] = set()
    queue = list(seed)
    while queue:
        current = queue.pop(0)
        if current.id in seen:
            continue
        seen.add(current.id)
        required_ms = frames_to_ms(current.capabilities.minimum_scene_frames, fps)
        if required_ms <= budget_ms:
            matched.append(current)
        for fallback_id in current.capabilities.fallback_effect_ids:
            fallback = registry.entry("effect", fallback_id, include_disabled=False)
            if isinstance(fallback, EffectEntry) and fallback.id not in seen:
                queue.append(fallback)
    return matched


def _preferred_effect_id(scene: SemanticScene) -> str | None:
    """Hold-extend empties should keep the prior frame and push in slowly."""
    if scene.visual_structure != "single" or len(scene.slots) != 1:
        return None
    slot = scene.slots[0]
    if getattr(slot.source, "kind", None) != "scene_input":
        return None
    if slot.slot_id == "hold_extend" or any(item.input_name == "hold_visual" for item in scene.inputs):
        return "detail_push_in"
    return None


def _select_effect(
    candidates: list[EffectEntry],
    *,
    run_seed: str,
    scene_id: str,
    preferred_effect_id: str | None = None,
) -> EffectEntry | None:
    if not candidates:
        return None
    if preferred_effect_id:
        preferred = [item for item in candidates if item.id == preferred_effect_id]
        if preferred:
            return preferred[0]
    if len(candidates) == 1:
        return candidates[0]
    ordered = sorted(candidates, key=lambda item: item.id)
    weights = [max(item.capabilities.weight, 1) for item in ordered]
    rng = random.Random(_seed_int(run_seed, f"effect:{scene_id}"))
    return rng.choices(ordered, weights=weights, k=1)[0]


def _select_direction(entry: EffectEntry, *, run_seed: str, scene_id: str) -> MotionDirection:
    if entry.id not in _DIRECTIONAL_EFFECTS:
        return "none"
    rng = random.Random(_seed_int(run_seed, f"direction:{scene_id}:{entry.id}"))
    return rng.choice(["left", "right"])


def _event_intents(
    scene: SemanticScene,
    resolved: ResolvedSceneAssets,
    entry: EffectEntry,
) -> list[EffectEventIntent]:
    bindings = list(entry.capabilities.event_bindings)
    if not bindings:
        return []
    event_type = bindings[0]
    intents: list[EffectEventIntent] = []
    resolved_by_slot = {slot.slot_id: slot for slot in resolved.slots}
    if scene.slots:
        for slot in scene.slots:
            resolved_slot = resolved_by_slot.get(slot.slot_id)
            if resolved_slot is not None and resolved_slot.status == "resolved_no_asset":
                continue
            intents.append(
                EffectEventIntent(
                    event_id=f"{scene.scene_id}.{slot.slot_id}.{event_type}",
                    event_type=event_type,
                    slot_id=slot.slot_id,
                    member_key=resolved_slot.member_key if resolved_slot else None,
                    anchor_phrase=slot.anchor_phrase,
                )
            )
    else:
        phrase = scene.text.strip() or scene.scene_id
        # Must match a PhraseAnchor already frozen at Stage6 anchor phase
        # (no_asset scenes bind the full scene text).
        anchor = phrase if phrase in scene.text else scene.text
        intents.append(
            EffectEventIntent(
                event_id=f"{scene.scene_id}.{event_type}",
                event_type=event_type,
                slot_id=None,
                member_key=None,
                anchor_phrase=anchor if anchor else scene.text,
            )
        )
    return intents


def _seed_int(run_seed: str, seed_material: str) -> int:
    digest = hashlib.sha256(f"{run_seed}:{seed_material}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)

"""Effect variant selection and revalidation for Stage6 compile."""

from __future__ import annotations

from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    CompiledEffectEvent,
    CompiledEffectInstance,
    EffectEntry,
    EffectEventIntent,
    PhraseAnchorV4,
    SceneMotionIntent,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.registries import CapabilityRegistryHub

_VARIANT_ORDER = ("full", "compact", "instant")


def select_variant_id(
    entry: EffectEntry,
    *,
    event_hit_frame: int,
    semantic_interval_end: int,
) -> str:
    available = semantic_interval_end - event_hit_frame
    if available <= 0:
        raise Stage6Error(
            "effect_variant_unavailable",
            "non-positive event interval",
            details={"available": available},
        )
    timings = entry.capabilities.event_timing
    if not timings:
        return "instant"
    # All required event types must share a variant quality tier.
    for variant_id in _VARIANT_ORDER:
        ok = True
        for event_type, timing in timings.items():
            variant = next((item for item in timing.variants if item.variant_id == variant_id), None)
            if variant is None:
                ok = False
                break
            if available < variant.minimum_interval_frames:
                ok = False
                break
            if event_hit_frame + variant.reveal_frames + variant.readable_settle_frames > semantic_interval_end:
                ok = False
                break
            _ = event_type
        if ok:
            return variant_id
    raise Stage6Error(
        "effect_variant_unavailable",
        f"no variant fits available frames={available} for effect {entry.id}",
        details={"available_frames": available, "effect_id": entry.id},
    )


def compile_effect_instance(
    *,
    motion: SceneMotionIntent,
    event_intent: EffectEventIntent | None,
    anchor: PhraseAnchorV4 | None,
    scene_end: int,
    next_anchor_hit: int | None,
    registry: CapabilityRegistryHub,
    instance_suffix: str,
) -> CompiledEffectInstance:
    entry = registry.entry("effect", motion.effect.effect_id)
    if not isinstance(entry, EffectEntry):
        raise Stage6Error(
            "adapter_coverage_missing",
            f"unknown effect {motion.effect.effect_id}",
            scene_id=motion.scene_id,
        )
    hit = anchor.hit_frame if anchor is not None else 0
    semantic_end = next_anchor_hit if next_anchor_hit is not None else scene_end
    if entry.capabilities.event_bindings and event_intent is not None and anchor is not None:
        variant_id = select_variant_id(entry, event_hit_frame=hit, semantic_interval_end=semantic_end)
        timing = entry.capabilities.event_timing.get(event_intent.event_type)
        if timing is None:
            raise Stage6Error(
                "effect_budget_revalidation_failed",
                f"missing event_timing for {event_intent.event_type}",
                scene_id=motion.scene_id,
                event_id=event_intent.event_id,
            )
        variant = next(item for item in timing.variants if item.variant_id == variant_id)
        start = hit
        end = min(scene_end, hit + max(variant.minimum_interval_frames, variant.reveal_frames))
        events = [
            CompiledEffectEvent(
                event_id=event_intent.event_id,
                event_type=event_intent.event_type,
                anchor_id=anchor.anchor_id,
                hit_frame=hit,
                start_frame=start,
                end_frame=max(start + 1, end),
            )
        ]
        parameters = {
            **dict(motion.effect.parameters),
            "reveal_frames": variant.reveal_frames,
            "readable_settle_frames": variant.readable_settle_frames,
            "minimum_interval_frames": variant.minimum_interval_frames,
        }
    else:
        variant_id = "instant"
        events = []
        start = hit
        end = scene_end
        parameters = dict(motion.effect.parameters)

    return CompiledEffectInstance(
        effect_instance_id=f"fx://{motion.scene_id}/{instance_suffix}",
        effect_id=motion.effect.effect_id,
        effect_version=motion.effect.effect_version,
        adapter_id=motion.effect.effect_id,
        variant_id=variant_id,  # type: ignore[arg-type]
        direction=motion.effect.direction,
        parameters=parameters,
        events=events,
    )


def revalidate_scene_effect(
    *,
    motion: SceneMotionIntent,
    scene_frames: int,
    registry: CapabilityRegistryHub,
) -> None:
    entry = registry.entry("effect", motion.effect.effect_id)
    if not isinstance(entry, EffectEntry):
        raise Stage6Error(
            "adapter_coverage_missing",
            f"unknown effect {motion.effect.effect_id}",
            scene_id=motion.scene_id,
        )
    if scene_frames < entry.capabilities.minimum_scene_frames:
        raise Stage6Error(
            "effect_budget_revalidation_failed",
            (
                f"effect {entry.id} needs {entry.capabilities.minimum_scene_frames} "
                f"frames but scene has {scene_frames}"
            ),
            scene_id=motion.scene_id,
            details={
                "effect_id": entry.id,
                "required": entry.capabilities.minimum_scene_frames,
                "available": scene_frames,
            },
        )


def next_anchor_hit_frame(
    anchored: AnchoredTimingPlan,
    *,
    scene_id: str,
    after_hit: int,
) -> int | None:
    hits = sorted(
        anchor.hit_frame
        for anchor in anchored.anchors
        if anchor.scene_id == scene_id and anchor.hit_frame > after_hit
    )
    return hits[0] if hits else None

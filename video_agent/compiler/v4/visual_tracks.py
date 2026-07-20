"""Compile base/overlay visual tracks from anchored timing + resolved assets."""

from __future__ import annotations

from video_agent.compiler.v4.effects import (
    compile_effect_instance,
    next_anchor_hit_frame,
    revalidate_scene_effect,
)
from video_agent.compiler.v4.layouts import content_layout
from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    CompiledEffectInstance,
    CompiledVisualClip,
    CompiledVisualTrack,
    MotionAudioPlan,
    PhraseAnchorV4,
    RemotionOrderedItem,
    ResolvedAssetPlan,
    SceneSemanticPlan,
    SemanticScene,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.registries import CapabilityRegistryHub


# Effects that require one scene-spanning clip with multiple asset bindings.
_MULTI_ASSET_EFFECTS = frozenset({"before_after", "grid_reveal"})


def compile_visual_tracks(
    *,
    scene_plan: SceneSemanticPlan,
    resolved: ResolvedAssetPlan,
    anchored: AnchoredTimingPlan,
    motion_plan: MotionAudioPlan,
    registry: CapabilityRegistryHub,
    postroll_frames: int = 0,
) -> tuple[list[CompiledVisualTrack], list[CompiledEffectInstance]]:
    motions = {item.scene_id: item for item in motion_plan.scenes}
    resolved_by = {item.scene_id: item for item in resolved.scenes}
    spans = {span.scene_id: span for span in anchored.scene_spans}
    anchors_by_id = {item.anchor_id: item for item in anchored.anchors}
    slot_bindings = {
        (b.scene_id, b.source_id): b.anchor_id
        for b in anchored.bindings
        if b.binding_kind == "slot"
    }
    op_bindings = {
        (b.scene_id, b.source_id): b.anchor_id
        for b in anchored.bindings
        if b.binding_kind == "operation"
    }

    base_clips: list[CompiledVisualClip] = []
    overlay_clips: list[CompiledVisualClip] = []
    effect_instances: list[CompiledEffectInstance] = []
    frame_count = anchored.duration_frames + max(postroll_frames, 0)

    ordered = sorted(scene_plan.scenes, key=lambda item: item.order)
    for scene in ordered:
        span = spans.get(scene.scene_id)
        if span is None:
            raise Stage6Error("scene_span_gap", "missing scene span", scene_id=scene.scene_id)
        motion = motions.get(scene.scene_id)
        if motion is None:
            raise Stage6Error(
                "effect_budget_revalidation_failed",
                "motion intent missing",
                scene_id=scene.scene_id,
            )
        revalidate_scene_effect(
            motion=motion,
            scene_frames=span.end_frame - span.start_frame,
            registry=registry,
        )
        resolved_scene = resolved_by[scene.scene_id]
        layout_id = motion.effect.layout_profile_id
        layout = content_layout(layout_id)

        if scene.visual_structure == "gallery":
            if motion.effect.effect_id in _MULTI_ASSET_EFFECTS:
                clips, effects = _compile_multi_asset(
                    scene=scene,
                    span_start=span.start_frame,
                    span_end=span.end_frame,
                    motion=motion,
                    resolved_scene=resolved_scene,
                    slot_bindings=slot_bindings,
                    anchors_by_id=anchors_by_id,
                    registry=registry,
                    layout_id=layout_id,
                    layout=layout,
                    instance_suffix="gallery_multi",
                )
            else:
                clips, effects = _compile_gallery(
                    scene=scene,
                    span_start=span.start_frame,
                    span_end=span.end_frame,
                    motion=motion,
                    resolved_scene=resolved_scene,
                    slot_bindings=slot_bindings,
                    anchors_by_id=anchors_by_id,
                    anchored=anchored,
                    registry=registry,
                    layout_id=layout_id,
                    layout=layout,
                )
            base_clips.extend(clips)
            effect_instances.extend(effects)
        elif scene.visual_structure == "sequence":
            clips, overlays, effects = _compile_sequence(
                scene=scene,
                span_start=span.start_frame,
                span_end=span.end_frame,
                motion=motion,
                resolved_scene=resolved_scene,
                slot_bindings=slot_bindings,
                op_bindings=op_bindings,
                anchors_by_id=anchors_by_id,
                anchored=anchored,
                registry=registry,
                layout_id=layout_id,
                layout=layout,
            )
            base_clips.extend(clips)
            overlay_clips.extend(overlays)
            effect_instances.extend(effects)
        elif scene.visual_structure == "comparison":
            clips, effects = _compile_multi_asset(
                scene=scene,
                span_start=span.start_frame,
                span_end=span.end_frame,
                motion=motion,
                resolved_scene=resolved_scene,
                slot_bindings=slot_bindings,
                anchors_by_id=anchors_by_id,
                registry=registry,
                layout_id=layout_id,
                layout=layout,
                instance_suffix="comparison",
            )
            base_clips.extend(clips)
            effect_instances.extend(effects)
        elif scene.visual_structure == "no_asset_transition" or scene.no_asset:
            clips, effects = _compile_no_asset(
                scene=scene,
                span_start=span.start_frame,
                span_end=span.end_frame,
                motion=motion,
                anchors_by_id=anchors_by_id,
                anchored=anchored,
                registry=registry,
                layout_id=layout_id,
                layout=layout,
            )
            base_clips.extend(clips)
            effect_instances.extend(effects)
        else:
            clips, effects = _compile_single(
                scene=scene,
                span_start=span.start_frame,
                span_end=span.end_frame,
                motion=motion,
                resolved_scene=resolved_scene,
                slot_bindings=slot_bindings,
                anchors_by_id=anchors_by_id,
                anchored=anchored,
                registry=registry,
                layout_id=layout_id,
                layout=layout,
                is_first=(scene is ordered[0]),
            )
            base_clips.extend(clips)
            effect_instances.extend(effects)

    # Ensure global base continuity: start at 0, close gaps by holding previous clip, extend to frame_count.
    if base_clips:
        base_clips = sorted(base_clips, key=lambda item: item.start_frame)
        if base_clips[0].start_frame > 0:
            base_clips[0] = base_clips[0].model_copy(update={"start_frame": 0})
        closed: list[CompiledVisualClip] = [base_clips[0]]
        for clip in base_clips[1:]:
            prev = closed[-1]
            if clip.start_frame > prev.end_frame:
                closed[-1] = prev.model_copy(
                    update={"end_frame": clip.start_frame, "hold_reason": prev.hold_reason or "pause"}
                )
            elif clip.start_frame < prev.end_frame:
                closed[-1] = prev.model_copy(update={"end_frame": clip.start_frame})
            closed.append(clip)
        base_clips = closed
        if base_clips[-1].end_frame < frame_count:
            base_clips[-1] = base_clips[-1].model_copy(
                update={"end_frame": frame_count, "hold_reason": "scene_span"}
            )

    _assert_base_coverage(base_clips, frame_count)
    tracks = [
        CompiledVisualTrack(track_id="base", track_kind="base", clips=base_clips),
    ]
    if overlay_clips:
        tracks.append(CompiledVisualTrack(track_id="overlay", track_kind="overlay", clips=overlay_clips))
    return tracks, effect_instances


def _assert_base_coverage(clips: list[CompiledVisualClip], frame_count: int) -> None:
    if not clips:
        raise Stage6Error("timeline_base_track_gap", "base track has no clips")
    cursor = 0
    for clip in sorted(clips, key=lambda item: item.start_frame):
        if clip.start_frame > cursor:
            raise Stage6Error(
                "timeline_base_track_gap",
                f"gap before {clip.clip_id} at frame {cursor}",
                scene_id=clip.scene_id,
            )
        if clip.start_frame < cursor:
            raise Stage6Error(
                "timeline_base_track_overlap",
                f"overlap at {clip.clip_id}",
                scene_id=clip.scene_id,
            )
        cursor = clip.end_frame
    if cursor < frame_count:
        raise Stage6Error("timeline_base_track_gap", f"base ends early at {cursor}/{frame_count}")


def _slot_anchor(
    scene_id: str,
    slot_id: str,
    slot_bindings: dict[tuple[str, str], str],
    anchors_by_id: dict[str, PhraseAnchorV4],
) -> PhraseAnchorV4 | None:
    anchor_id = slot_bindings.get((scene_id, slot_id))
    return anchors_by_id.get(anchor_id) if anchor_id else None


def _compile_gallery(**kwargs):
    scene: SemanticScene = kwargs["scene"]
    span_start = kwargs["span_start"]
    span_end = kwargs["span_end"]
    motion = kwargs["motion"]
    resolved_scene = kwargs["resolved_scene"]
    slot_bindings = kwargs["slot_bindings"]
    anchors_by_id = kwargs["anchors_by_id"]
    anchored = kwargs["anchored"]
    registry = kwargs["registry"]
    layout_id = kwargs["layout_id"]
    layout = kwargs["layout"]

    resolved_slots = [slot for slot in resolved_scene.slots if slot.status != "resolved_no_asset"]
    if not resolved_slots:
        raise Stage6Error("timeline_base_track_gap", "gallery has no assets", scene_id=scene.scene_id)

    hits: list[tuple[object, object, PhraseAnchorV4]] = []
    for slot in scene.slots:
        resolved = next((item for item in resolved_slots if item.slot_id == slot.slot_id), None)
        if resolved is None or not resolved.asset_ref:
            continue
        anchor = _slot_anchor(scene.scene_id, slot.slot_id, slot_bindings, anchors_by_id)
        if anchor is None:
            raise Stage6Error(
                "anchor_unresolved",
                f"gallery slot missing anchor: {slot.slot_id}",
                scene_id=scene.scene_id,
            )
        hits.append((slot, resolved, anchor))
    hits.sort(key=lambda item: item[2].hit_frame)

    clips: list[CompiledVisualClip] = []
    effects: list[CompiledEffectInstance] = []
    for index, (slot, resolved, anchor) in enumerate(hits):
        if slot.entry_policy == "scene_start" and index == 0:
            start = span_start
        else:
            start = anchor.hit_frame
        end = hits[index + 1][2].hit_frame if index + 1 < len(hits) else span_end
        if end <= start:
            end = start + 1
        event = motion.event_intents[index] if index < len(motion.event_intents) else (
            motion.event_intents[0] if motion.event_intents else None
        )
        nxt = hits[index + 1][2].hit_frame if index + 1 < len(hits) else None
        effect = compile_effect_instance(
            motion=motion,
            event_intent=event,
            anchor=anchor,
            scene_end=span_end,
            next_anchor_hit=nxt,
            registry=registry,
            instance_suffix=f"gallery_{resolved.slot_id}",
        )
        effects.append(effect)
        clips.append(
            CompiledVisualClip(
                clip_id=f"clip://{scene.scene_id}/{resolved.slot_id}",
                scene_id=scene.scene_id,
                slot_id=resolved.slot_id,
                group_ref=resolved.group_ref,
                member_key=resolved.member_key,
                asset_bindings={"primary": resolved.asset_ref},
                start_frame=start,
                end_frame=end,
                semantic_hit_frame=anchor.hit_frame,
                hold_reason="reading" if index + 1 < len(hits) else "scene_span",
                layout_profile_id=layout_id,
                layout=layout,
                effect_instance_id=effect.effect_instance_id,
                z_index=0,
            )
        )
    _ = anchored
    return clips, effects


def _compile_single(**kwargs):
    scene = kwargs["scene"]
    span_start = kwargs["span_start"]
    span_end = kwargs["span_end"]
    motion = kwargs["motion"]
    resolved_scene = kwargs["resolved_scene"]
    slot_bindings = kwargs["slot_bindings"]
    anchors_by_id = kwargs["anchors_by_id"]
    anchored = kwargs["anchored"]
    registry = kwargs["registry"]
    layout_id = kwargs["layout_id"]
    layout = kwargs["layout"]
    is_first = kwargs["is_first"]

    if not scene.slots:
        raise Stage6Error("timeline_base_track_gap", "single scene has no slots", scene_id=scene.scene_id)
    slot = scene.slots[0]
    resolved = next((item for item in resolved_scene.slots if item.slot_id == slot.slot_id), None)
    if resolved is None or not resolved.asset_ref:
        raise Stage6Error("timeline_base_track_gap", "single scene missing asset", scene_id=scene.scene_id)
    anchor = _slot_anchor(scene.scene_id, slot.slot_id, slot_bindings, anchors_by_id)
    if anchor is None:
        raise Stage6Error(
            "anchor_unresolved",
            f"single scene slot missing PhraseAnchor: {slot.slot_id}",
            scene_id=scene.scene_id,
            slot_id=slot.slot_id,
        )
    start = span_start if (is_first or slot.entry_policy == "scene_start") else anchor.hit_frame
    if slot.entry_policy == "scene_start":
        start = span_start
    end = span_end
    event = motion.event_intents[0] if motion.event_intents else None
    nxt = next_anchor_hit_frame(anchored, scene_id=scene.scene_id, after_hit=anchor.hit_frame)
    effect = compile_effect_instance(
        motion=motion,
        event_intent=event,
        anchor=anchor,
        scene_end=span_end,
        next_anchor_hit=nxt,
        registry=registry,
        instance_suffix=slot.slot_id,
    )
    clip = CompiledVisualClip(
        clip_id=f"clip://{scene.scene_id}/{slot.slot_id}",
        scene_id=scene.scene_id,
        slot_id=slot.slot_id,
        group_ref=resolved.group_ref,
        member_key=resolved.member_key,
        asset_bindings={"primary": resolved.asset_ref},
        start_frame=start,
        end_frame=end,
        semantic_hit_frame=anchor.hit_frame,
        hold_reason="scene_span",
        layout_profile_id=layout_id,
        layout=layout,
        effect_instance_id=effect.effect_instance_id,
        z_index=0,
    )
    return [clip], [effect]


def _compile_sequence(**kwargs):
    scene = kwargs["scene"]
    span_start = kwargs["span_start"]
    span_end = kwargs["span_end"]
    motion = kwargs["motion"]
    resolved_scene = kwargs["resolved_scene"]
    slot_bindings = kwargs["slot_bindings"]
    op_bindings = kwargs["op_bindings"]
    anchors_by_id = kwargs["anchors_by_id"]
    anchored = kwargs["anchored"]
    registry = kwargs["registry"]
    layout_id = kwargs["layout_id"]
    layout = kwargs["layout"]

    # Order members by resolved member order / slot order.
    slots = list(scene.slots)
    if not slots:
        raise Stage6Error("timeline_base_track_gap", "sequence has no slots", scene_id=scene.scene_id)

    def hit_for(slot_id: str) -> int:
        anchor = _slot_anchor(scene.scene_id, slot_id, slot_bindings, anchors_by_id)
        return anchor.hit_frame if anchor else span_start

    # base = first slot from scene start
    base_slot = slots[0]
    base_resolved = next(item for item in resolved_scene.slots if item.slot_id == base_slot.slot_id)
    base_anchor = _slot_anchor(scene.scene_id, base_slot.slot_id, slot_bindings, anchors_by_id)
    event = motion.event_intents[0] if motion.event_intents else None
    effect = compile_effect_instance(
        motion=motion,
        event_intent=event,
        anchor=base_anchor,
        scene_end=span_end,
        next_anchor_hit=next_anchor_hit_frame(anchored, scene_id=scene.scene_id, after_hit=(base_anchor.hit_frame if base_anchor else span_start)),
        registry=registry,
        instance_suffix="sequence_base",
    )
    clips = [
        CompiledVisualClip(
            clip_id=f"clip://{scene.scene_id}/base",
            scene_id=scene.scene_id,
            slot_id=base_slot.slot_id,
            group_ref=base_resolved.group_ref,
            member_key=base_resolved.member_key,
            asset_bindings={"primary": base_resolved.asset_ref or ""},
            start_frame=span_start,
            end_frame=span_end,
            semantic_hit_frame=base_anchor.hit_frame if base_anchor else span_start,
            hold_reason="scene_span",
            layout_profile_id=layout_id,
            layout=layout,
            effect_instance_id=effect.effect_instance_id,
            z_index=0,
        )
    ]
    overlays: list[CompiledVisualClip] = []
    effects = [effect]
    # stage/final overlays by subsequent slots or operation events
    for index, slot in enumerate(slots[1:], start=1):
        resolved = next((item for item in resolved_scene.slots if item.slot_id == slot.slot_id), None)
        if resolved is None or not resolved.asset_ref:
            continue
        start = hit_for(slot.slot_id)
        end = hit_for(slots[index + 1].slot_id) if index + 1 < len(slots) else span_end
        if end <= start:
            end = min(span_end, start + 1)
        anchor = _slot_anchor(scene.scene_id, slot.slot_id, slot_bindings, anchors_by_id)
        fx = compile_effect_instance(
            motion=motion,
            event_intent=motion.event_intents[index] if index < len(motion.event_intents) else event,
            anchor=anchor,
            scene_end=span_end,
            next_anchor_hit=end if end < span_end else None,
            registry=registry,
            instance_suffix=f"sequence_{slot.slot_id}",
        )
        effects.append(fx)
        overlays.append(
            CompiledVisualClip(
                clip_id=f"clip://{scene.scene_id}/{slot.slot_id}",
                scene_id=scene.scene_id,
                slot_id=slot.slot_id,
                group_ref=resolved.group_ref,
                member_key=resolved.member_key,
                asset_bindings={"primary": resolved.asset_ref},
                start_frame=start,
                end_frame=end,
                semantic_hit_frame=anchor.hit_frame if anchor else start,
                hold_reason="reading",
                layout_profile_id=layout_id,
                layout=layout,
                effect_instance_id=fx.effect_instance_id,
                z_index=index,
            )
        )
    _ = op_bindings
    return clips, overlays, effects


def _compile_multi_asset(**kwargs):
    """One scene-spanning clip with multiple bindings for BeforeAfter / GridReveal / comparison."""
    scene: SemanticScene = kwargs["scene"]
    span_start = kwargs["span_start"]
    span_end = kwargs["span_end"]
    motion = kwargs["motion"]
    resolved_scene = kwargs["resolved_scene"]
    slot_bindings = kwargs["slot_bindings"]
    anchors_by_id = kwargs["anchors_by_id"]
    registry = kwargs["registry"]
    layout_id = kwargs["layout_id"]
    layout = kwargs["layout"]
    instance_suffix = kwargs.get("instance_suffix", "multi")

    items = []
    for slot in scene.slots:
        resolved = next((item for item in resolved_scene.slots if item.slot_id == slot.slot_id), None)
        if resolved is None or not resolved.asset_ref:
            continue
        anchor = _slot_anchor(scene.scene_id, slot.slot_id, slot_bindings, anchors_by_id)
        if anchor is None:
            raise Stage6Error(
                "anchor_unresolved",
                f"multi-asset slot missing anchor: {slot.slot_id}",
                scene_id=scene.scene_id,
            )
        items.append((slot, resolved, anchor))
    if not items:
        raise Stage6Error("timeline_base_track_gap", "multi-asset scene has no assets", scene_id=scene.scene_id)

    bindings: dict[str, str] = {}
    ordered: list[RemotionOrderedItem] = []
    for index, (slot, resolved, anchor) in enumerate(items):
        binding_name = resolved.member_key or slot.slot_id
        bindings[binding_name] = resolved.asset_ref
        if index == 0 or slot.entry_policy == "scene_start":
            item_start = span_start
        else:
            item_start = anchor.hit_frame
        if index + 1 < len(items):
            item_end = items[index + 1][2].hit_frame
        else:
            item_end = span_end
        if item_end <= item_start:
            item_end = min(span_end, item_start + 1)
        ordered.append(
            RemotionOrderedItem(
                item_id=f"{scene.scene_id}:{binding_name}",
                asset_binding_name=binding_name,
                member_key=resolved.member_key,
                start_frame=item_start,
                end_frame=item_end,
                hit_frame=anchor.hit_frame,
            )
        )

    # Reveal event follows the first phrase_start member when present (after / result side).
    reveal_index = next(
        (index for index, (slot, _, _) in enumerate(items) if slot.entry_policy == "phrase_start"),
        min(1, len(items) - 1),
    )
    reveal_anchor = items[reveal_index][2]
    event = (
        motion.event_intents[reveal_index]
        if reveal_index < len(motion.event_intents)
        else (motion.event_intents[0] if motion.event_intents else None)
    )
    effect = compile_effect_instance(
        motion=motion,
        event_intent=event,
        anchor=reveal_anchor,
        scene_end=span_end,
        next_anchor_hit=None,
        registry=registry,
        instance_suffix=instance_suffix,
    )
    clip = CompiledVisualClip(
        clip_id=f"clip://{scene.scene_id}/{instance_suffix}",
        scene_id=scene.scene_id,
        slot_id=None,
        group_ref=items[0][1].group_ref,
        member_key=None,
        asset_bindings=bindings,
        ordered_items=ordered,
        start_frame=span_start,
        end_frame=span_end,
        semantic_hit_frame=items[0][2].hit_frame,
        hold_reason="scene_span",
        layout_profile_id=layout_id,
        layout=layout,
        effect_instance_id=effect.effect_instance_id,
        z_index=0,
    )
    return [clip], [effect]


def _compile_no_asset(**kwargs):
    scene = kwargs["scene"]
    span_start = kwargs["span_start"]
    span_end = kwargs["span_end"]
    motion = kwargs["motion"]
    anchors_by_id = kwargs["anchors_by_id"]
    anchored = kwargs["anchored"]
    registry = kwargs["registry"]
    layout_id = kwargs["layout_id"]
    layout = kwargs["layout"]

    # Use first scene-level anchor if present
    scene_anchors = [a for a in anchored.anchors if a.scene_id == scene.scene_id]
    anchor = scene_anchors[0] if scene_anchors else None
    event = motion.event_intents[0] if motion.event_intents else None
    effect = compile_effect_instance(
        motion=motion,
        event_intent=event,
        anchor=anchor,
        scene_end=span_end,
        next_anchor_hit=None,
        registry=registry,
        instance_suffix="light_sweep",
    )
    clip = CompiledVisualClip(
        clip_id=f"clip://{scene.scene_id}/transition",
        scene_id=scene.scene_id,
        slot_id=None,
        group_ref=None,
        member_key=None,
        asset_bindings={},
        start_frame=span_start,
        end_frame=span_end,
        semantic_hit_frame=anchor.hit_frame if anchor else span_start,
        hold_reason="scene_span",
        layout_profile_id=layout_id,
        layout=layout,
        effect_instance_id=effect.effect_instance_id,
        z_index=0,
    )
    _ = anchors_by_id
    return [clip], [effect]

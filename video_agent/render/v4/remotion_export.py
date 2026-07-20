"""Export Remotion V4Timeline props from CompiledVideoTimeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from video_agent.contracts.v4 import (
    CompiledVideoTimeline,
    RemotionEffectEventProps,
    RemotionEffectProps,
    RemotionOrderedItem,
)
from video_agent.io import write_json_atomic


ADAPTER_IDS = frozenset(
    {
        "none",
        "fade_in",
        "result_reveal",
        "detail_push_in",
        "full_bleed_to_safe_card",
        "spring_card_pop",
        "card_flip_3d",
        "paper_curl_flip",
        "slide_gallery",
        "card_stack",
        "grid_reveal",
        "before_after",
        "light_sweep",
        "brand_breath",
    }
)


def export_remotion_timeline(timeline: CompiledVideoTimeline, output: Path) -> Path:
    missing = [
        instance.effect_id
        for instance in timeline.effect_instances
        if instance.adapter_id not in ADAPTER_IDS and instance.effect_id not in ADAPTER_IDS
    ]
    if missing:
        from video_agent.contracts.v4.stage6_errors import Stage6Error

        raise Stage6Error(
            "adapter_coverage_missing",
            f"missing Remotion adapters: {sorted(set(missing))}",
        )

    from video_agent.compiler.v4.font_measure import DEFAULT_SUBTITLE_FONT_PX
    from video_agent.platform.profiles import get_profile

    platform = get_profile(timeline.platform_profile_id)
    effects: list[dict[str, Any]] = []
    instances = {item.effect_instance_id: item for item in timeline.effect_instances}
    for track in timeline.visual_tracks:
        for clip in track.clips:
            instance = instances[clip.effect_instance_id]
            if clip.ordered_items:
                ordered = list(clip.ordered_items)
            else:
                ordered = [
                    RemotionOrderedItem(
                        item_id=clip.clip_id,
                        asset_binding_name=name,
                        member_key=clip.member_key,
                        start_frame=clip.start_frame,
                        end_frame=clip.end_frame,
                        hit_frame=clip.semantic_hit_frame,
                    )
                    for name in clip.asset_bindings
                ]
            props = RemotionEffectProps(
                effect_instance_id=instance.effect_instance_id,
                effect_id=instance.effect_id,
                effect_version=instance.effect_version,
                variant_id=instance.variant_id,
                start_frame=clip.start_frame,
                end_frame=clip.end_frame,
                events=[
                    RemotionEffectEventProps(
                        event_id=event.event_id,
                        event_type=event.event_type,
                        anchor_id=event.anchor_id,
                        hit_frame=event.hit_frame,
                        start_frame=event.start_frame,
                        end_frame=event.end_frame,
                    )
                    for event in instance.events
                ],
                direction=instance.direction,
                layout=clip.layout,
                parameters=dict(instance.parameters),
                assets=dict(clip.asset_bindings),
                ordered_items=ordered,
            )
            effects.append(props.model_dump(mode="json"))

    payload = {
        "composition_id": "V4Timeline",
        "schema_version": timeline.schema_version,
        "case_id": timeline.case_id,
        "run_id": timeline.run_id,
        "width": timeline.width,
        "height": timeline.height,
        "fps": timeline.fps,
        "frame_count": timeline.frame_count,
        "platform_profile_id": timeline.platform_profile_id,
        "platform_profile": {
            "profile_id": platform.profile_id,
            "canvas": platform.canvas.as_dict(),
            "subtitle_top": platform.subtitle_top.as_dict(),
            "subtitle_lower": platform.subtitle_lower.as_dict(),
            "subtitle_font_px": DEFAULT_SUBTITLE_FONT_PX,
        },
        "render_assets": [item.model_dump(mode="json") for item in timeline.render_assets],
        "visual_tracks": [item.model_dump(mode="json") for item in timeline.visual_tracks],
        "effect_instances": [item.model_dump(mode="json") for item in timeline.effect_instances],
        "effect_props": effects,
        "subtitle_track": [item.model_dump(mode="json") for item in timeline.subtitle_track],
        "audio_tracks": [item.model_dump(mode="json") for item in timeline.audio_tracks],
    }
    write_json_atomic(output, payload)
    return output

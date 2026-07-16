"""Effect capabilities shared by planning, compile-time validation and QA."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EffectPolicy:
    minimum_scene_frames: int = 1
    readable_settle_frames: int = 0
    requires_readable_hold: bool = False


EFFECTS: dict[str, EffectPolicy] = {
    "none": EffectPolicy(),
    "fade_in": EffectPolicy(minimum_scene_frames=6),
    "fade_out": EffectPolicy(minimum_scene_frames=6),
    "scale_in": EffectPolicy(minimum_scene_frames=8),
    "scale_out": EffectPolicy(minimum_scene_frames=8),
    "image_pan_scan": EffectPolicy(minimum_scene_frames=18),
    "detail_push_in": EffectPolicy(minimum_scene_frames=18),
    "result_reveal": EffectPolicy(minimum_scene_frames=12, readable_settle_frames=18, requires_readable_hold=True),
    "full_bleed_to_safe_card": EffectPolicy(minimum_scene_frames=18, readable_settle_frames=12, requires_readable_hold=True),
    "card_flip_3d": EffectPolicy(minimum_scene_frames=24, readable_settle_frames=12, requires_readable_hold=True),
    "paper_curl_flip": EffectPolicy(minimum_scene_frames=30, readable_settle_frames=12, requires_readable_hold=True),
    "spring_card_pop": EffectPolicy(minimum_scene_frames=12, readable_settle_frames=10, requires_readable_hold=True),
    "page_turn_3d": EffectPolicy(minimum_scene_frames=24, readable_settle_frames=12, requires_readable_hold=True),
    "brand_breath": EffectPolicy(minimum_scene_frames=18),
    "film_strip": EffectPolicy(minimum_scene_frames=18),
    "grid_reveal": EffectPolicy(minimum_scene_frames=24, readable_settle_frames=12, requires_readable_hold=True),
    "vertical_scroll": EffectPolicy(minimum_scene_frames=12),
    # The comparison component scales its reveal to the available phrase span;
    # 18 frames is enough for a clear causal hand-off without inventing silence.
    "before_after": EffectPolicy(minimum_scene_frames=18, readable_settle_frames=6, requires_readable_hold=True),
    "slide_gallery": EffectPolicy(minimum_scene_frames=36, readable_settle_frames=12, requires_readable_hold=True),
    "card_stack": EffectPolicy(minimum_scene_frames=36, readable_settle_frames=12, requires_readable_hold=True),
    "light_sweep": EffectPolicy(minimum_scene_frames=12),
}


def get_effect_policy(effect_id: str) -> EffectPolicy:
    try:
        return EFFECTS[effect_id]
    except KeyError as exc:
        raise ValueError(f"unknown effect: {effect_id}") from exc

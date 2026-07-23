from __future__ import annotations

from types import SimpleNamespace

from video_agent.editors.jianying.adapter import (
    _bounded_native_duration_us,
    _duration_us,
    _frame_to_us,
    _native_clip_animation,
    _native_transition_name,
)
from video_agent.editors.jianying.compiler import _effect_keyframes


def test_frame_conversion_preserves_30fps_boundaries() -> None:
    assert _frame_to_us(0, 30) == 0
    assert _frame_to_us(30, 30) == 1_000_000
    assert _duration_us(98, 115, 30) == 566_666


def test_card_stack_compiles_to_bounded_keyframes() -> None:
    frames = _effect_keyframes(
        {
            "effect_id": "card_stack",
            "direction": "right",
            "parameters": {"reveal_frames": 8},
        },
        clip_start=115,
        clip_end=141,
    )

    assert [(item.property, item.frame_offset) for item in frames] == [
        ("scale", 0),
        ("position_x", 0),
        ("scale", 8),
        ("position_x", 8),
    ]


def test_instant_effect_never_places_keyframe_outside_short_clip() -> None:
    frames = _effect_keyframes(
        {
            "effect_id": "fade_in",
            "direction": "none",
            "parameters": {"reveal_frames": 12},
        },
        clip_start=20,
        clip_end=22,
    )

    assert max(item.frame_offset for item in frames) == 1


def test_single_frame_clip_has_no_generated_keyframes() -> None:
    assert (
        _effect_keyframes(
            {
                "effect_id": "fade_in",
                "direction": "none",
                "parameters": {"reveal_frames": 12},
            },
            clip_start=20,
            clip_end=21,
        )
        == []
    )


def test_native_motion_mapping_uses_jianying_assets() -> None:
    first = SimpleNamespace(
        scene_id="s001",
        motion_context="site_home",
        asset_orientation="landscape",
        start_frame=0,
        end_frame=45,
    )
    gallery_a = SimpleNamespace(
        scene_id="s002",
        motion_context="gallery",
        asset_orientation="landscape",
        start_frame=45,
        end_frame=60,
    )
    gallery_b = SimpleNamespace(
        scene_id="s002",
        motion_context="gallery",
        asset_orientation="portrait",
        start_frame=60,
        end_frame=75,
    )

    assert _native_clip_animation(first, is_first_clip=True) == (
        "IntroType",
        "翻入",
    )
    assert _native_transition_name(gallery_a, gallery_b) == "左移"
    assert _native_transition_name(first, gallery_a) == "叠化"
    assert (
        _bounded_native_duration_us(
            gallery_a,
            gallery_b,
            fps=30,
            preferred_frames=10,
        )
        == _frame_to_us(7, 30)
    )


def test_native_motion_selection_ignores_legacy_effect_id() -> None:
    landscape_result = SimpleNamespace(
        motion_context="result",
        asset_orientation="landscape",
        effect_id="legacy_effect_that_must_not_matter",
    )
    portrait_result = SimpleNamespace(
        motion_context="result",
        asset_orientation="portrait",
        effect_id="another_legacy_effect",
    )

    assert _native_clip_animation(
        landscape_result,
        is_first_clip=False,
    ) == ("GroupAnimationType", "左拉镜")
    assert _native_clip_animation(
        portrait_result,
        is_first_clip=False,
    ) == ("IntroType", "轻微放大")

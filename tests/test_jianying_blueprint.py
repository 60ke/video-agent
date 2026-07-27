from __future__ import annotations

from types import SimpleNamespace

from video_agent.editors.jianying.adapter import (
    _bounded_native_duration_us,
    _duration_us,
    _frame_to_us,
    _subtitle_style_size,
    _subtitle_transform_y,
)
from video_agent.editors.jianying.compiler import _effect_keyframes
from video_agent.editors.jianying.contracts import (
    BlueprintCanvas,
    BlueprintVisualClip,
    JianyingEditBlueprint,
)
from video_agent.editors.jianying.native_catalog import (
    NativeEffectCatalog,
    NativeEffectQuery,
    clip_motion_query,
    transition_motion_query,
)


def test_frame_conversion_preserves_30fps_boundaries() -> None:
    assert _frame_to_us(0, 30) == 0
    assert _frame_to_us(30, 30) == 1_000_000
    assert _duration_us(98, 115, 30) == 566_666


def _blueprint() -> JianyingEditBlueprint:
    return JianyingEditBlueprint(
        case_id="case",
        run_id="run",
        timeline_sha256="a" * 64,
        canvas=BlueprintCanvas(
            width=1080,
            height=1920,
            fps=30,
            platform_profile_id="douyin_portrait_v1",
        ),
        frame_count=30,
        visual_clips=[
            BlueprintVisualClip(
                clip_id="clip",
                scene_id="scene",
                source_asset_ref="A0001",
                media_path="asset.png",
                start_frame=0,
                end_frame=30,
                effect_id="fade_in",
            )
        ],
    )


def test_jianying_subtitle_uses_platform_safe_slot() -> None:
    blueprint = _blueprint()

    assert _subtitle_transform_y(blueprint, "subtitle_top") == 0.7958333333333334
    assert _subtitle_transform_y(blueprint, "subtitle_lower") == -0.43541666666666656


def test_jianying_subtitle_size_shrinks_long_text_to_safe_width() -> None:
    blueprint = _blueprint()
    short_size = _subtitle_style_size(
        blueprint,
        text="简单好上手",
        slot_id="subtitle_top",
        style_id="default",
    )
    long_size = _subtitle_style_size(
        blueprint,
        text="全品类统一操作简单好上手而且人人都能快速学会",
        slot_id="subtitle_top",
        style_id="default",
    )

    assert short_size == 5.185
    assert long_size < short_size


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


def test_native_motion_intents_use_catalog_queries() -> None:
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

    intro_intent, intro_query = clip_motion_query(first, is_first_clip=True)
    assert intro_intent == "website_book_open"
    assert intro_query.enum_name == "IntroType"
    assert intro_query.keywords[0] == "翻书"

    gallery_intent, gallery_group, gallery_query = transition_motion_query(
        gallery_a,
        gallery_b,
    )
    assert gallery_intent == "gallery_page_turn"
    assert gallery_group == "gallery:s002"
    assert gallery_query.enum_name == "TransitionType"
    assert gallery_query.keywords[0] == "翻页"

    ordinary_intent, _, ordinary_query = transition_motion_query(first, gallery_a)
    assert ordinary_intent == "scene_soft_transition"
    assert ordinary_query.keywords[0] == "叠化"
    assert _bounded_native_duration_us(
        gallery_a,
        gallery_b,
        fps=30,
        preferred_frames=10,
    ) == _frame_to_us(7, 30)


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

    landscape_intent, landscape_query = clip_motion_query(
        landscape_result,
        is_first_clip=False,
    )
    portrait_intent, portrait_query = clip_motion_query(
        portrait_result,
        is_first_clip=False,
    )

    assert landscape_intent == "landscape_result_focus"
    assert landscape_query.enum_name == "GroupAnimationType"
    assert portrait_intent == "portrait_result_focus"
    assert portrait_query.enum_name == "IntroType"


def test_catalog_prefers_free_candidate_when_requested() -> None:
    class Metadata:
        def __init__(self, title: str, is_vip: bool, effect_id: str) -> None:
            self.title = title
            self.is_vip = is_vip
            self.effect_id = effect_id
            self.duration = 500_000

    class Member:
        def __init__(self, name: str, metadata: Metadata) -> None:
            self.name = name
            self.value = metadata

    fake_draft = SimpleNamespace(
        IntroType=[
            Member("展开", Metadata("展开", True, "vip")),
            Member("渐显", Metadata("渐显", False, "free")),
        ]
    )
    candidate = NativeEffectCatalog(fake_draft).resolve(
        NativeEffectQuery(
            "IntroType",
            ("展开", "渐显"),
            prefer_free=True,
        )
    )

    assert candidate.member_name == "渐显"
    assert candidate.effect_id == "free"

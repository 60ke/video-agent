from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from video_agent.contracts import NarrationBeat, PauseIntent, RenderShot, ShotPlan, TimeRef
from video_agent.effects import get_effect_policy
from video_agent.io import load_json
from video_agent.speech.pause_compiler import compile_beat_markup


def test_pause_intent_compiles_to_provider_markup_without_editorial_cap() -> None:
    beat = NarrationBeat(
        beat_id="beat_001",
        spoken_text="先打开首页，然后进入文生图。",
        pause_intents=[PauseIntent(after_phrase="首页，", kind="section", requested_ms=1000)],
    )

    assert compile_beat_markup(beat) == "先打开首页，<#1.00#>然后进入文生图。"


def test_pause_after_final_phrase_is_not_emitted_as_invalid_markup() -> None:
    beat = NarrationBeat(
        beat_id="beat_001",
        spoken_text="完成生成。",
        pause_intents=[PauseIntent(after_phrase="完成生成。", kind="beat", requested_ms=800)],
    )

    assert compile_beat_markup(beat) == "完成生成。"


def test_effect_policy_distinguishes_feedback_from_reading_hold() -> None:
    assert get_effect_policy("fade_in").requires_readable_hold is False
    assert get_effect_policy("before_after").minimum_scene_frames == 18
    assert get_effect_policy("grid_reveal").readable_settle_frames > 0
    with pytest.raises(ValueError, match="unknown effect"):
        get_effect_policy("unregistered")


def test_site_home_uses_spring_card_pop() -> None:
    config_path = Path(__file__).resolve().parents[1] / "config" / "scene_effects.json"
    scene_effects = load_json(config_path)

    assert scene_effects["scenes"]["site_home"]["motion"] == "spring_card_pop"
    policy = get_effect_policy("spring_card_pop")
    assert policy.minimum_scene_frames == 12
    assert policy.requires_readable_hold is True


def test_gallery_effects_require_multiple_source_assets() -> None:
    base = dict(
        shot_id="shot_001",
        beat_ids=["beat_001"],
        start=TimeRef(anchor_id="timeline_start"),
        end=TimeRef(anchor_id="timeline_end"),
        template="result_showcase",
        asset_bindings={"primary": "result_001"},
    )
    with pytest.raises(ValidationError, match="slide_gallery requires at least two"):
        ShotPlan(**base, motion="slide_gallery")
    with pytest.raises(ValidationError, match="card_stack requires at least two"):
        ShotPlan(**base, motion="card_stack")
    plan = ShotPlan(
        **(base | {"asset_bindings": {"result_001": "result_001", "result_002": "result_002"}}),
        motion="slide_gallery",
    )
    assert plan.motion == "slide_gallery"


def test_light_sweep_fallback_is_the_only_assetless_shot() -> None:
    shot = ShotPlan(
        shot_id="shot_fallback",
        scene_kind="light_sweep_fallback",
        beat_ids=["beat_001"],
        start=TimeRef(anchor_id="timeline_start"),
        end=TimeRef(anchor_id="timeline_end"),
        template="result_showcase",
        motion="light_sweep",
    )
    rendered = RenderShot(
        shot_id="shot_fallback",
        scene_kind="light_sweep_fallback",
        beat_ids=["beat_001"],
        template="result_showcase",
        start_frame=0,
        end_frame=30,
        motion="light_sweep",
    )

    assert shot.asset_bindings == {}
    assert rendered.asset_bindings == {}
    with pytest.raises(ValidationError, match="shots without assets"):
        ShotPlan(
            shot_id="shot_invalid",
            scene_kind="result_detail",
            beat_ids=["beat_001"],
            start=TimeRef(anchor_id="timeline_start"),
            end=TimeRef(anchor_id="timeline_end"),
            template="result_showcase",
            motion="light_sweep",
        )

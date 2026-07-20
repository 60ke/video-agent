from __future__ import annotations

from pathlib import Path

import pytest

from video_agent.contracts.v4 import (
    AnchoredSceneSpan,
    AnchoredTimingPlan,
    MotionAudioPlan,
    ResolvedAssetPlan,
    ResolvedSceneAssets,
    ResolvedSlot,
    SceneSemanticPlan,
    SpeechTimingLock,
    SpeechTokenTimingV4,
    validate_motion_audio_plan,
)
from video_agent.io import load_json, sha256_json
from video_agent.motion.v4.planner import build_motion_audio_plan
from video_agent.motion.v4.sfx_intents import _apply_profile_density
from video_agent.motion.v4.timing_budget import scene_budget_ms
from video_agent.registries import CapabilityRegistryHub
from video_agent.timing.v4.anchor_compiler import build_anchored_timing_plan


FIXTURE = Path(__file__).parent / "fixtures" / "v4" / "stage0"


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(Path(__file__).parents[1] / "config" / "registries" / "v4")


def _anchored_for_scenes(scene_plan: SceneSemanticPlan, *, fps: int = 30) -> AnchoredTimingPlan:
    tokens: list[SpeechTokenTimingV4] = []
    cursor_ms = 0
    for scene in sorted(scene_plan.scenes, key=lambda item: item.order):
        duration_ms = max(len(scene.text) * 120, 2500)
        start_ms = cursor_ms
        end_ms = cursor_ms + duration_ms
        start_frame = int(round(start_ms * fps / 1000))
        end_frame = max(start_frame + 1, int(round(end_ms * fps / 1000)))
        tokens.append(
            SpeechTokenTimingV4(
                token_id=f"tok_{scene.scene_id}",
                text=scene.text,
                start_ms=start_ms,
                end_ms=end_ms,
                start_frame=start_frame,
                end_frame=end_frame,
                beat_id=scene.scene_id,
            )
        )
        cursor_ms = end_ms
    speech = SpeechTimingLock(
        schema_version=1,
        case_id="stage5-test",
        run_id="run",
        narration_sha256="a" * 64,
        audio_object_key="audio/speech.wav",
        audio_sha256="a" * 64,
        voice_profile_id="voice",
        voice_profile_version="1",
        voice_profile_sha256="a" * 64,
        fps=fps,
        duration_ms=cursor_ms,
        duration_frames=max(1, int(round(cursor_ms * fps / 1000))),
        tokens=tokens,
        pause_events=[],
        beat_spans=[],
    )
    return build_anchored_timing_plan(
        case_id="stage5-test",
        run_id="run",
        narration_sha256="a" * 64,
        speech=speech,
        scene_plan=scene_plan,
    )


def _resolved_from_plan(scene_plan: SceneSemanticPlan) -> ResolvedAssetPlan:
    scenes: list[ResolvedSceneAssets] = []
    for scene in sorted(scene_plan.scenes, key=lambda item: item.order):
        slots: list[ResolvedSlot] = []
        for index, slot in enumerate(scene.slots, start=1):
            member_key = None
            group_ref = None
            source = slot.source
            if getattr(source, "member_key", None):
                member_key = source.member_key
                group_ref = f"group://G{index:04d}"
            if scene.no_asset:
                status = "resolved_no_asset"
                asset_ref = None
            elif member_key:
                status = "resolved_group_member"
                asset_ref = f"asset://A{index:04d}"
            else:
                status = "resolved_asset"
                asset_ref = f"asset://A{index:04d}"
            slots.append(
                ResolvedSlot(
                    slot_id=slot.slot_id,
                    status=status,
                    asset_ref=asset_ref,
                    group_ref=group_ref,
                    member_key=member_key,
                )
            )
        scenes.append(
            ResolvedSceneAssets(
                scene_id=scene.scene_id,
                slots=slots,
                inputs={},
                outputs={},
            )
        )
    return ResolvedAssetPlan(
        schema_version=1,
        run_seed="motion",
        scene_plan_sha256="b" * 64,
        repository_base_revision=0,
        pre_run_repository_fingerprint="c" * 64,
        used_assets_snapshot_id="snapshot://test",
        post_run_repository_revision=0,
        post_run_repository_fingerprint="d" * 64,
        registry_snapshot_id="registry-snapshot://sha256/" + ("e" * 64),
        scenes=scenes,
    )


def test_motion_audio_plan_stage0_s001_to_s010(hub: CapabilityRegistryHub) -> None:
    scene_plan = SceneSemanticPlan.model_validate(load_json(FIXTURE / "scene_semantic_plan.payload.json"))
    resolved = _resolved_from_plan(scene_plan)
    anchored = _anchored_for_scenes(scene_plan)
    plan = build_motion_audio_plan(
        registry=hub,
        scene_plan=scene_plan,
        resolved_assets=resolved,
        anchored_timing=anchored,
        run_seed="golden-motion",
        registry_snapshot_id="registry-snapshot://sha256/" + ("f" * 64),
    )
    assert isinstance(plan, MotionAudioPlan)
    assert plan.anchored_timing_plan_sha256 == sha256_json(anchored)
    assert [scene.scene_id for scene in plan.scenes] == [f"s{index:03d}" for index in range(1, 11)]
    by_id = {scene.scene_id: scene for scene in plan.scenes}

    assert by_id["s002"].effect.effect_id in {"slide_gallery", "card_stack", "grid_reveal"}
    assert by_id["s002"].continuity_group_id == "gallery:s002"
    assert by_id["s002"].effect.direction in {"left", "right"}
    assert len(by_id["s002"].event_intents) == 3
    assert {event.anchor_phrase for event in by_id["s002"].event_intents} == {"文化墙", "门头招牌", "美陈"}

    assert by_id["s004"].continuity_group_id == "sequence:culture_wall_parameters"
    assert by_id["s007"].continuity_group_id == "comparison:culture_wall_reference_flow"
    assert by_id["s008"].continuity_group_id == "comparison:culture_wall_reference_flow"
    assert by_id["s007"].effect.effect_id == by_id["s008"].effect.effect_id
    assert by_id["s007"].effect.direction == by_id["s008"].effect.direction

    assert by_id["s009"].effect.effect_id in {"light_sweep", "none"}
    assert not any(
        key in plan.model_dump(mode="json")
        for key in ("start_frame", "end_frame", "hit_frame")
    )
    dumped = plan.model_dump(mode="json")
    assert "start_frame" not in str(dumped)

    assert plan.sfx_profile.profile_id == "normal"
    assert any(intent.source_kind == "operation_semantic" for intent in plan.sfx_intents)
    assert any(intent.sfx_id == "typing" for intent in plan.sfx_intents)
    validate_motion_audio_plan(plan, scene_plan)


def test_motion_assignment_is_deterministic(hub: CapabilityRegistryHub) -> None:
    scene_plan = SceneSemanticPlan.model_validate(load_json(FIXTURE / "scene_semantic_plan.payload.json"))
    resolved = _resolved_from_plan(scene_plan)
    anchored = _anchored_for_scenes(scene_plan)
    first = build_motion_audio_plan(
        registry=hub,
        scene_plan=scene_plan,
        resolved_assets=resolved,
        anchored_timing=anchored,
        run_seed="seed-x",
        registry_snapshot_id="registry-snapshot://sha256/" + ("1" * 64),
    )
    second = build_motion_audio_plan(
        registry=hub,
        scene_plan=scene_plan,
        resolved_assets=resolved,
        anchored_timing=anchored,
        run_seed="seed-x",
        registry_snapshot_id="registry-snapshot://sha256/" + ("1" * 64),
    )
    assert sha256_json(first) == sha256_json(second)


def test_effect_binding_rejects_frame_parameters() -> None:
    from video_agent.contracts.v4 import EffectBinding

    with pytest.raises(Exception):
        EffectBinding(
            effect_id="fade_in",
            effect_version="1",
            layout_profile_id="douyin_safe",
            direction="none",
            parameters={"start_frame": 12},
        )


def test_scene_budget_uses_exact_span_only() -> None:
    anchored = AnchoredTimingPlan(
        schema_version=1,
        case_id="c",
        run_id="r",
        narration_sha256="a" * 64,
        speech_timing_lock_sha256="a" * 64,
        scene_plan_sha256="a" * 64,
        fps=30,
        duration_frames=90,
        scene_spans=[
            AnchoredSceneSpan(scene_id="s001", token_ids=["t1"], start_frame=0, end_frame=60),
        ],
        anchors=[],
        bindings=[],
    )
    assert scene_budget_ms(anchored, "s001") == 2000
    with pytest.raises(Exception):
        scene_budget_ms(anchored, "missing")


def test_sfx_density_does_not_truncate_distinct_anchors(hub: CapabilityRegistryHub) -> None:
    from video_agent.contracts.v4 import SfxIntent

    profile = hub.entry("sfx_profile", "normal")
    intents = [
        SfxIntent(
            intent_id=f"sfx:s002.{index}",
            scene_id="s002",
            event_id=None,
            source_kind="effect_event",
            anchor_phrase=phrase,
            sfx_id="transition_whoosh",
            priority=50,
        )
        for index, phrase in enumerate(["文化墙", "门头招牌", "美陈", "LOGO", "海报"])
    ]
    kept = _apply_profile_density(intents, profile)
    assert len(kept) == 5

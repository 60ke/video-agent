from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from video_agent.compiler.v4.timeline import compile_video_timeline
from video_agent.compiler.v4.validation import validate_compiled_timeline
from video_agent.contracts.v4 import (
    AssetQuerySource,
    AssetRepositorySnapshot,
    AssetRepositorySnapshotAsset,
    AssetStatus,
    EvidenceClass,
    MaterialSlot,
    ResolvedAssetPlan,
    ResolvedSceneAssets,
    ResolvedSlot,
    SceneSemanticPlan,
    SemanticScene,
    SpeechTimingLock,
    SpeechTokenTimingV4,
)
from video_agent.io import sha256_file
from video_agent.motion.v4.planner import build_motion_audio_plan
from video_agent.registries import CapabilityRegistryHub
from video_agent.render.v4.material_resolver import resolve_materials
from video_agent.timing.v4.anchor_compiler import build_anchored_timing_plan


def test_compile_single_scene_timeline(tmp_path: Path) -> None:
    hub = CapabilityRegistryHub.load(Path(__file__).parents[1] / "config" / "registries" / "v4")
    objects = tmp_path / "objects"
    objects.mkdir()
    png = objects / "A0001.png"
    Image.new("RGB", (640, 480), (20, 40, 80)).save(png)
    digest = sha256_file(png)

    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="打开文化墙",
                visual_structure="single",
                slots=[
                    MaterialSlot(
                        slot_id="main",
                        anchor_phrase="文化墙",
                        entry_policy="scene_start",
                        hold_policy="scene_end",
                        category_id=None,
                        asset_role="feature_entry",
                        source=AssetQuerySource(kind="asset_query"),
                        subtitle_emphasis="keyword",
                    )
                ],
                events=[],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=False,
            )
        ]
    )
    tokens = [
        SpeechTokenTimingV4(
            token_id="tok_0000",
            text="打开",
            start_ms=0,
            end_ms=300,
            start_frame=0,
            end_frame=9,
            beat_id=None,
        ),
        SpeechTokenTimingV4(
            token_id="tok_0001",
            text="文化墙",
            start_ms=300,
            end_ms=800,
            start_frame=9,
            end_frame=24,
            beat_id=None,
        ),
    ]
    speech = SpeechTimingLock(
        schema_version=1,
        case_id="case",
        run_id="run",
        narration_sha256="a" * 64,
        audio_object_key="audio/speech.wav",
        audio_sha256="a" * 64,
        voice_profile_id="v",
        voice_profile_version="1",
        voice_profile_sha256="a" * 64,
        fps=30,
        duration_ms=800,
        duration_frames=24,
        tokens=tokens,
        pause_events=[],
        beat_spans=[],
    )
    anchored = build_anchored_timing_plan(
        case_id="case",
        run_id="run",
        narration_sha256="a" * 64,
        speech=speech,
        scene_plan=scene_plan,
    )
    resolved = ResolvedAssetPlan(
        schema_version=1,
        run_seed="s",
        scene_plan_sha256="b" * 64,
        repository_base_revision=0,
        pre_run_repository_fingerprint="c" * 64,
        used_assets_snapshot_id="asset-snapshot://sha256/" + ("d" * 64),
        post_run_repository_revision=0,
        post_run_repository_fingerprint="e" * 64,
        registry_snapshot_id="registry-snapshot://sha256/" + ("f" * 64),
        scenes=[
            ResolvedSceneAssets(
                scene_id="s001",
                slots=[
                    ResolvedSlot(
                        slot_id="main",
                        status="resolved_asset",
                        asset_ref="asset://A0001",
                        group_ref=None,
                        member_key=None,
                    )
                ],
                inputs={},
                outputs={},
            )
        ],
    )
    motion = build_motion_audio_plan(
        registry=hub,
        scene_plan=scene_plan,
        resolved_assets=resolved,
        anchored_timing=anchored,
        run_seed="seed",
        registry_snapshot_id="registry-snapshot://sha256/" + ("f" * 64),
    )
    motion = motion.model_copy(update={"sfx_intents": []})
    snapshot = AssetRepositorySnapshot(
        snapshot_id="asset-snapshot://sha256/" + ("d" * 64),
        created_at=datetime.now(timezone.utc),
        repository_schema_version=4,
        content_sha256="a" * 64,
        assets=[
            AssetRepositorySnapshotAsset(
                asset_ref="asset://A0001",
                object_key="objects/A0001.png",
                content_sha256=digest,
                status=AssetStatus.ACTIVE,
                lineage_sha256=None,
                evidence_class=EvidenceClass.SOURCE,
                claims=[],
            )
        ],
        groups=[],
    )
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "speech.wav").write_bytes(b"RIFF")
    timeline, report, _audit = compile_video_timeline(
        case_id="case",
        run_id="run",
        speech=speech,
        scene_plan=scene_plan,
        anchored=anchored,
        resolved=resolved,
        motion_plan=motion,
        snapshot=snapshot,
        registry=hub,
        repo_root=tmp_path,
        object_store_root=tmp_path,
    )
    assert report["ok"] is True
    assert timeline.frame_count == 24
    assert timeline.render_assets[0].width == 640
    assert timeline.render_assets[0].height == 480
    base = next(track for track in timeline.visual_tracks if track.track_kind == "base")
    assert base.clips[0].start_frame == 0
    assert base.clips[0].end_frame == 24
    assert validate_compiled_timeline(timeline)["ok"]
    assert any(
        "reveal_frames" in instance.parameters for instance in timeline.effect_instances if instance.events
    )


def test_material_resolver_copies_relative(tmp_path: Path) -> None:
    from video_agent.contracts.v4 import (
        CompiledAudioTrackV4,
        CompiledRenderAsset,
        CompiledVideoTimeline,
        CompiledVisualTrack,
    )

    src = tmp_path / "objects"
    src.mkdir()
    blob = src / "A0001.png"
    Image.new("RGB", (320, 240), (10, 20, 30)).save(blob)
    digest = sha256_file(blob)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    timeline = CompiledVideoTimeline(
        schema_version=1,
        case_id="c",
        run_id="r",
        width=1080,
        height=1920,
        fps=30,
        narration_frame_count=30,
        postroll_frames=0,
        frame_count=30,
        platform_profile_id="douyin_portrait_v1",
        registry_snapshot_id="reg",
        speech_timing_lock_sha256="a" * 64,
        anchored_timing_plan_sha256="a" * 64,
        resolved_asset_plan_sha256="a" * 64,
        motion_audio_plan_sha256="a" * 64,
        used_assets_snapshot_id="snap",
        render_assets=[
            CompiledRenderAsset(
                asset_ref="asset://A0001",
                object_key="objects/A0001.png",
                sha256=digest,
                media_kind="image",
                width=320,
                height=240,
            )
        ],
        visual_tracks=[CompiledVisualTrack(track_id="base", track_kind="base", clips=[])],
        effect_instances=[],
        subtitle_track=[],
        audio_tracks=[
            CompiledAudioTrackV4(
                track_id="voice://main",
                kind="voice",
                object_key="audio/speech.wav",
                sha256="a" * 64,
                start_frame=0,
            )
        ],
    )
    (run_dir / "audio").mkdir()
    (run_dir / "audio" / "speech.wav").write_bytes(b"RIFF")
    resolved = resolve_materials(
        timeline=timeline,
        run_dir=run_dir,
        object_store_root=tmp_path,
        repo_root=tmp_path,
    )
    assert resolved.render_assets[0].object_key.startswith("assets/")
    assert resolved.render_assets[0].width == 320
    assert resolved.render_assets[0].height == 240
    assert not Path(resolved.render_assets[0].object_key).is_absolute()
    assert (run_dir / "render" / resolved.render_assets[0].object_key).is_file()


def test_anchored_plan_not_rewritten_by_assert(tmp_path: Path) -> None:
    from video_agent.contracts.v4 import EffectBinding, EffectEventIntent, MotionAudioPlan, SceneMotionIntent
    from video_agent.v4.stage6 import _assert_intent_phrases_bound
    from video_agent.contracts.v4 import AnchoredSceneSpan, AnchoredTimingPlan, PhraseAnchorV4

    anchored = AnchoredTimingPlan(
        schema_version=1,
        case_id="c",
        run_id="r",
        narration_sha256="a" * 64,
        speech_timing_lock_sha256="a" * 64,
        scene_plan_sha256="a" * 64,
        fps=30,
        duration_frames=30,
        scene_spans=[AnchoredSceneSpan(scene_id="s001", token_ids=["t1"], start_frame=0, end_frame=30)],
        anchors=[
            PhraseAnchorV4(
                anchor_id="a1",
                scene_id="s001",
                text="文化墙",
                token_ids=["t1"],
                onset_ms=0,
                end_ms=100,
                onset_frame=0,
                end_frame=3,
                hit_frame=0,
            )
        ],
        bindings=[],
    )
    before = anchored.model_dump(mode="json")
    motion = MotionAudioPlan(
        schema_version=1,
        run_seed="s",
        scene_plan_sha256="a" * 64,
        resolved_asset_plan_sha256="a" * 64,
        speech_timing_lock_sha256="a" * 64,
        anchored_timing_plan_sha256="a" * 64,
        registry_snapshot_id="reg",
        scenes=[
            SceneMotionIntent(
                scene_id="s001",
                continuity_group_id=None,
                effect=EffectBinding(
                    effect_id="fade_in",
                    effect_version="1",
                    layout_profile_id="douyin_safe",
                    direction="none",
                    parameters={},
                ),
                event_intents=[
                    EffectEventIntent(
                        event_id="e1",
                        event_type="enter",
                        slot_id="main",
                        member_key=None,
                        anchor_phrase="文化墙",
                    )
                ],
            )
        ],
        sfx_profile=__import__("video_agent.contracts.v4.motion_audio", fromlist=["FrozenSfxProfileRef"]).FrozenSfxProfileRef(
            profile_id="normal",
            profile_version="1",
            content_sha256="a" * 64,
        ),
        sfx_intents=[],
    )
    _assert_intent_phrases_bound(anchored, motion)
    assert anchored.model_dump(mode="json") == before


def test_stage6_input_fingerprint_excludes_timeline_hash() -> None:
    """Resume must compare pre-compile inputs only; timeline hash is output-side."""
    from video_agent.v4.stage6_fingerprint import build_stage6_fingerprint_components
    from video_agent.io import sha256_json

    repo_root = Path(__file__).parents[1]
    components = build_stage6_fingerprint_components(
        repo_root=repo_root,
        base={
            "speech_timing_lock_sha256": "a" * 64,
            "anchored_timing_plan_sha256": "b" * 64,
            "resolved_asset_plan_sha256": "c" * 64,
            "motion_audio_plan_sha256": "d" * 64,
            "used_assets_snapshot_id": "snap",
            "registry_snapshot_id": "reg",
            "postroll_frames": 0,
            "platform_profile_id": "douyin_portrait_v1",
        },
    )
    assert "compiled_video_timeline_sha256" not in components
    first = sha256_json(components)
    second = sha256_json(components)
    assert first == second

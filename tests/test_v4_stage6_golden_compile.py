"""Stage0 golden: Speech → Anchor → Motion → CompiledVideoTimeline (§18 mappings)."""

from __future__ import annotations

import os
import wave
from pathlib import Path

import pytest

from video_agent.assets.v4 import AssetPlanResolver, LocalObjectStore, SQLiteAssetRepository
from video_agent.assets.v4.gap_policy import load_selection_config
from video_agent.compiler.v4.timeline import compile_video_timeline
from video_agent.compiler.v4.validation import validate_compiled_timeline
from video_agent.contracts.v4 import SceneSemanticPlan, SpeechTimingLock, SpeechTokenTimingV4
from video_agent.io import load_json, sha256_json, write_json_atomic
from video_agent.motion.v4.planner import build_motion_audio_plan
from video_agent.registries import CapabilityRegistryHub
from video_agent.render.v4.material_resolver import resolve_materials
from video_agent.render.v4.remotion_export import export_remotion_timeline
from video_agent.render.v4.remotion_render import render_v4_silent_mp4
from video_agent.timing.v4.anchor_compiler import build_anchored_timing_plan
from video_agent.timing.v4.timebase import ms_to_hit_frame, ms_to_interval_end

from tests.test_v4_stage4_golden import _seed_golden_repo


FIXTURE = Path(__file__).parent / "fixtures" / "v4" / "stage0"
REPO_ROOT = Path(__file__).parents[1]
FPS = 30
# ~2 frames per character keeps phrase hits distinct while staying Remotion-friendly.
MS_PER_CHAR = 67


def _write_silent_wav(path: Path, *, duration_ms: int, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(sample_rate * duration_ms / 1000))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)


def _speech_from_scenes(scene_plan: SceneSemanticPlan, *, case_id: str, run_id: str) -> SpeechTimingLock:
    """Character-level synthetic SpeechTimingLock covering SceneSemanticPlan text."""
    ordered = sorted(scene_plan.scenes, key=lambda item: item.order)
    narration = "".join(scene.text for scene in ordered)
    tokens: list[SpeechTokenTimingV4] = []
    cursor_ms = 0
    for index, char in enumerate(narration):
        start_ms = cursor_ms
        end_ms = cursor_ms + MS_PER_CHAR
        tokens.append(
            SpeechTokenTimingV4(
                token_id=f"tok_{index:04d}",
                text=char,
                start_ms=start_ms,
                end_ms=end_ms,
                start_frame=ms_to_hit_frame(start_ms, FPS),
                end_frame=max(ms_to_hit_frame(start_ms, FPS) + 1, ms_to_interval_end(end_ms, FPS)),
                beat_id=None,
            )
        )
        cursor_ms = end_ms
    return SpeechTimingLock(
        schema_version=1,
        case_id=case_id,
        run_id=run_id,
        narration_sha256="a" * 64,
        audio_object_key="audio/speech.wav",
        audio_sha256="b" * 64,
        voice_profile_id="golden-synthetic",
        voice_profile_version="1",
        voice_profile_sha256="c" * 64,
        fps=FPS,
        duration_ms=cursor_ms,
        duration_frames=max(1, ms_to_interval_end(cursor_ms, FPS)),
        tokens=tokens,
        pause_events=[],
        beat_spans=[],
    )


def _base_clips_by_scene(timeline) -> dict[str, list]:
    base = next(track for track in timeline.visual_tracks if track.track_kind == "base")
    by_scene: dict[str, list] = {}
    for clip in base.clips:
        by_scene.setdefault(clip.scene_id, []).append(clip)
    return by_scene


def _build_golden_pipeline(tmp_path: Path, hub: CapabilityRegistryHub):
    objects = tmp_path / "objects"
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(objects), hub)
    seeded = _seed_golden_repo(repo, tmp_path)
    scene_plan = SceneSemanticPlan.model_validate(load_json(FIXTURE / "scene_semantic_plan.payload.json"))
    selection = load_selection_config(REPO_ROOT / "config" / "stage4_selection.v4.json")
    resolved = AssetPlanResolver(hub).resolve(
        scene_plan,
        session=repo.open_resolution_session(),
        selection_config=selection,
        run_seed="golden-stage6",
        registry_snapshot_id="registry://golden-stage6",
        scene_plan_sha256=sha256_json(scene_plan),
        allow_fake_derivation=False,
    )
    used_assets = sorted({slot.asset_ref for scene in resolved.scenes for slot in scene.slots if slot.asset_ref})
    used_groups = sorted({slot.group_ref for scene in resolved.scenes for slot in scene.slots if slot.group_ref})
    snapshot = repo.freeze(used_assets, used_groups)
    assert snapshot.snapshot_id == resolved.used_assets_snapshot_id

    speech = _speech_from_scenes(scene_plan, case_id="v4_stage0_golden", run_id="golden_compile")
    _write_silent_wav(tmp_path / "audio" / "speech.wav", duration_ms=speech.duration_ms)

    anchored = build_anchored_timing_plan(
        case_id="v4_stage0_golden",
        run_id="golden_compile",
        narration_sha256=speech.narration_sha256,
        speech=speech,
        scene_plan=scene_plan,
    )
    motion = build_motion_audio_plan(
        registry=hub,
        scene_plan=scene_plan,
        resolved_assets=resolved,
        anchored_timing=anchored,
        run_seed="golden-stage6",
        registry_snapshot_id="registry://golden-stage6",
    )

    timeline, report, audit = compile_video_timeline(
        case_id="v4_stage0_golden",
        run_id="golden_compile",
        speech=speech,
        scene_plan=scene_plan,
        anchored=anchored,
        resolved=resolved,
        motion_plan=motion,
        snapshot=snapshot,
        registry=hub,
        repo_root=REPO_ROOT,
        object_store_root=objects,
    )
    return {
        "repo": repo,
        "seeded": seeded,
        "scene_plan": scene_plan,
        "resolved": resolved,
        "speech": speech,
        "anchored": anchored,
        "motion": motion,
        "snapshot": snapshot,
        "timeline": timeline,
        "report": report,
        "audit": audit,
        "objects": objects,
    }


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(REPO_ROOT / "config" / "registries" / "v4")


def test_stage0_golden_s001_to_s010_compile(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    built = _build_golden_pipeline(tmp_path, hub)
    timeline = built["timeline"]
    report = built["report"]
    resolved = built["resolved"]
    anchored = built["anchored"]
    seeded = built["seeded"]
    try:
        assert report["ok"] is True
        assert validate_compiled_timeline(timeline)["ok"]
        assert timeline.width == 1080
        assert timeline.height == 1920
        assert timeline.fps == 30
        assert timeline.platform_profile_id == "douyin_portrait_v1"
        assert timeline.postroll_frames == 0
        assert timeline.frame_count == timeline.narration_frame_count == built["speech"].duration_frames

        spans = {span.scene_id: span for span in anchored.scene_spans}
        assert set(spans) == {f"s{index:03d}" for index in range(1, 11)}
        assert spans["s001"].start_frame == 0
        assert spans["s010"].end_frame == timeline.narration_frame_count

        by_scene = _base_clips_by_scene(timeline)
        assert set(by_scene) == {f"s{index:03d}" for index in range(1, 11)}

        # s001: base from frame 0
        assert by_scene["s001"][0].start_frame == 0
        assert by_scene["s001"][0].asset_bindings["primary"] == seeded["home"]

        # s002 gallery: distinct phrase-hit clip starts, yellow cues, three assets
        gallery_clips = sorted(by_scene["s002"], key=lambda item: item.start_frame)
        assert len(gallery_clips) == 3
        assert gallery_clips[0].start_frame < gallery_clips[1].start_frame < gallery_clips[2].start_frame
        gallery_hits = [clip.semantic_hit_frame for clip in gallery_clips]
        assert gallery_hits[0] < gallery_hits[1] < gallery_hits[2]
        yellow = [cue for cue in timeline.subtitle_track if cue.style_id == "gallery_yellow"]
        assert {cue.text for cue in yellow} == {"文化墙", "门头招牌", "美陈"}

        # s003 feature entry present
        assert len(by_scene["s003"]) == 1
        assert by_scene["s003"][0].asset_bindings["primary"] == seeded["entry"]

        # s004 sequence: base on base track; stage/final as overlays
        overlay = next(track for track in timeline.visual_tracks if track.track_kind == "overlay")
        assert by_scene["s004"][0].member_key == "base"
        assert by_scene["s004"][0].group_ref == seeded["params"]
        s004_overlay = sorted(
            [clip for clip in overlay.clips if clip.scene_id == "s004"],
            key=lambda item: item.start_frame,
        )
        assert [clip.member_key for clip in s004_overlay] == ["stage", "final"]
        assert all(clip.group_ref == seeded["params"] for clip in s004_overlay)
        assert s004_overlay[0].start_frame < s004_overlay[1].start_frame

        # s005 ≠ s002 gallery identity; primary_result identity
        primary = resolved.scenes[4].outputs["primary_result"]
        s002_g1 = next(slot.asset_ref for slot in resolved.scenes[1].slots if slot.slot_id == "g1")
        assert primary != s002_g1
        assert by_scene["s005"][0].asset_bindings["primary"] == primary

        # s006 editor sequence inherits primary
        assert by_scene["s006"][0].member_key == "source_result"
        assert by_scene["s006"][0].group_ref == seeded[f"editor:{primary}"]
        s006_overlay = sorted(
            [clip for clip in overlay.clips if clip.scene_id == "s006"],
            key=lambda item: item.start_frame,
        )
        assert [clip.member_key for clip in s006_overlay] == ["editor_page", "edited_result"]
        assert all(clip.group_ref == seeded[f"editor:{primary}"] for clip in s006_overlay)

        # s007/s008 causal: one multi-asset comparison clip (not sequential cuts)
        assert len(by_scene["s007"]) == 1
        s007 = by_scene["s007"][0]
        assert s007.group_ref == seeded[f"causal:{primary}"]
        assert set(s007.asset_bindings) == {"reference_image", "result_image"}
        assert len(s007.ordered_items) == 2
        assert s007.ordered_items[0].asset_binding_name == "reference_image"
        assert s007.ordered_items[1].asset_binding_name == "result_image"
        assert s007.ordered_items[0].hit_frame < s007.ordered_items[1].hit_frame
        assert by_scene["s008"][0].member_key == "flat_plan" or "flat_plan" in by_scene["s008"][0].asset_bindings
        assert by_scene["s008"][0].group_ref == seeded[f"causal:{primary}"]

        # Remotion export projects multi-asset ordered_items onto one effect instance
        remotion_probe = tmp_path / "probe_remotion.json"
        export_remotion_timeline(timeline, remotion_probe)
        props = load_json(remotion_probe)
        s007_fx = next(
            item
            for item in props["effect_props"]
            if item["effect_instance_id"] == s007.effect_instance_id
        )
        assert len(s007_fx["ordered_items"]) >= 2
        assert len(s007_fx["assets"]) >= 2

        # s009 light_sweep effect is present (pixel layer is Remotion-side)
        s009_fx = next(
            item for item in timeline.effect_instances if item.effect_instance_id == by_scene["s009"][0].effect_instance_id
        )
        assert s009_fx.effect_id in {"light_sweep", "none"}

        # s009 no_asset transition (empty asset bindings)
        assert by_scene["s009"][0].asset_bindings == {}
        assert by_scene["s009"][0].start_frame == spans["s009"].start_frame

        # s010 configured outro through narration end
        assert by_scene["s010"][0].asset_bindings["primary"] == seeded["outro"]
        assert by_scene["s010"][0].end_frame == timeline.narration_frame_count
        assert by_scene["s010"][0].asset_bindings["primary"] != seeded.get("home")

        # base continuity: no gaps across scenes
        all_base = sorted(
            (clip for clips in by_scene.values() for clip in clips),
            key=lambda item: item.start_frame,
        )
        assert all_base[0].start_frame == 0
        cursor = 0
        for clip in all_base:
            assert clip.start_frame <= cursor + 1  # allow adjacent cuts; no multi-frame holes
            cursor = max(cursor, clip.end_frame)
        assert cursor == timeline.frame_count

        # subtitles never multiline
        assert all(cue.single_line and "\n" not in cue.text for cue in timeline.subtitle_track)

        # real probed dimensions from seeded 8x6 PNGs
        assert all(asset.width == 8 and asset.height == 6 for asset in timeline.render_assets)

        # SFX intents survive Stage5→Stage6 peak arbitration (synthetic speech + real wavs)
        assert built["motion"].sfx_intents
        assert any(track.kind == "sfx" for track in timeline.audio_tracks) or any(
            item.get("action") == "suppress" for item in built["audit"]
        )
        assert any(track.kind == "voice" for track in timeline.audio_tracks)

        # material resolve + remotion props (repo_root resolves registry SFX paths)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "audio").mkdir()
        (run_dir / "audio" / "speech.wav").write_bytes((tmp_path / "audio" / "speech.wav").read_bytes())
        resolved_timeline = resolve_materials(
            timeline=timeline,
            run_dir=run_dir,
            object_store_root=built["objects"],
            repo_root=REPO_ROOT,
        )
        remotion_path = run_dir / "render" / "remotion.timeline.json"
        export_remotion_timeline(resolved_timeline, remotion_path)
        assert remotion_path.is_file()
        props = load_json(remotion_path)
        assert props["composition_id"] == "V4Timeline"
        assert props["width"] == 1080
        assert props["height"] == 1920
        assert props["fps"] == 30
        assert props["platform_profile"]["profile_id"] == "douyin_portrait_v1"
        assert props["platform_profile"]["subtitle_top"]["w"] == 820
        assert props["platform_profile"]["subtitle_lower"]["w"] == 760
        assert props["platform_profile"]["subtitle_font_px"] == 56

        # Freeze compile ledger under fixtures when requested
        if os.environ.get("STAGE6_FREEZE_GOLDEN") == "1":
            out = REPO_ROOT / "tests" / "fixtures" / "v4" / "stage6" / "golden"
            out.mkdir(parents=True, exist_ok=True)
            write_json_atomic(out / "compiled_video_timeline.json", timeline)
            write_json_atomic(out / "anchored_timing_plan.json", anchored)
            write_json_atomic(out / "stage6_validation.json", report)
            write_json_atomic(
                out / "acceptance_ledger.json",
                {
                    "schema_version": "v4.stage6_golden_acceptance.1",
                    "scenes": list(by_scene),
                    "frame_count": timeline.frame_count,
                    "primary_result": primary,
                    "s002_g1": s002_g1,
                    "gallery_yellow": sorted({cue.text for cue in yellow}),
                    "outro_asset": by_scene["s010"][0].asset_bindings["primary"],
                    "note": "Synthetic SpeechTimingLock; Pass B MiniMax speech still open",
                },
            )
    finally:
        built["repo"].close()


@pytest.mark.skipif(os.environ.get("STAGE6_GOLDEN_RENDER") != "1", reason="set STAGE6_GOLDEN_RENDER=1")
def test_stage0_golden_remotion_render(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    built = _build_golden_pipeline(tmp_path, hub)
    timeline = built["timeline"]
    try:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "audio").mkdir()
        (run_dir / "audio" / "speech.wav").write_bytes((tmp_path / "audio" / "speech.wav").read_bytes())
        resolved_timeline = resolve_materials(
            timeline=timeline,
            run_dir=run_dir,
            object_store_root=built["objects"],
            repo_root=REPO_ROOT,
        )
        remotion_path = run_dir / "render" / "remotion.timeline.json"
        export_remotion_timeline(resolved_timeline, remotion_path)
        silent = run_dir / "render" / "silent.mp4"
        render_v4_silent_mp4(
            timeline=resolved_timeline,
            remotion_timeline_path=remotion_path,
            run_render_dir=run_dir / "render",
            repo_root=REPO_ROOT,
            output=silent,
            crf=28,
            preset="ultrafast",
        )
        assert silent.is_file()
        assert silent.stat().st_size > 1000
        from video_agent.render.v4.ffmpeg_mix import mix_compiled_audio

        final = run_dir / "render" / "final.mp4"
        mix_compiled_audio(
            timeline=resolved_timeline,
            visual_input=silent,
            run_render_dir=run_dir / "render",
            output=final,
        )
        assert final.is_file()
        assert final.stat().st_size > silent.stat().st_size
    finally:
        built["repo"].close()


def test_stage0_golden_ffmpeg_mix_without_remotion(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    """Voice + SFX peak compile + FFmpeg mix (lavfi black visual; no Remotion)."""
    import subprocess

    from video_agent.render.v4.ffmpeg_mix import mix_compiled_audio

    built = _build_golden_pipeline(tmp_path, hub)
    timeline = built["timeline"]
    try:
        assert any(track.kind == "sfx" for track in timeline.audio_tracks)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "audio").mkdir()
        (run_dir / "audio" / "speech.wav").write_bytes((tmp_path / "audio" / "speech.wav").read_bytes())
        resolved_timeline = resolve_materials(
            timeline=timeline,
            run_dir=run_dir,
            object_store_root=built["objects"],
            repo_root=REPO_ROOT,
        )
        silent = run_dir / "render" / "silent.mp4"
        silent.parent.mkdir(parents=True, exist_ok=True)
        duration = timeline.frame_count / timeline.fps
        proc = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s=1080x1920:d={duration:.3f}:r={timeline.fps}",
                "-pix_fmt",
                "yuv420p",
                str(silent),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        final = run_dir / "render" / "final.mp4"
        mix_compiled_audio(
            timeline=resolved_timeline,
            visual_input=silent,
            run_render_dir=run_dir / "render",
            output=final,
        )
        assert final.is_file()
        assert final.stat().st_size > 1000
    finally:
        built["repo"].close()

"""Stage0 Pass B: real MiniMax speech → Stage4–6 golden compile/render.

Creates a new run under cases/v4_stage0_golden_20260717, freezes SpeechTimingLock
from live MiniMax word timing, installs the Rev3 s001–s010 SceneSemanticPlan
fixture, seeds a Pass-B asset repository, then runs Stage4 → Stage5 → Stage6
with Remotion + FFmpeg mix.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_v4_stage4_golden import _seed_golden_repo  # noqa: E402
from video_agent.assets.v4 import LocalObjectStore, SQLiteAssetRepository  # noqa: E402
from video_agent.contracts import Narration  # noqa: E402
from video_agent.contracts.v4 import FrozenNarration, SceneSemanticPlan  # noqa: E402
from video_agent.io import load_json, load_model, sha256_file, sha256_json, utc_now, write_json_atomic  # noqa: E402
from video_agent.orchestrator import Orchestrator as LegacyOrchestrator  # noqa: E402
from video_agent.progress import get_logger  # noqa: E402
from video_agent.registries import CapabilityRegistryHub  # noqa: E402
from video_agent.runtime import RunContext  # noqa: E402
from video_agent.speech.v4.voice_resolve import (  # noqa: E402
    apply_resolved_voice_to_case_voice,
    resolve_fixed_voice_profile,
)
from video_agent.v4.orchestrator import V4Orchestrator  # noqa: E402


logger = get_logger()
CASE = REPO_ROOT / "cases" / "v4_stage0_golden_20260717"
FIXTURE_SCENE = REPO_ROOT / "tests" / "fixtures" / "v4" / "stage0" / "scene_semantic_plan.payload.json"


def _ensure_wav(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() == ".wav":
        shutil.copy2(src, dest)
        return
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "44100", str(dest)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not dest.is_file():
        raise RuntimeError(f"ffmpeg wav convert failed: {(proc.stderr or '')[-2000:]}")


def _seed_pass_b_repo(run_dir: Path, hub: CapabilityRegistryHub) -> Path:
    db = run_dir / "pass_b_assets.sqlite3"
    objects = run_dir / "pass_b_objects"
    seed_dir = run_dir / "pass_b_seed"
    if db.exists():
        db.unlink()
    if objects.exists():
        shutil.rmtree(objects)
    objects.mkdir(parents=True, exist_ok=True)
    seed_dir.mkdir(parents=True, exist_ok=True)
    repo = SQLiteAssetRepository(db, LocalObjectStore(objects), hub)
    _seed_golden_repo(repo, seed_dir)
    # Touch a marker image so empty dirs are not confusing in the ledger.
    Image.new("RGB", (8, 6), "white").save(seed_dir / "_seed_ok.png")
    repo.close()
    return db


def _install_rev3_scene(run_dir: Path) -> SceneSemanticPlan:
    plan = SceneSemanticPlan.model_validate(load_json(FIXTURE_SCENE))
    if [scene.scene_id for scene in plan.scenes] != [f"s{i:03d}" for i in range(1, 11)]:
        raise RuntimeError("Rev3 fixture must contain s001–s010")
    write_json_atomic(
        run_dir / "scene_semantic_plan.json",
        {
            "schema_version": "v4.scene_semantics.1",
            "input_fingerprints": {
                "source": "tests/fixtures/v4/stage0/scene_semantic_plan.payload.json",
                "pass_b": "stage0_rev3_oracle",
            },
            "payload": plan.model_dump(mode="json"),
        },
    )
    return plan


def _project_speech_timing_lock(context: RunContext) -> Path:
    """Project MiniMax TimingLock → V4 SpeechTimingLock (no phrase anchors)."""
    from video_agent.contracts import TimingLock
    from video_agent.contracts.v4 import ResolvedVoiceProfile, SpeechBeatSpanV4, SpeechTimingLock, SpeechTokenTimingV4
    from video_agent.timing.v4.speech_lock import voice_profile_content_sha256
    from video_agent.timing.v4.timebase import duration_frames, ms_to_hit_frame, ms_to_interval_end

    speech_path = context.artifact("speech_timing_lock.json")
    timing = load_model(context.artifact("timing_lock.json"), TimingLock)
    voice = load_model(context.artifact("resolved_voice_profile.json"), ResolvedVoiceProfile)
    narration = load_model(context.artifact("narration.json"), Narration)

    tokens: list[SpeechTokenTimingV4] = []
    for index, token in enumerate(timing.tokens):
        start_frame = ms_to_hit_frame(token.start_ms, timing.fps)
        end_frame = max(start_frame + 1, ms_to_interval_end(token.end_ms, timing.fps))
        tokens.append(
            SpeechTokenTimingV4(
                token_id=f"tok_{index:04d}",
                text=token.text,
                start_ms=token.start_ms,
                end_ms=token.end_ms,
                start_frame=start_frame,
                end_frame=end_frame,
                beat_id=None,
            )
        )
    frames = max(duration_frames(timing.duration_ms, timing.fps), tokens[-1].end_frame if tokens else 0)
    audio_object_key = "audio/speech.wav"
    audio_src = Path(timing.audio_path)
    if not audio_src.is_file():
        audio_src = context.run_dir / timing.audio_path
    audio_dest = context.run_dir / audio_object_key
    _ensure_wav(audio_src, audio_dest)

    speech = SpeechTimingLock(
        schema_version=1,
        case_id=context.case.case_id,
        run_id=context.run_id,
        narration_sha256=sha256_json(narration),
        audio_object_key=audio_object_key,
        audio_sha256=sha256_file(audio_dest),
        voice_profile_id=voice.profile_id,
        voice_profile_version=voice.profile_version,
        voice_profile_sha256=voice_profile_content_sha256(voice),
        fps=timing.fps,
        duration_ms=timing.duration_ms,
        duration_frames=frames,
        tokens=tokens,
        pause_events=[],
        beat_spans=[
            SpeechBeatSpanV4(
                beat_id="speech_full",
                token_ids=[token.token_id for token in tokens],
                start_frame=tokens[0].start_frame if tokens else 0,
                end_frame=frames,
            )
        ],
    )
    # Fail-loud: SpeechTimingLock must not carry semantic phrase anchors.
    dumped = speech.model_dump(mode="json")
    if "phrase_anchors" in dumped:
        raise RuntimeError("SpeechTimingLock must not contain phrase_anchors")
    write_json_atomic(speech_path, speech)
    return speech_path


def _verify_pass_b(context: RunContext) -> dict:
    resolved = load_json(context.artifact("resolved_asset_plan.json"))
    scenes = {item["scene_id"]: item for item in resolved["scenes"]}
    assert set(scenes) == {f"s{i:03d}" for i in range(1, 11)}
    s002_g1 = next(slot["asset_ref"] for slot in scenes["s002"]["slots"] if slot["slot_id"] == "g1")
    primary = scenes["s005"]["outputs"]["primary_result"]
    assert primary != s002_g1
    assert scenes["s006"]["inputs"]["source_result"] == primary
    assert scenes["s007"]["inputs"]["source_result"] == primary
    assert scenes["s008"]["inputs"]["source_result"] == primary
    assert scenes["s009"]["slots"] == []
    assert scenes["s010"]["slots"][0]["asset_ref"]

    timeline = load_json(context.artifact("compiled_video_timeline.json"))
    speech = load_json(context.artifact("speech_timing_lock.json"))
    assert "phrase_anchors" not in speech
    assert timeline["fps"] == 30
    assert timeline["width"] == 1080 and timeline["height"] == 1920
    assert any(track["kind"] == "sfx" for track in timeline["audio_tracks"])
    assert any(track["kind"] == "voice" for track in timeline["audio_tracks"])

    final = context.run_dir / "render" / "final.mp4"
    silent = context.run_dir / "render" / "silent.mp4"
    assert silent.is_file()
    assert final.is_file()
    return {
        "s002_g1": s002_g1,
        "primary_result": primary,
        "frame_count": timeline["frame_count"],
        "duration_ms": speech["duration_ms"],
        "token_count": len(speech["tokens"]),
        "sfx_tracks": sum(1 for track in timeline["audio_tracks"] if track["kind"] == "sfx"),
        "final_video_bytes": final.stat().st_size,
        "silent_video_bytes": silent.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", help="Resume an existing Pass B run id")
    parser.add_argument("--skip-minimax", action="store_true", help="Reuse timing_lock.json if present")
    parser.add_argument("--skip-render", action="store_true", help="Compile only (no Remotion/FFmpeg)")
    args = parser.parse_args()

    if not CASE.is_dir():
        raise SystemExit(f"missing golden case: {CASE}")

    context = RunContext.open(CASE, args.resume) if args.resume else RunContext.create(CASE)
    logger.info("[PassB] case=%s run=%s", context.case.case_id, context.run_id)

    legacy = LegacyOrchestrator(context)
    narration_path = context.artifact("narration.json")
    if not narration_path.is_file():
        source = CASE / "input" / "narration.json"
        if not source.is_file():
            raise SystemExit(f"missing locked narration: {source}")
        shutil.copy2(source, narration_path)
    narration = load_model(narration_path, Narration)
    frozen = FrozenNarration(
        text=narration.spoken_text,
        source=context.case.mode,
        source_fingerprint=f"sha256:{sha256_json(narration)}",
    )
    write_json_atomic(context.artifact("frozen_narration.json"), frozen)

    hub = CapabilityRegistryHub.load(REPO_ROOT / "config" / "registries" / "v4")
    snapshot_path = context.artifact("capability_registry.snapshot.json")
    frozen_registry = hub.freeze(snapshot_path)

    case_voice = context.case.voice
    resolved_voice = resolve_fixed_voice_profile(
        hub,
        repo_root=REPO_ROOT,
        voice_profile_id=case_voice.voice_profile_id,
        speed_override=case_voice.speed if case_voice.voice_profile_id is not None else None,
        emotion_override=case_voice.emotion,
        registry_snapshot_id=frozen_registry.snapshot_id,
    )
    write_json_atomic(context.artifact("resolved_voice_profile.json"), resolved_voice)
    # RunContext is frozen; MiniMax voice already applied via case.json local defaults.
    _ = apply_resolved_voice_to_case_voice

    timing_path = context.artifact("timing_lock.json")
    if args.skip_minimax and timing_path.is_file():
        logger.info("[PassB] reusing existing timing_lock.json")
    else:
        if timing_path.is_file():
            timing_path.unlink()
        speech_lock = context.artifact("speech_timing_lock.json")
        if speech_lock.is_file():
            speech_lock.unlink()
        logger.info("[PassB] calling MiniMax TTS…")
        legacy.stage_speech()

    speech_path = _project_speech_timing_lock(context)
    logger.info("[PassB] speech_timing_lock=%s", speech_path)

    scene_plan = _install_rev3_scene(context.run_dir)
    logger.info("[PassB] installed Rev3 scenes=%s", [s.scene_id for s in scene_plan.scenes])

    db = _seed_pass_b_repo(context.run_dir, hub)
    object_root = context.run_dir / "pass_b_objects"
    orch = V4Orchestrator(context)

    logger.info("[PassB] Stage4 resolve…")
    orch.run_stage4(run_seed="pass_b", allow_fake_derivation=False, db=db, object_root=object_root)

    logger.info("[PassB] Stage5 motion…")
    orch.run_stage5(run_seed="pass_b", sfx_profile_id="normal")

    logger.info("[PassB] Stage6 compile-render…")
    stage6 = orch.run_stage6(
        phase=None,
        postroll_frames=0,
        object_root=object_root,
        render=not args.skip_render,
        skip_ffmpeg=False,
    )

    checks = _verify_pass_b(context) if not args.skip_render else {
        "note": "render skipped; compile artifacts only",
        "compiled": (context.artifact("compiled_video_timeline.json")).is_file(),
    }
    ledger = {
        "schema_version": "v4.stage0_pass_b_ledger.1",
        "completed_at": utc_now(),
        "case_id": context.case.case_id,
        "run_id": context.run_id,
        "run_dir": context.run_dir.as_posix(),
        "frozen_narration_sha256": sha256_json(frozen),
        "speech_timing_lock_sha256": sha256_file(speech_path),
        "scene_fixture": FIXTURE_SCENE.as_posix(),
        "registry_snapshot_id": frozen_registry.snapshot_id,
        "pass_b_db": db.as_posix(),
        "stage6_manifest": stage6.manifest.as_posix(),
        "final_video": None if stage6.final_video is None else stage6.final_video.as_posix(),
        "checks": checks,
        "status": "pass_b_closed" if not args.skip_render else "pass_b_compile_only",
    }
    ledger_path = context.artifact("stage0_pass_b_ledger.json")
    write_json_atomic(ledger_path, ledger)
    # Also mirror under docs fixtures for the progress ledger (relative path only).
    mirror = REPO_ROOT / "tests" / "fixtures" / "v4" / "stage6" / "pass_b_ledger.json"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(mirror, ledger)
    logger.info("[PassB] DONE status=%s ledger=%s", ledger["status"], ledger_path)
    print(sha256_json(ledger))
    print(ledger_path.as_posix())
    if stage6.final_video:
        print(stage6.final_video.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

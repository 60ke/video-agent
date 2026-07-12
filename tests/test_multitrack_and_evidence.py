from __future__ import annotations

from pathlib import Path
import math
import struct
import wave

import pytest
from PIL import Image

from video_agent.compiler import compile_render_plan
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    AudioConfig,
    BeatSpan,
    Claim,
    CueBinding,
    DurationPolicy,
    EvidenceClass,
    Narration,
    NarrationBeat,
    Provenance,
    ShotPlan,
    TimeRef,
    TimingLock,
    TokenTiming,
    TransitionIn,
    VisualPlan,
)
from video_agent.io import sha256_file
from video_agent.render.ffmpeg import ffprobe, render_video
from video_agent.qa import run_final_qa
from video_agent.scene import FrameRenderer


def _asset(path: Path, asset_id: str, color: tuple[int, int, int]) -> Asset:
    Image.new("RGB", (720, 1280), color).save(path)
    return Asset(
        asset_id=asset_id,
        path=path.name,
        sha256=sha256_file(path),
        filename=path.name,
        width=720,
        height=1280,
        semantic_path=["文生图", "文化墙"],
        role="result_image",
        evidence_class=EvidenceClass.SOURCE,
        claims=["真实结果"],
        quality=AssetQuality(status="machine_checked"),
        provenance=Provenance(origin="curated_result_library"),
    )


def _timing() -> TimingLock:
    return TimingLock(
        case_id="demo",
        audio_path="voice.wav",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=1000,
        duration_frames=30,
        tokens=[TokenTiming(token_id="tok", text="展示", start_ms=0, end_ms=1000, start_frame=0, end_frame=30, beat_id="beat_1")],
        beat_spans=[BeatSpan(beat_id="beat_1", token_ids=["tok"], start_frame=0, end_frame=30)],
    )


def _compile(tmp_path: Path, visual: VisualPlan, narration: Narration, catalog: AssetCatalog):
    return compile_render_plan(
        "demo",
        "run",
        narration,
        _timing(),
        visual,
        catalog,
        tmp_path,
        "douyin_portrait_v1",
        1080,
        1920,
        tmp_path,
        AudioConfig(sfx_profile=None),
        DurationPolicy(preferred_min_sec=1, preferred_max_sec=1, hard_max_sec=1),
    )


def test_compiler_and_renderer_support_multishot_beat_transition_and_overlay(tmp_path: Path) -> None:
    red = _asset(tmp_path / "red.png", "asset_red", (240, 20, 20))
    green = _asset(tmp_path / "green.png", "asset_green", (20, 220, 20))
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[red, green])
    narration = Narration(
        case_id="demo",
        claims=[Claim(claim_id="claim_result", text="展示真实结果", supporting_asset_ids=[red.asset_id])],
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="展示真实结果", claim_ids=["claim_result"])],
    )
    visual = VisualPlan(
        case_id="demo",
        shots=[
            ShotPlan(
                shot_id="base_red",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="beat_start:beat_1"),
                end=TimeRef(anchor_id="beat_start:beat_1", offset_frames=15),
                template="result_showcase",
                asset_bindings={"primary": red.asset_id},
                cue_bindings=[CueBinding(action="visual.enter", anchor_id="beat_start:beat_1")],
                claim_ids=["claim_result"],
            ),
            ShotPlan(
                shot_id="base_green",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="beat_start:beat_1", offset_frames=15),
                end=TimeRef(anchor_id="beat_end:beat_1"),
                template="result_showcase",
                asset_bindings={"primary": green.asset_id},
                transition_in=TransitionIn(kind="crossfade", duration_frames=10),
            ),
            ShotPlan(
                shot_id="overlay_green",
                track="overlay",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="beat_start:beat_1", offset_frames=5),
                end=TimeRef(anchor_id="beat_start:beat_1", offset_frames=12),
                template="result_showcase",
                asset_bindings={"primary": green.asset_id},
                motion="scale_in",
            ),
        ],
    )
    plan = _compile(tmp_path, visual, narration, catalog)
    assert [shot.shot_id for shot in plan.shots if shot.track == "base"] == ["base_red", "base_green"]
    assert any(shot.track == "overlay" for shot in plan.shots)
    renderer = FrameRenderer(plan)
    try:
        blended = renderer.render(20).getpixel((540, 900))
    finally:
        renderer.close()
    assert blended[0] > 35 and blended[1] > 35


def test_compiler_rejects_claim_without_visible_supporting_asset(tmp_path: Path) -> None:
    red = _asset(tmp_path / "red.png", "asset_red", (240, 20, 20))
    green = _asset(tmp_path / "green.png", "asset_green", (20, 220, 20))
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[red, green])
    narration = Narration(
        case_id="demo",
        claims=[Claim(claim_id="claim_result", text="展示真实结果", supporting_asset_ids=[red.asset_id])],
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="展示真实结果", claim_ids=["claim_result"])],
    )
    visual = VisualPlan(
        case_id="demo",
        shots=[
            ShotPlan(
                shot_id="wrong_asset",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="beat_start:beat_1"),
                end=TimeRef(anchor_id="beat_end:beat_1"),
                template="result_showcase",
                asset_bindings={"primary": green.asset_id},
                claim_ids=["claim_result"],
            )
        ],
    )
    with pytest.raises(ValueError, match="not supported by an asset visible"):
        _compile(tmp_path, visual, narration, catalog)


def test_multitrack_plan_renders_real_mp4(tmp_path: Path) -> None:
    red = _asset(tmp_path / "red.png", "asset_red", (240, 20, 20))
    green = _asset(tmp_path / "green.png", "asset_green", (20, 220, 20))
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[red, green])
    narration = Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="展示")])
    visual = VisualPlan(
        case_id="demo",
        shots=[
            ShotPlan(
                shot_id="red",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="beat_start:beat_1"),
                end=TimeRef(anchor_id="beat_start:beat_1", offset_frames=15),
                template="result_showcase",
                asset_bindings={"primary": red.asset_id},
                cue_bindings=[CueBinding(action="visual.enter", anchor_id="beat_start:beat_1")],
            ),
            ShotPlan(
                shot_id="green",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="beat_start:beat_1", offset_frames=15),
                end=TimeRef(anchor_id="beat_end:beat_1"),
                template="result_showcase",
                asset_bindings={"primary": green.asset_id},
                transition_in=TransitionIn(kind="slide_left", duration_frames=8),
            ),
        ],
    )
    plan = _compile(tmp_path, visual, narration, catalog)
    voice = tmp_path / "voice.wav"
    with wave.open(str(voice), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"".join(struct.pack("<h", round(2400 * math.sin(2 * math.pi * 440 * sample / 48_000))) for sample in range(48_000)))
    plan.audio_tracks[0].path = voice.as_posix()
    output = render_video(plan, tmp_path / "multitrack.mp4", preset="ultrafast", crf=30)
    streams = ffprobe(output)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert any(stream["codec_type"] == "audio" for stream in streams)
    report = run_final_qa(plan, output, tmp_path)
    assert report.status == "passed", [(check.check_id, check.message, check.details) for check in report.checks if check.status == "failed"]
    assert (tmp_path / "final" / "cue_contact_sheet.jpg").is_file()

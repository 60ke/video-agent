from __future__ import annotations

import wave
from pathlib import Path

from PIL import Image

from video_agent.audio import get_sfx_profile
from video_agent.compiler.render_plan import compile_render_plan
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    AudioConfig,
    BeatSpan,
    DurationPolicy,
    EvidenceClass,
    Narration,
    NarrationBeat,
    PhraseAnchor,
    Provenance,
    SemanticSfx,
    ShotPlan,
    TimeRef,
    TimingLock,
    TokenTiming,
    VisualPlan,
)
from video_agent.io import sha256_file
from video_agent.planning import build_auto_visual_plan


def _asset(path: Path) -> Asset:
    Image.new("RGB", (720, 1280), (20, 24, 30)).save(path)
    return Asset(
        asset_id="asset_site_params",
        path=path.name,
        sha256=sha256_file(path),
        filename=path.name,
        width=720,
        height=1280,
        semantic_path=["文生图", "文化墙"],
        role="feature_form_params",
        evidence_class=EvidenceClass.SOURCE,
        claims=["real_website_screenshot"],
        quality=AssetQuality(status="machine_checked"),
        provenance=Provenance(origin="site_screenshot_library"),
    )


def _timing() -> TimingLock:
    return TimingLock(
        case_id="demo",
        audio_path="voice.wav",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=1000,
        duration_frames=30,
        tokens=[TokenTiming(token_id="tok_1", text="填写必填项", start_ms=0, end_ms=1000, start_frame=0, end_frame=30, beat_id="beat_1")],
        phrase_anchors=[PhraseAnchor(anchor_id="anchor_1", text="填写必填项", token_ids=["tok_1"], hit_frame=6, beat_id="beat_1")],
        beat_spans=[BeatSpan(beat_id="beat_1", token_ids=["tok_1"], start_frame=0, end_frame=30)],
    )


def test_auto_visual_uses_flat_motion_and_semantic_sfx_for_params(tmp_path: Path) -> None:
    asset = _asset(tmp_path / "params.png")
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[asset])
    narration = Narration(
        case_id="demo",
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="填写必填项", asset_slots=["参数"], hit_phrases=["填写必填项"])],
    )

    visual = build_auto_visual_plan("demo", narration, _timing(), catalog)

    assert visual.shots[0].template == "ui_params_focus"
    assert visual.shots[0].motion == "scale_in"
    assert visual.shots[0].cue_bindings[0].sfx == "field_focus"


def test_compile_resolves_semantic_sfx_and_keeps_anchor_frame(tmp_path: Path) -> None:
    asset = _asset(tmp_path / "params.png")
    sfx_path = tmp_path / "focus.wav"
    with wave.open(str(sfx_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\x00\x00" * 4800)
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[asset])
    visual = VisualPlan(
        case_id="demo",
        shots=[
            ShotPlan(
                shot_id="shot_1",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="beat_start:beat_1"),
                end=TimeRef(anchor_id="beat_end:beat_1"),
                template="ui_params_focus",
                asset_bindings={"primary": asset.asset_id},
                motion="scale_in",
                cue_bindings=[{"action": "focus.hit", "anchor_id": "anchor_1", "sfx": "field_focus"}],
            )
        ],
    )
    audio = AudioConfig(
        sfx_profile=None,
        sfx_overrides={
            "field_focus": SemanticSfx(path=sfx_path.name, gain_db=-18, max_duration_ms=100, fade_out_ms=30, sync_point="peak", sync_offset_ms=40)
        },
    )

    plan = compile_render_plan(
        "demo",
        "run",
        Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="填写必填项")]),
        _timing(),
        visual,
        catalog,
        tmp_path,
        "douyin_portrait_v1",
        1080,
        1920,
        tmp_path,
        audio,
        DurationPolicy(preferred_min_sec=1, preferred_max_sec=1, hard_max_sec=1),
    )

    sfx = next(track for track in plan.audio_tracks if track.kind == "sfx")
    assert sfx.semantic_id == "field_focus"
    assert sfx.anchor_id == "anchor_1"
    assert sfx.start_frame == 5
    assert sfx.sync_frame == 6
    assert sfx.sync_point == "peak"
    assert sfx.max_duration_ms == 100


def test_builtin_sfx_profile_points_to_valid_wav_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    profile = get_sfx_profile("short_video_ui_v1")
    assert {"ui_click", "field_focus", "upload", "result_reveal", "success"} <= set(profile)
    for source in profile.values():
        path = repo_root / source.path
        with wave.open(str(path), "rb") as audio:
            assert audio.getframerate() == 48_000
            assert audio.getnframes() > 0

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
    ParameterFrameSequence,
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


def _sequence_assets(root: Path) -> list[Asset]:
    states = ("base", "stage", "final")
    assets: list[Asset] = []
    ids = {state: f"asset_params_{state}" for state in states}
    for state in states:
        path = root / f"params_{state}.png"
        Image.new("RGB", (720, 1280), (20, 24, 30)).save(path)
        assets.append(
            Asset(
                asset_id=ids[state], path=path.name, sha256=sha256_file(path), filename=path.name, width=720, height=1280,
                semantic_path=["文生图", "文化墙"], role="feature_form_params", evidence_class=EvidenceClass.SEMANTIC,
                quality=AssetQuality(status="human_approved"), provenance=Provenance(origin="gpt_image_site_keyframe"),
                metadata={
                    "sequence_id": "params_文化墙", "sequence_role": state, "sequence_asset_ids": ids,
                    "required_field_labels": ["行业"], "callout_text": "行业",
                },
            )
        )
    return assets


def _parameter_shot(*, start: TimeRef, end: TimeRef, cue_bindings: list[dict[str, str]] | None = None) -> ShotPlan:
    ids = {state: f"asset_params_{state}" for state in ("base", "stage", "final")}
    return ShotPlan(
        shot_id="shot", beat_ids=["beat_1"], start=start, end=end, template="ui_params_focus",
        asset_bindings=ids,
        parameter_sequence=ParameterFrameSequence(
            sequence_id="params_文化墙", base_asset_id=ids["base"], stage_asset_id=ids["stage"], final_asset_id=ids["final"],
            required_field_labels=["行业"], callout_text="行业",
        ),
        cue_bindings=cue_bindings or [],
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
    assets = _sequence_assets(tmp_path)
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=assets)
    narration = Narration(
        case_id="demo",
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="填写必填项", asset_slots=["参数"], hit_phrases=["填写必填项"])],
    )

    timing = _timing().model_copy(
        update={
            "duration_ms": 3000,
            "duration_frames": 90,
            "tokens": [_timing().tokens[0].model_copy(update={"end_ms": 3000, "end_frame": 90})],
            "beat_spans": [_timing().beat_spans[0].model_copy(update={"end_frame": 90})],
        }
    )
    visual = build_auto_visual_plan("demo", narration, timing, catalog)

    assert visual.shots[0].template == "ui_params_focus"
    assert visual.shots[0].motion == "scale_in"
    assert visual.shots[0].cue_bindings[0].sfx == "typing"


def test_auto_visual_covers_timeline_tail_and_marks_pause(tmp_path: Path) -> None:
    assets = _sequence_assets(tmp_path)
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=assets)
    narration = Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="填写必填项", asset_slots=["参数"])])
    timing = _timing().model_copy(
        update={
            "duration_ms": 4000,
            "duration_frames": 120,
            "tokens": [_timing().tokens[0].model_copy(update={"end_ms": 3000, "end_frame": 90})],
            "beat_spans": [_timing().beat_spans[0].model_copy(update={"end_frame": 90})],
        }
    )
    visual = build_auto_visual_plan("demo", narration, timing, catalog)
    assert visual.shots[0].start.anchor_id == "timeline_start"
    assert visual.shots[-1].end.anchor_id == "timeline_end"
    assert visual.shots[-1].long_hold_reason == "pause"


def test_auto_visual_bridges_lead_in_and_inter_beat_gaps(tmp_path: Path) -> None:
    home = tmp_path / "home.png"
    result = tmp_path / "result.png"
    Image.new("RGB", (720, 1280), (20, 24, 30)).save(home)
    Image.new("RGB", (720, 1280), (40, 50, 60)).save(result)
    catalog = AssetCatalog(
        catalog_id="demo",
        generated_at="now",
        source_root="assets",
        assets=[
            Asset(
                asset_id="asset_site_home",
                path=home.name,
                sha256=sha256_file(home),
                filename=home.name,
                width=720,
                height=1280,
                semantic_path=["文生图"],
                role="site_home",
                evidence_class=EvidenceClass.SOURCE,
                quality=AssetQuality(status="machine_checked"),
                provenance=Provenance(origin="site_screenshot_library"),
            ),
            Asset(
                asset_id="asset_result_vi",
                path=result.name,
                sha256=sha256_file(result),
                filename=result.name,
                width=720,
                height=1280,
                semantic_path=["文生图", "VI"],
                role="result_image",
                evidence_class=EvidenceClass.SOURCE,
                quality=AssetQuality(status="machine_checked"),
                provenance=Provenance(origin="result_library"),
            ),
        ],
    )
    narration = Narration(
        case_id="demo",
        beats=[
            NarrationBeat(beat_id="beat_1", spoken_text="什么网站可以帮你", asset_slots=["网站首页"]),
            NarrationBeat(beat_id="beat_2", spoken_text="一键生成设计方案", asset_slots=["真实结果", "VI"]),
        ],
    )
    timing = TimingLock(
        case_id="demo",
        audio_path="voice.wav",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=5000,
        duration_frames=150,
        tokens=[
            TokenTiming(token_id="tok_1", text="什么网站可以帮你", start_ms=40, end_ms=1600, start_frame=1, end_frame=48, beat_id="beat_1"),
            TokenTiming(token_id="tok_2", text="一键生成设计方案", start_ms=2200, end_ms=4000, start_frame=66, end_frame=120, beat_id="beat_2"),
        ],
        phrase_anchors=[],
        beat_spans=[
            BeatSpan(beat_id="beat_1", token_ids=["tok_1"], start_frame=1, end_frame=48),
            BeatSpan(beat_id="beat_2", token_ids=["tok_2"], start_frame=66, end_frame=120),
        ],
    )

    visual = build_auto_visual_plan("demo", narration, timing, catalog)

    assert visual.shots[0].start.anchor_id == "timeline_start"
    assert visual.shots[0].end.anchor_id == "beat_start:beat_2"
    assert visual.shots[0].long_hold_reason == "pause"
    assert visual.shots[-1].start.anchor_id == "beat_start:beat_2"
    assert visual.shots[-1].end.anchor_id == "timeline_end"
    assert visual.shots[-1].long_hold_reason == "pause"


def test_compile_resolves_semantic_sfx_and_keeps_anchor_frame(tmp_path: Path) -> None:
    assets = _sequence_assets(tmp_path)
    sfx_path = tmp_path / "focus.wav"
    with wave.open(str(sfx_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\x00\x00" * 4800)
    catalog = AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=assets)
    visual = VisualPlan(
        case_id="demo",
        shots=[
            _parameter_shot(start=TimeRef(anchor_id="beat_start:beat_1"), end=TimeRef(anchor_id="beat_end:beat_1"), cue_bindings=[{"action": "focus.hit", "anchor_id": "anchor_1", "sfx": "mouse_click"}])
        ],
    )
    audio = AudioConfig(
        sfx_profile=None,
        sfx_overrides={
            "mouse_click": SemanticSfx(path=sfx_path.name, gain_db=-18, max_duration_ms=100, fade_out_ms=30, sync_point="peak", sync_offset_ms=40)
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
    assert plan.shots[0].start_frame == 0
    assert sfx.semantic_id == "mouse_click"
    assert sfx.anchor_id == "anchor_1"
    assert sfx.start_frame == 5
    assert sfx.sync_frame == 6
    assert sfx.sync_point == "peak"
    assert sfx.max_duration_ms == 100


def test_first_frame_peak_sfx_uses_extra_trim(tmp_path: Path) -> None:
    assets = _sequence_assets(tmp_path)
    sfx_path = tmp_path / "click.wav"
    with wave.open(str(sfx_path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(48_000)
        output.writeframes(b"\x00\x00\x00\x00" * 4800)
    timing = _timing().model_copy(
        update={"phrase_anchors": [PhraseAnchor(anchor_id="anchor_1", text="填写必填项", token_ids=["tok_1"], hit_frame=0, beat_id="beat_1")]}
    )
    visual = VisualPlan(
        case_id="demo",
        shots=[_parameter_shot(start=TimeRef(anchor_id="timeline_start"), end=TimeRef(anchor_id="timeline_end"), cue_bindings=[{"action": "click", "anchor_id": "anchor_1", "sfx": "mouse_click"}])],
    )
    plan = compile_render_plan(
        "demo", "run", Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="填写必填项")]), timing, visual,
        AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=assets), tmp_path, "douyin_portrait_v1", 1080, 1920, tmp_path,
        AudioConfig(sfx_profile=None, sfx_overrides={"mouse_click": SemanticSfx(path=sfx_path.name, trim_start_ms=130, max_duration_ms=200, fade_out_ms=30, sync_point="peak", sync_offset_ms=134)}),
        DurationPolicy(preferred_min_sec=1, preferred_max_sec=1, hard_max_sec=1),
    )
    sfx = next(track for track in plan.audio_tracks if track.kind == "sfx")
    assert sfx.start_frame == 0
    assert sfx.trim_start_ms == 264
    assert sfx.effective_sync_offset_ms == 0


def test_registered_sfx_profile_points_to_normalized_wav_files() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    profile = get_sfx_profile("douyin_common_v1")
    assert set(profile) == {"typing", "transition_whoosh", "camera_shutter", "task_complete", "mouse_click", "swish"}
    for source in profile.values():
        path = repo_root / source.path
        with wave.open(str(path), "rb") as audio:
            assert audio.getframerate() == 48_000
            assert audio.getnchannels() == 2
            assert audio.getsampwidth() == 2
            assert audio.getnframes() > 0

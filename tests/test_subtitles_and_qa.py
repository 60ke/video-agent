from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_agent.compiler.subtitles import compile_subtitles, fullwidth_units
from video_agent.contracts import (
    AudioTrack,
    BeatSpan,
    CompiledParameterFrameSequence,
    CueBinding,
    GalleryItem,
    RenderAsset,
    RenderPlan,
    RenderShot,
    SubtitleCue,
    TimingLock,
    TokenTiming,
    TransitionIn,
)
from video_agent.qa import validate_render_plan


def _timing() -> TimingLock:
    text = "上传LOGO，再填品牌名称。"
    tokens = [
        TokenTiming(
            token_id=f"tok_{index:04d}",
            text=char,
            start_ms=index * 100,
            end_ms=(index + 1) * 100,
            start_frame=index * 3,
            end_frame=(index + 1) * 3,
            beat_id="beat_001",
        )
        for index, char in enumerate(text, 1)
    ]
    return TimingLock(
        case_id="demo",
        audio_path="voice.mp3",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=len(tokens) * 100,
        duration_frames=len(tokens) * 3 + 3,
        tokens=tokens,
        beat_spans=[BeatSpan(beat_id="beat_001", token_ids=[token.token_id for token in tokens], start_frame=3, end_frame=len(tokens) * 3 + 3)],
    )


def test_subtitle_compiler_outputs_single_lines_that_fit_the_safe_slot() -> None:
    cues = compile_subtitles(_timing())
    assert len(cues) >= 2
    assert all("\n" not in cue.text and fullwidth_units(cue.text) * 48 <= 856 for cue in cues)
    assert all(fullwidth_units(cue.text) >= 4 for cue in cues)


def test_subtitle_compiler_never_crosses_beat_boundary() -> None:
    timing = _timing()
    split = len(timing.tokens) // 2
    for token in timing.tokens[split:]:
        token.beat_id = "beat_002"
    timing.beat_spans = [
        BeatSpan(beat_id="beat_001", token_ids=[token.token_id for token in timing.tokens[:split]], start_frame=timing.tokens[0].start_frame, end_frame=timing.tokens[split - 1].end_frame),
        BeatSpan(beat_id="beat_002", token_ids=[token.token_id for token in timing.tokens[split:]], start_frame=timing.tokens[split].start_frame, end_frame=timing.tokens[-1].end_frame),
    ]
    cues = compile_subtitles(timing)
    assert all(cue.beat_id in {"beat_001", "beat_002"} for cue in cues)
    assert all(not ({token.beat_id for token in timing.tokens if token.start_frame >= cue.start_frame and token.end_frame <= cue.end_frame} - {cue.beat_id}) for cue in cues)


def test_gallery_items_become_word_anchored_yellow_subtitles() -> None:
    text = "从文化墙、门头招牌、LOGO等设计。"
    tokens = [
        TokenTiming(
            token_id=f"tok_{index:04d}", text=char,
            start_ms=(index - 1) * 100, end_ms=index * 100,
            start_frame=(index - 1) * 3, end_frame=index * 3,
            beat_id="beat_001",
        )
        for index, char in enumerate(text, 1)
    ]
    timing = TimingLock(
        case_id="gallery", audio_path="voice.mp3", audio_sha256="a" * 64,
        fps=30, duration_ms=len(tokens) * 100, duration_frames=len(tokens) * 3,
        tokens=tokens,
        beat_spans=[
            BeatSpan(
                beat_id="beat_001", token_ids=[token.token_id for token in tokens],
                start_frame=0, end_frame=len(tokens) * 3,
            )
        ],
    )
    items = [
        GalleryItem(asset_id="culture", phrase="文化墙", anchor_id="tok_0002"),
        GalleryItem(asset_id="sign", phrase="门头招牌", anchor_id="tok_0006"),
        GalleryItem(asset_id="logo", phrase="LOGO", anchor_id="tok_0011"),
    ]

    cues = compile_subtitles(timing, gallery_items=items)
    gallery_cues = [cue for cue in cues if cue.style == "gallery_yellow"]

    assert [cue.text for cue in gallery_cues] == ["文化墙", "门头招牌", "LOGO"]
    assert [cue.start_frame for cue in gallery_cues] == [3, 15, 30]
    assert all(cue.emphasize == cue.text for cue in gallery_cues)
    assert all("从" not in cue.text for cue in gallery_cues)


def test_gallery_phrase_accepts_punctuation_attached_to_final_token() -> None:
    token_texts = ["从", "文", "化", "墙、", "门", "头", "招", "牌。"]
    tokens = [
        TokenTiming(
            token_id=f"tok_{index:04d}",
            text=text,
            start_ms=(index - 1) * 100,
            end_ms=index * 100,
            start_frame=(index - 1) * 3,
            end_frame=index * 3,
            beat_id="beat_001",
        )
        for index, text in enumerate(token_texts, 1)
    ]
    timing = TimingLock(
        case_id="gallery_punctuation",
        audio_path="voice.mp3",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=len(tokens) * 100,
        duration_frames=len(tokens) * 3,
        tokens=tokens,
        beat_spans=[
            BeatSpan(
                beat_id="beat_001",
                token_ids=[token.token_id for token in tokens],
                start_frame=0,
                end_frame=len(tokens) * 3,
            )
        ],
    )

    cues = compile_subtitles(
        timing,
        gallery_items=[
            GalleryItem(asset_id="culture", phrase="文化墙", anchor_id="tok_0002"),
            GalleryItem(asset_id="sign", phrase="门头招牌", anchor_id="tok_0005"),
        ],
    )
    gallery_cues = [cue for cue in cues if cue.style == "gallery_yellow"]

    assert [cue.text for cue in gallery_cues] == ["文化墙", "门头招牌"]
    assert gallery_cues[0].end_frame == tokens[3].end_frame


def test_gallery_summary_reuses_one_subtitle_for_same_phrase_anchor() -> None:
    timing = _timing()
    anchor_id = timing.tokens[2].token_id

    cues = compile_subtitles(
        timing,
        gallery_items=[
            GalleryItem(asset_id="result_1", phrase="LOGO", anchor_id=anchor_id),
            GalleryItem(asset_id="result_2", phrase="LOGO", anchor_id=anchor_id),
            GalleryItem(asset_id="result_3", phrase="LOGO", anchor_id=anchor_id),
        ],
    )

    gallery_cues = [cue for cue in cues if cue.style == "gallery_yellow"]
    assert [cue.text for cue in gallery_cues] == ["LOGO"]


def test_qa_rejects_forbidden_motion_and_long_subtitle() -> None:
    plan = RenderPlan(
        case_id="demo",
        run_id="run",
        frame_count=30,
        assets=[RenderAsset(asset_id="asset", path="demo.png", sha256="a" * 64, width=100, height=100)],
        shots=[
            RenderShot(
                shot_id="shot",
                beat_ids=["beat"],
                template="result_showcase",
                asset_bindings={"primary": "asset"},
                start_frame=0,
                end_frame=30,
                motion="tile_drop",
            )
        ],
        subtitles=[SubtitleCue(cue_id="sub", text="这是一条明显超过十个字的字幕", start_frame=0, end_frame=30, slot="subtitle_top")],
        audio_tracks=[AudioTrack(kind="voice", path="voice.mp3")],
    )
    checks = {check.check_id: check for check in validate_render_plan(plan)}
    assert checks["motion_allowlist"].status == "failed"
    assert checks["subtitle_single_line_fits"].status == "passed"


def test_qa_rejects_3d_turn_on_text_dense_ui() -> None:
    plan = RenderPlan(
        case_id="demo",
        run_id="run",
        frame_count=30,
        assets=[RenderAsset(asset_id="asset", path="demo.png", sha256="a" * 64, width=100, height=100)],
        shots=[
            RenderShot(
                shot_id="shot",
                beat_ids=["beat"],
                template="ui_params_focus",
                asset_bindings={"primary": "asset"},
                start_frame=0,
                end_frame=30,
                motion="page_turn_3d",
            )
        ],
        subtitles=[],
        audio_tracks=[AudioTrack(kind="voice", path="voice.mp3")],
    )
    checks = {check.check_id: check for check in validate_render_plan(plan)}
    assert checks["text_dense_motion_safe"].status == "failed"


def test_qa_rejects_short_reading_time_and_late_parameter_sequence() -> None:
    plan = RenderPlan(
        case_id="demo",
        run_id="run",
        frame_count=30,
        assets=[RenderAsset(asset_id=item, path="demo.png", sha256="a" * 64, width=100, height=100) for item in ("base", "stage", "final")],
        shots=[
            RenderShot(
                shot_id="entry",
                beat_ids=["beat"],
                template="ui_params_focus",
                asset_bindings={"base": "base", "stage": "stage", "final": "final"},
                start_frame=0,
                end_frame=30,
                parameter_sequence=CompiledParameterFrameSequence(
                    sequence_id="params", base_asset_id="base", stage_asset_id="stage", final_asset_id="final",
                    start_frame=8, stage_frame=14, hit_frame=26, minimum_hold_frames=10, crossfade_frames=3,
                    timing_source="keyword_end",
                ),
            )
        ],
        subtitles=[],
        audio_tracks=[AudioTrack(kind="voice", path="voice.mp3")],
    )

    checks = {check.check_id: check for check in validate_render_plan(plan)}

    assert checks["effect_timing_requirements"].status == "passed"
    assert checks["parameter_sequence_timing"].status == "failed"


def test_overlay_layout_rejects_douyin_rail_and_subtitle_slots() -> None:
    plan = RenderPlan(
        case_id="demo", run_id="run", frame_count=30,
        assets=[RenderAsset(asset_id="asset", path="demo.png", sha256="a" * 64, width=100, height=100)],
        shots=[RenderShot(shot_id="base", beat_ids=["beat"], template="result_showcase", asset_bindings={"primary": "asset"}, start_frame=0, end_frame=30), RenderShot(shot_id="overlay", track="overlay", beat_ids=["beat"], template="brand_ip_cutaway", asset_bindings={"primary": "asset"}, start_frame=0, end_frame=30, overlay_layout={"x": 0.86, "y": 0.3, "w": 0.14, "h": 0.3, "fit": "contain", "opacity": 1.0, "z_index": 10})],
        subtitles=[], audio_tracks=[AudioTrack(kind="voice", path="voice.mp3")],
    )
    checks = {check.check_id: check for check in validate_render_plan(plan)}
    assert checks["overlay_platform_safe"].status == "failed"


def test_wipe_transition_and_fake_carousel_are_removed() -> None:
    with pytest.raises(ValidationError):
        TransitionIn(kind="wipe_left", duration_frames=8)  # type: ignore[arg-type]
    plan = RenderPlan(
        case_id="demo", run_id="run", frame_count=30,
        assets=[RenderAsset(asset_id="asset", path="demo.png", sha256="a" * 64, width=100, height=100)],
        shots=[RenderShot(shot_id="shot", beat_ids=["beat"], template="image_carousel", asset_bindings={"primary": "asset"}, start_frame=0, end_frame=30)],
        subtitles=[], audio_tracks=[AudioTrack(kind="voice", path="voice.mp3")],
    )
    checks = {check.check_id: check for check in validate_render_plan(plan)}
    assert checks["template_implemented"].status == "failed"


def test_runtime_contracts_reject_programmatic_asset_coordinates() -> None:
    with pytest.raises(ValidationError):
        CueBinding(action="focus.hit", anchor_id="phrase", asset_anchor_id="wrong_coordinate")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        RenderAsset(asset_id="asset", path="demo.png", sha256="a" * 64, width=100, height=100, anchors={"wrong": {"x": 0.1}})  # type: ignore[call-arg]

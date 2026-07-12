from __future__ import annotations

from video_agent.compiler.subtitles import compile_subtitles, fullwidth_units
from video_agent.contracts import (
    AudioTrack,
    BeatSpan,
    RenderAsset,
    RenderPlan,
    RenderShot,
    SubtitleCue,
    TimingLock,
    TokenTiming,
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


def test_subtitle_compiler_outputs_only_short_single_lines() -> None:
    cues = compile_subtitles(_timing())
    assert len(cues) >= 2
    assert all("\n" not in cue.text and fullwidth_units(cue.text) <= 10 for cue in cues)
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
    assert checks["subtitle_single_line_10_units"].status == "failed"


def test_qa_rejects_perspective_on_text_dense_ui() -> None:
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
                motion="perspective_push_in",
            )
        ],
        subtitles=[],
        audio_tracks=[AudioTrack(kind="voice", path="voice.mp3")],
    )
    checks = {check.check_id: check for check in validate_render_plan(plan)}
    assert checks["text_dense_motion_safe"].status == "failed"

from __future__ import annotations

from video_agent.compiler.v4.font_measure import measure_text_width_px, resolve_subtitle_font_path
from video_agent.compiler.v4.subtitles import compile_subtitles_v4
from video_agent.contracts.v4 import (
    AnchoredSceneSpan,
    AnchoredTimingPlan,
    PhraseAnchorV4,
    SceneSemanticPlan,
    SemanticScene,
    SpeechTimingLock,
    SpeechTokenTimingV4,
)
from video_agent.platform.profiles import get_profile


def test_subtitle_font_measure_uses_real_font() -> None:
    path = resolve_subtitle_font_path()
    assert path.is_file()
    wide = measure_text_width_px("文化墙门头招牌美陈都能一键出图")
    narrow = measure_text_width_px("文化墙")
    assert wide > narrow > 0
    profile = get_profile("douyin_portrait_v1")
    assert narrow < profile.subtitle_lower.w


def test_compile_subtitles_uses_platform_slot_width() -> None:
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="打开柯幻熊猫。",
                visual_structure="single",
                slots=[],
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
            text="打开柯幻熊猫。",
            start_ms=0,
            end_ms=400,
            start_frame=0,
            end_frame=12,
            beat_id=None,
        )
    ]
    speech = SpeechTimingLock(
        schema_version=1,
        case_id="c",
        run_id="r",
        narration_sha256="a" * 64,
        audio_object_key="audio/speech.wav",
        audio_sha256="a" * 64,
        voice_profile_id="v",
        voice_profile_version="1",
        voice_profile_sha256="a" * 64,
        fps=30,
        duration_ms=400,
        duration_frames=12,
        tokens=tokens,
        pause_events=[],
        beat_spans=[],
    )
    anchored = AnchoredTimingPlan(
        schema_version=1,
        case_id="c",
        run_id="r",
        narration_sha256="a" * 64,
        speech_timing_lock_sha256="a" * 64,
        scene_plan_sha256="a" * 64,
        fps=30,
        duration_frames=12,
        scene_spans=[AnchoredSceneSpan(scene_id="s001", token_ids=["tok_0000"], start_frame=0, end_frame=12)],
        anchors=[
            PhraseAnchorV4(
                anchor_id="a1",
                scene_id="s001",
                text="打开柯幻熊猫",
                token_ids=["tok_0000"],
                onset_ms=0,
                end_ms=400,
                onset_frame=0,
                end_frame=12,
                hit_frame=0,
            )
        ],
        bindings=[],
    )
    cues = compile_subtitles_v4(speech=speech, scene_plan=scene_plan, anchored=anchored)
    assert cues
    assert all(cue.slot_id == "subtitle_top" for cue in cues)

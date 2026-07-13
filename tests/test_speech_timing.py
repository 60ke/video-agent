from __future__ import annotations

from pathlib import Path

import pytest

from video_agent.contracts import Narration, NarrationBeat, PauseIntent
from video_agent.speech.pause_compiler import compile_narration_markup
from video_agent.speech.minimax import normalize_tokens
from video_agent.speech.timing_lock import build_timing_lock, ms_to_frame


def _tokens(text: str, step_ms: int = 120) -> list[dict[str, int | str]]:
    return [
        {"text": char, "start_ms": index * step_ms, "end_ms": (index + 1) * step_ms - 10}
        for index, char in enumerate(text)
    ]


def test_explicit_pause_markup_is_disabled() -> None:
    narration = Narration(
        case_id="pause_case",
        beats=[
            NarrationBeat(
                beat_id="beat_001",
                spoken_text="上传LOGO，再填写品牌名称。",
                pause_intents=[PauseIntent(after_phrase="上传LOGO", kind="short", requested_ms=180)],
            ),
            NarrationBeat(beat_id="beat_002", spoken_text="一键生成。"),
        ],
    )

    markup = compile_narration_markup(narration)

    assert markup == "上传LOGO，再填写品牌名称。\n一键生成。"
    assert markup.replace("\n", "") == narration.spoken_text
    assert "<#" not in markup


def test_narration_beat_supports_enumerated_visual_strategy() -> None:
    beat = NarrationBeat(
        beat_id="beat_001",
        spoken_text="文化墙、美陈。",
        visual_strategy="enumerated_results",
        hit_phrases=["文化墙", "美陈"],
    )

    assert beat.visual_strategy == "enumerated_results"


def test_word_timing_is_strict_and_frame_locked(tmp_path: Path) -> None:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"synthetic-audio")
    narration = Narration(
        case_id="timing_case",
        beats=[
            NarrationBeat(
                beat_id="beat_001",
                spoken_text="填写品牌名称。",
                hit_phrases=["品牌名称"],
                pause_intents=[PauseIntent(after_phrase="品牌名称", kind="short", requested_ms=160)],
            )
        ],
    )
    raw = _tokens(narration.spoken_text)
    timing = build_timing_lock("timing_case", narration, raw, audio, len(raw) * 120, 30)

    assert timing.phrase_anchors[0].text == "品牌名称"
    assert timing.phrase_anchors[0].hit_frame == ms_to_frame(2 * 120, 30)
    assert timing.duration_frames == ms_to_frame(len(raw) * 120, 30)

    broken = list(raw)
    broken[0] = {**broken[0], "text": "选"}
    with pytest.raises(ValueError, match="text mismatch"):
        build_timing_lock("timing_case", narration, broken, audio, len(raw) * 120, 30)


def test_word_timing_allows_only_punctuation_omission_and_restores_it(tmp_path: Path) -> None:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"synthetic-audio")
    narration = Narration(
        case_id="punctuation_case",
        beats=[NarrationBeat(beat_id="beat_001", spoken_text="确认后，点击开始生成。", hit_phrases=["开始生成"])],
    )
    raw_text = "确认后点击开始生成。"
    raw = _tokens(raw_text)

    timing = build_timing_lock("punctuation_case", narration, raw, audio, len(raw) * 120, 30)

    assert "".join(token.text for token in timing.tokens) == narration.spoken_text
    assert timing.phrase_anchors[0].text == "开始生成"


def test_minimax_timestamp_unit_is_detected_for_the_whole_response() -> None:
    raw = [
        {"word": "短", "time_begin": 20, "time_end": 80},
        {"word": "句", "time_begin": 1200, "time_end": 1500},
    ]
    assert normalize_tokens(raw) == [
        {"text": "短", "start_ms": 20, "end_ms": 80},
        {"text": "句", "start_ms": 1200, "end_ms": 1500},
    ]


def test_minimax_collapses_exact_span_duplicate_numeric_word() -> None:
    raw = {
        "subtitles": [
            {
                "timestamped_words": [
                    {"word": "还", "word_begin": 0, "word_end": 1, "time_begin": 0, "time_end": 1000},
                    {"word": "20", "word_begin": 1, "word_end": 3, "time_begin": 1000, "time_end": 2000},
                    {"word": "20", "word_begin": 1, "word_end": 3, "time_begin": 2000, "time_end": 3000},
                    {"word": "多", "word_begin": 3, "word_end": 4, "time_begin": 3000, "time_end": 4000},
                ]
            }
        ]
    }

    assert normalize_tokens(raw) == [
        {"text": "还", "start_ms": 0, "end_ms": 1000},
        {"text": "20", "start_ms": 1000, "end_ms": 2000},
        {"text": "多", "start_ms": 3000, "end_ms": 4000},
    ]


def test_punctuation_token_end_is_merged_into_previous_word(tmp_path: Path) -> None:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"synthetic-audio")
    narration = Narration(
        case_id="punctuation_pause",
        beats=[
            NarrationBeat(
                beat_id="beat_001",
                spoken_text="确认后，继续。",
                pause_intents=[PauseIntent(after_phrase="确认后，", kind="micro", requested_ms=60)],
            )
        ],
    )
    raw = [
        {"text": "确", "start_ms": 0, "end_ms": 100},
        {"text": "认", "start_ms": 100, "end_ms": 200},
        {"text": "后", "start_ms": 200, "end_ms": 300},
        {"text": "，", "start_ms": 300, "end_ms": 360},
        {"text": "继", "start_ms": 500, "end_ms": 600},
        {"text": "续", "start_ms": 600, "end_ms": 700},
        {"text": "。", "start_ms": 700, "end_ms": 750},
    ]
    timing = build_timing_lock("punctuation_pause", narration, raw, audio, 800, 30)
    assert timing.pause_events == []

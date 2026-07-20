"""V4 SpeechTimingLock builder (voice facts only)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from video_agent.contracts.v4 import (
    ResolvedVoiceProfile,
    SpeechBeatSpanV4,
    SpeechPauseEventV4,
    SpeechTimingLock,
    SpeechTokenTimingV4,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.io import sha256_file, sha256_json
from video_agent.timing.v4.timebase import duration_frames, ms_to_hit_frame, ms_to_interval_end


SPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    compact = SPACE_RE.sub("", text).lower()
    return "".join(char for char in compact if not unicodedata.category(char).startswith("P"))


def _display_slices(text: str, lexical_lengths: list[int]) -> list[str]:
    compact = SPACE_RE.sub("", text)
    lexical_total = sum(1 for char in compact if not unicodedata.category(char).startswith("P"))
    if sum(lexical_lengths) != lexical_total:
        raise Stage6Error("speech_text_mismatch", "word timing lexical lengths do not match narration")
    slices: list[str] = []
    display_cursor = 0
    lexical_cursor = 0
    for length in lexical_lengths:
        target = lexical_cursor + length
        index = display_cursor
        seen = lexical_cursor
        while index < len(compact) and seen < target:
            if not unicodedata.category(compact[index]).startswith("P"):
                seen += 1
            index += 1
        while index < len(compact) and unicodedata.category(compact[index]).startswith("P"):
            index += 1
        slices.append(compact[display_cursor:index])
        display_cursor = index
        lexical_cursor = target
    if display_cursor != len(compact):
        raise Stage6Error("speech_text_mismatch", "word timing could not recover narration punctuation")
    return slices


def voice_profile_content_sha256(profile: ResolvedVoiceProfile) -> str:
    return sha256_json(profile.model_dump(mode="json"))


def build_speech_timing_lock(
    *,
    case_id: str,
    run_id: str,
    narration_text: str,
    narration_sha256: str,
    raw_tokens: list[dict[str, Any]],
    audio_object_key: str,
    audio_path: Path,
    duration_ms: int,
    fps: int,
    voice_profile: ResolvedVoiceProfile,
) -> SpeechTimingLock:
    """Build SpeechTimingLock from provider word timestamps. Never emits PhraseAnchors."""
    usable = [token for token in raw_tokens if str(token.get("text") or "").strip()]
    if not usable:
        raise Stage6Error("speech_text_mismatch", "speech timing has no usable tokens")

    lexical_lengths = [len(normalize_text(str(token["text"]))) for token in usable]
    if sum(lexical_lengths) == 0:
        raise Stage6Error("speech_text_mismatch", "speech timing tokens are empty after normalization")
    display_slices = _display_slices(narration_text, lexical_lengths)
    joined = normalize_text("".join(str(token["text"]) for token in usable))
    if joined != normalize_text(narration_text):
        raise Stage6Error("speech_text_mismatch", "speech tokens do not match frozen narration")

    tokens: list[SpeechTokenTimingV4] = []
    for index, (token, display) in enumerate(zip(usable, display_slices, strict=True)):
        start_ms = int(token["start_ms"])
        end_ms = int(token["end_ms"])
        start_frame = ms_to_hit_frame(start_ms, fps)
        end_frame = max(start_frame + 1, ms_to_interval_end(end_ms, fps))
        tokens.append(
            SpeechTokenTimingV4(
                token_id=f"tok_{index:04d}",
                text=display,
                start_ms=start_ms,
                end_ms=end_ms,
                start_frame=start_frame,
                end_frame=end_frame,
                beat_id=None,
            )
        )

    frames = max(duration_frames(duration_ms, fps), tokens[-1].end_frame)
    beat = SpeechBeatSpanV4(
        beat_id="speech_full",
        token_ids=[token.token_id for token in tokens],
        start_frame=tokens[0].start_frame,
        end_frame=frames,
    )
    return SpeechTimingLock(
        schema_version=1,
        case_id=case_id,
        run_id=run_id,
        narration_sha256=narration_sha256,
        audio_object_key=audio_object_key.replace("\\", "/"),
        audio_sha256=sha256_file(audio_path),
        voice_profile_id=voice_profile.profile_id,
        voice_profile_version=voice_profile.profile_version,
        voice_profile_sha256=voice_profile_content_sha256(voice_profile),
        fps=fps,
        duration_ms=duration_ms,
        duration_frames=frames,
        tokens=tokens,
        pause_events=[],
        beat_spans=[beat],
    )


# Silence unused import warning for Pause type availability in future pause detection.
_ = SpeechPauseEventV4

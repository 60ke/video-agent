from __future__ import annotations

from pathlib import Path

from video_agent.contracts.v4 import ResolvedVoiceProfile, SpeechTimingLock
from video_agent.io import sha256_json
from video_agent.timing.v4.speech_lock import build_speech_timing_lock
from video_agent.timing.v4.timebase import duration_frames, ms_to_hit_frame, ms_to_interval_end


def test_timebase_rounding() -> None:
    assert ms_to_hit_frame(50, 30) == 2  # 1.5 -> 2 half-up
    assert ms_to_interval_end(50, 30) == 2
    assert ms_to_interval_end(33, 30) == 1  # 0.99 -> 1
    assert duration_frames(1000, 30) == 30


def test_build_speech_timing_lock_has_no_phrase_anchors(tmp_path: Path) -> None:
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"RIFF....WAVEfmt ")
    profile = ResolvedVoiceProfile(
        schema_version=1,
        profile_id="minimax_adman_clear_01",
        profile_version="1",
        provider="minimax",
        provider_voice_ref="voice_x",
        voice_ref_fingerprint="b" * 64,
        language="zh-CN",
        speed=1.2,
        emotion=None,
        subtitle_type="default",
        resolve_mode="fixed",
        registry_snapshot_id="reg",
    )
    narration = "文化墙设计"
    tokens = [
        {"text": "文化墙", "start_ms": 0, "end_ms": 400},
        {"text": "设计", "start_ms": 400, "end_ms": 800},
    ]
    lock = build_speech_timing_lock(
        case_id="case",
        run_id="run",
        narration_text=narration,
        narration_sha256="c" * 64,
        raw_tokens=tokens,
        audio_object_key="audio/speech.wav",
        audio_path=audio,
        duration_ms=800,
        fps=30,
        voice_profile=profile,
    )
    assert isinstance(lock, SpeechTimingLock)
    dumped = lock.model_dump(mode="json")
    assert "phrase_anchors" not in dumped
    assert lock.voice_profile_sha256 == sha256_json(profile.model_dump(mode="json"))
    assert lock.tokens[0].text == "文化墙"
    assert lock.tokens[0].end_frame > lock.tokens[0].start_frame

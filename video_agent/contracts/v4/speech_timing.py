"""V4 SpeechTimingLock — TTS voice facts only (no semantic PhraseAnchors)."""

from __future__ import annotations

from pydantic import Field, model_validator

from .common import V4Contract

_SHA256 = r"^[a-f0-9]{64}$"


class SpeechTokenTimingV4(V4Contract):
    token_id: str = Field(min_length=1)
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)  # exclusive
    beat_id: str | None = None

    @model_validator(mode="after")
    def valid_span(self) -> SpeechTokenTimingV4:
        if self.end_ms < self.start_ms:
            raise ValueError("token end_ms must be >= start_ms")
        if self.end_frame <= self.start_frame:
            raise ValueError("token end_frame must be exclusive and > start_frame")
        return self


class SpeechPauseEventV4(V4Contract):
    pause_id: str = Field(min_length=1)
    after_token_id: str = Field(min_length=1)
    requested_ms: int = Field(ge=0)
    measured_start_ms: int = Field(ge=0)
    measured_end_ms: int = Field(ge=0)
    measured_start_frame: int = Field(ge=0)
    measured_end_frame: int = Field(ge=0)


class SpeechBeatSpanV4(V4Contract):
    beat_id: str = Field(min_length=1)
    token_ids: list[str] = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)  # exclusive

    @model_validator(mode="after")
    def valid_span(self) -> SpeechBeatSpanV4:
        if self.end_frame <= self.start_frame:
            raise ValueError("beat span end_frame must be exclusive and > start_frame")
        return self


class SpeechTimingLock(V4Contract):
    schema_version: int = Field(ge=1)
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    narration_sha256: str = Field(pattern=_SHA256)
    audio_object_key: str = Field(min_length=1)
    audio_sha256: str = Field(pattern=_SHA256)
    voice_profile_id: str = Field(min_length=1)
    voice_profile_version: str = Field(min_length=1)
    voice_profile_sha256: str = Field(pattern=_SHA256)
    fps: int = Field(gt=0)
    duration_ms: int = Field(ge=0)
    duration_frames: int = Field(ge=0)
    tokens: list[SpeechTokenTimingV4] = Field(min_length=1)
    pause_events: list[SpeechPauseEventV4] = Field(default_factory=list)
    beat_spans: list[SpeechBeatSpanV4] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_absolute_audio_path(self) -> SpeechTimingLock:
        key = self.audio_object_key.replace("\\", "/")
        if key.startswith("/") or (len(key) >= 2 and key[1] == ":"):
            raise ValueError("audio_object_key must be a run-relative POSIX path")
        if ".." in key.split("/"):
            raise ValueError("audio_object_key must not contain parent traversal")
        return self

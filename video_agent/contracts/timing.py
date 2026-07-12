from __future__ import annotations

from pydantic import Field, model_validator

from .base import Contract, VersionedContract


class TokenTiming(Contract):
    token_id: str
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    beat_id: str | None = None

    @model_validator(mode="after")
    def valid_span(self) -> "TokenTiming":
        if self.end_ms <= self.start_ms or self.end_frame <= self.start_frame:
            raise ValueError("token timing must have positive duration")
        return self


class PhraseAnchor(Contract):
    anchor_id: str
    text: str
    token_ids: list[str] = Field(min_length=1)
    hit_frame: int = Field(ge=0)
    beat_id: str


class PauseEvent(Contract):
    pause_id: str
    after_token_id: str
    requested_ms: int = Field(ge=0)
    measured_start_frame: int = Field(ge=0)
    measured_end_frame: int = Field(ge=0)

    @property
    def measured_frames(self) -> int:
        return max(0, self.measured_end_frame - self.measured_start_frame)


class BeatSpan(Contract):
    beat_id: str
    token_ids: list[str] = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)


class TimingLock(VersionedContract):
    case_id: str
    audio_path: str
    audio_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fps: int = Field(gt=0)
    duration_ms: int = Field(gt=0)
    duration_frames: int = Field(gt=0)
    tokens: list[TokenTiming] = Field(min_length=1)
    phrase_anchors: list[PhraseAnchor] = Field(default_factory=list)
    pause_events: list[PauseEvent] = Field(default_factory=list)
    beat_spans: list[BeatSpan] = Field(min_length=1)

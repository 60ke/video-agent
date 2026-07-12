from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Contract, VersionedContract


class PauseIntent(Contract):
    after_phrase: str
    kind: Literal["micro", "short", "beat", "section"]
    requested_ms: int = Field(ge=10, le=450)


class NarrationBeat(Contract):
    beat_id: str
    spoken_text: str = Field(min_length=1)
    tts_markup_text: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    asset_slots: list[str] = Field(default_factory=list)
    hit_phrases: list[str] = Field(default_factory=list)
    pause_intents: list[PauseIntent] = Field(default_factory=list)


class Narration(VersionedContract):
    case_id: str
    beats: list[NarrationBeat] = Field(min_length=1)
    voice_style: str = "清晰、自然、有节奏"

    @property
    def spoken_text(self) -> str:
        return "".join(beat.spoken_text for beat in self.beats)

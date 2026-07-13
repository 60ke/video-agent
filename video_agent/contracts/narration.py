from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .assets import EvidenceClass
from .base import Contract, VersionedContract


class PauseIntent(Contract):
    after_phrase: str
    kind: Literal["micro", "short", "beat", "section"]
    requested_ms: int = Field(ge=10, le=450)


class Claim(Contract):
    """A factual statement that may appear in narration or a visual shot."""

    claim_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1)
    supporting_asset_ids: list[str] = Field(min_length=1)
    required_evidence_classes: list[EvidenceClass] = Field(
        default_factory=lambda: [EvidenceClass.SOURCE, EvidenceClass.FAITHFUL],
        min_length=1,
    )

    @model_validator(mode="after")
    def factual_evidence_only(self) -> "Claim":
        unsupported = set(self.required_evidence_classes) - {EvidenceClass.SOURCE, EvidenceClass.FAITHFUL}
        if unsupported:
            raise ValueError("factual claims require E0 source or E1 faithful evidence")
        return self


class ClaimCue(Contract):
    claim_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    phrase: str = Field(min_length=1)


class NarrationBeat(Contract):
    beat_id: str
    spoken_text: str = Field(min_length=1)
    tts_markup_text: str | None = None
    claim_cues: list[ClaimCue] = Field(default_factory=list)
    asset_slots: list[str] = Field(default_factory=list)
    hit_phrases: list[str] = Field(default_factory=list)
    pause_intents: list[PauseIntent] = Field(default_factory=list)

    @model_validator(mode="after")
    def claim_phrases_are_spoken(self) -> "NarrationBeat":
        missing = [cue.phrase for cue in self.claim_cues if cue.phrase not in self.spoken_text]
        if missing:
            raise ValueError(f"claim cue phrases must appear verbatim in spoken_text: {missing}")
        return self


class Narration(VersionedContract):
    case_id: str
    beats: list[NarrationBeat] = Field(min_length=1)
    claims: list[Claim] = Field(default_factory=list)
    voice_style: str = "清晰、自然、有节奏"

    @model_validator(mode="after")
    def claim_references_exist(self) -> "Narration":
        known = {claim.claim_id for claim in self.claims}
        if len(known) != len(self.claims):
            raise ValueError("claim_id values must be unique")
        unknown = sorted({cue.claim_id for beat in self.beats for cue in beat.claim_cues} - known)
        if unknown:
            raise ValueError(f"beats reference unknown claims: {unknown}")
        return self

    @property
    def spoken_text(self) -> str:
        return "".join(beat.spoken_text for beat in self.beats)

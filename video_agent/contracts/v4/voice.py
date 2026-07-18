from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import V4Contract


class ResolvedVoiceProfile(V4Contract):
    schema_version: int = Field(default=1, ge=1)
    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    provider_voice_ref: str = Field(min_length=1)
    voice_ref_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    language: str = Field(min_length=1)
    speed: float = Field(gt=0)
    emotion: str | None = None
    subtitle_type: str = Field(min_length=1)
    resolve_mode: Literal["fixed", "auto"]
    registry_snapshot_id: str = Field(min_length=1)

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .base import Contract, VersionedContract


class VideoFormat(Contract):
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    fps: Literal[30] = 30


class DurationPolicy(Contract):
    preferred_min_sec: float = 15.0
    preferred_max_sec: float = 20.0
    hard_max_sec: float = 60.0

    @model_validator(mode="after")
    def validate_order(self) -> "DurationPolicy":
        if not 0 < self.preferred_min_sec <= self.preferred_max_sec <= self.hard_max_sec:
            raise ValueError("duration limits must satisfy 0 < preferred_min <= preferred_max <= hard_max")
        return self


class VoiceConfig(Contract):
    provider: Literal["minimax"] = "minimax"
    model: str = "speech-2.8-hd"
    voice_id: str = "male-qn-qingse"
    speed: float = Field(default=1.2, ge=0.5, le=2.0)
    emotion: str | None = None
    subtitle_type: Literal["word"] = "word"
    pause_profile: str = "disabled"
    # Stage 5 Voice Registry ID for fixed resolve before TTS. When set (or when
    # V4 Stage1 runs), speed/voice_id are projected from the frozen registry.
    voice_profile_id: str | None = None


class SemanticSfx(Contract):
    path: str = Field(min_length=1)
    gain_db: float = Field(default=-14.0, ge=-36.0, le=3.0)
    trim_start_ms: int = Field(default=0, ge=0, le=5000)
    max_duration_ms: int = Field(default=700, ge=40, le=5000)
    fade_in_ms: int = Field(default=5, ge=0, le=500)
    fade_out_ms: int = Field(default=80, ge=0, le=1000)
    priority: int = Field(default=50, ge=0, le=100)
    sync_point: Literal["onset", "peak"] = "onset"
    sync_offset_ms: int = Field(default=0, ge=0, le=1000)

    @model_validator(mode="after")
    def validate_fades(self) -> "SemanticSfx":
        if self.fade_in_ms + self.fade_out_ms > self.max_duration_ms:
            raise ValueError("SFX fades cannot exceed max_duration_ms")
        return self


class SfxDensityPolicy(Contract):
    profile: Literal["clean", "normal", "energetic", "custom"] = "normal"
    min_gap_ms: int | None = Field(default=None, ge=0, le=3000)
    window_ms: int | None = Field(default=None, ge=500, le=10000)
    max_events_per_window: int | None = Field(default=None, ge=1, le=12)
    repeat_cooldown_ms: int | None = Field(default=None, ge=0, le=10000)

    @model_validator(mode="after")
    def resolve_profile(self) -> "SfxDensityPolicy":
        profiles = {
            "clean": (420, 3500, 2, 1100),
            "normal": (280, 3000, 3, 900),
            "energetic": (140, 2200, 5, 500),
        }
        if self.profile != "custom":
            gap, window, maximum, repeat = profiles[self.profile]
            # Assignment validation is enabled by Contract, so use the model's
            # raw setter inside this post-validation normalization step.
            object.__setattr__(self, "min_gap_ms", gap)
            object.__setattr__(self, "window_ms", window)
            object.__setattr__(self, "max_events_per_window", maximum)
            object.__setattr__(self, "repeat_cooldown_ms", repeat)
        return self


class AudioConfig(Contract):
    bgm_path: str | None = None
    bgm_gain_db: float = Field(default=-22.0, ge=-60.0, le=0.0)
    voice_gain_db: float = Field(default=0.0, ge=-24.0, le=12.0)
    sfx_profile: str | None = "douyin_common_v1"
    sfx_overrides: dict[str, SemanticSfx] = Field(default_factory=dict)
    sfx_density: SfxDensityPolicy = Field(default_factory=SfxDensityPolicy)


class CaseConfig(VersionedContract):
    case_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    goal: str = Field(min_length=1)
    mode: Literal["material_first", "script_locked"] = "material_first"
    quality: Literal["draft", "final"] = "final"
    feature_path: list[str] = Field(default_factory=list)
    format: VideoFormat = Field(default_factory=VideoFormat)
    duration_policy: DurationPolicy = Field(default_factory=DurationPolicy)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    platform_profile: Literal["douyin_portrait_v1"] = "douyin_portrait_v1"
    narration_source: str | None = None
    selected_asset_ids: list[str] = Field(default_factory=list)
    cover_enabled: bool = True
    cover_source: str = "input/cover.json"
    outro_enabled: bool = True
    outro_source: str = "assets/outro/default_panda_outro.mp4"
    ai_enabled: bool = False

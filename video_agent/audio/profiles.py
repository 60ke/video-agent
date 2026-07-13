from __future__ import annotations

import wave
from pathlib import Path

from pydantic import Field

from video_agent.contracts import SemanticSfx
from video_agent.contracts.base import Contract
from video_agent.io import load_model, sha256_file


class RegisteredSfx(SemanticSfx):
    semantic_id: str
    filename: str
    source_filename: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    registered_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sample_rate: int
    sample_width_bits: int
    channels: int
    duration_ms: int
    allowed_intents: list[str] = Field(default_factory=list)
    forbidden_intents: list[str] = Field(default_factory=list)

    def runtime_config(self) -> SemanticSfx:
        fields = SemanticSfx.model_fields.keys()
        return SemanticSfx.model_validate({name: getattr(self, name) for name in fields})


class SfxCatalog(Contract):
    schema_version: int = 1
    profile_id: str
    normalization: dict[str, int | str]
    assets: list[RegisteredSfx]


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "assets" / "audio" / "sfx" / "catalog.json"


def load_sfx_catalog() -> SfxCatalog:
    path = _catalog_path()
    if not path.is_file():
        raise FileNotFoundError(f"SFX catalog is missing: {path}")
    catalog = load_model(path, SfxCatalog)
    ids = [asset.semantic_id for asset in catalog.assets]
    if len(ids) != len(set(ids)):
        raise ValueError("SFX catalog semantic_id values must be unique")
    for asset in catalog.assets:
        audio_path = path.parent / asset.filename
        if not audio_path.is_file():
            raise FileNotFoundError(f"registered SFX is missing: {audio_path}")
        if sha256_file(audio_path) != asset.registered_sha256:
            raise ValueError(f"registered SFX hash differs from catalog: {audio_path}")
        with wave.open(str(audio_path), "rb") as audio:
            actual = (audio.getframerate(), audio.getsampwidth() * 8, audio.getnchannels())
        expected = (asset.sample_rate, asset.sample_width_bits, asset.channels)
        if actual != expected or actual != (48_000, 16, 2):
            raise ValueError(f"registered SFX format differs from catalog: {audio_path}")
    return catalog


def get_sfx_profile(name: str | None) -> dict[str, SemanticSfx]:
    if name is None:
        return {}
    catalog = load_sfx_catalog()
    if name != catalog.profile_id:
        raise ValueError(f"unknown SFX profile: {name}")
    return {asset.semantic_id: asset.runtime_config() for asset in catalog.assets}


def merge_sfx_profile(name: str | None, overrides: dict[str, SemanticSfx]) -> dict[str, SemanticSfx]:
    profile = get_sfx_profile(name)
    profile.update({key: value.model_copy(deep=True) for key, value in overrides.items()})
    return profile

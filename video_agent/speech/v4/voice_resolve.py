from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from video_agent.contracts.v4 import ResolvedVoiceProfile, VoiceEntry
from video_agent.registries import CapabilityRegistryHub
from video_agent.speech.minimax import load_minimax_local_config


DEFAULT_FIXED_VOICE_PROFILE_ID = "minimax_adman_clear_01"


class VoiceResolveError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_provider_voice_value(provider_voice_ref: str, *, repo_root: Path) -> str:
    """Resolve a registry voice ref to the provider value without exposing secrets in artifacts."""
    if provider_voice_ref.startswith("local:minimax."):
        key = provider_voice_ref.removeprefix("local:minimax.")
        local = load_minimax_local_config(repo_root)
        value = str(local.get(key) or "").strip()
        if not value:
            raise VoiceResolveError(
                "voice_provider_incompatible",
                f"local MiniMax config missing key for {provider_voice_ref}",
            )
        return value
    if provider_voice_ref.startswith("literal:"):
        value = provider_voice_ref.removeprefix("literal:").strip()
        if not value:
            raise VoiceResolveError("voice_provider_incompatible", "empty literal voice ref")
        return value
    raise VoiceResolveError(
        "voice_provider_incompatible",
        f"unsupported provider_voice_ref: {provider_voice_ref}",
    )


def resolve_fixed_voice_profile(
    hub: CapabilityRegistryHub,
    *,
    repo_root: Path,
    voice_profile_id: str | None = None,
    speed_override: float | None = None,
    emotion_override: str | None = None,
    registry_snapshot_id: str | None = None,
) -> ResolvedVoiceProfile:
    profile_id = (voice_profile_id or DEFAULT_FIXED_VOICE_PROFILE_ID).strip()
    entry = hub.entry("voice", profile_id)
    if entry is None or not isinstance(entry, VoiceEntry):
        raise VoiceResolveError("voice_profile_missing", f"unknown or disabled voice profile: {profile_id}")
    caps = entry.capabilities
    if caps.resolve_mode != "fixed":
        raise VoiceResolveError(
            "voice_provider_incompatible",
            f"voice profile {profile_id} resolve_mode={caps.resolve_mode} is not fixed",
        )
    if caps.provider != "minimax":
        raise VoiceResolveError(
            "voice_provider_incompatible",
            f"unsupported voice provider: {caps.provider}",
        )
    resolved_voice = resolve_provider_voice_value(caps.provider_voice_ref, repo_root=repo_root)
    fingerprint = sha256(resolved_voice.encode("utf-8")).hexdigest()
    snapshot_id = registry_snapshot_id or hub.snapshot().snapshot_id
    speed = float(speed_override) if speed_override is not None else float(caps.default_speed)
    emotion = emotion_override
    if emotion is not None and caps.supported_emotions and emotion not in caps.supported_emotions:
        raise VoiceResolveError(
            "voice_provider_incompatible",
            f"emotion {emotion!r} is not supported by voice profile {profile_id}",
        )
    return ResolvedVoiceProfile(
        profile_id=entry.id,
        profile_version=str(entry.schema_version),
        provider=caps.provider,
        provider_voice_ref=caps.provider_voice_ref,
        voice_ref_fingerprint=fingerprint,
        language=caps.language,
        speed=speed,
        emotion=emotion,
        subtitle_type=caps.subtitle_type,
        resolve_mode="fixed",
        registry_snapshot_id=snapshot_id,
    )


def apply_resolved_voice_to_case_voice(
    case_voice: dict[str, Any],
    resolved: ResolvedVoiceProfile,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Project ResolvedVoiceProfile into the legacy VoiceConfig dict used by MiniMax TTS."""
    patched = dict(case_voice)
    patched["provider"] = resolved.provider
    patched["voice_id"] = resolve_provider_voice_value(resolved.provider_voice_ref, repo_root=repo_root)
    patched["speed"] = resolved.speed
    patched["subtitle_type"] = "word" if resolved.subtitle_type in {"zh", "word"} else resolved.subtitle_type
    if resolved.emotion is not None:
        patched["emotion"] = resolved.emotion
    return patched

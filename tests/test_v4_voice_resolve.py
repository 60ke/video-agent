from __future__ import annotations

from pathlib import Path

import pytest

from video_agent.contracts.v4 import VoiceEntry
from video_agent.registries import CapabilityRegistryHub
from video_agent.speech.v4.voice_resolve import (
    VoiceResolveError,
    apply_resolved_voice_to_case_voice,
    resolve_fixed_voice_profile,
)


REGISTRY_ROOT = Path(__file__).parents[1] / "config" / "registries" / "v4"


def test_fixed_voice_resolve_uses_registry_default_speed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)
    monkeypatch.setattr(
        "video_agent.speech.v4.voice_resolve.load_minimax_local_config",
        lambda _root: {"voice_id": "adman_ai_clone_test"},
    )
    resolved = resolve_fixed_voice_profile(
        hub,
        repo_root=tmp_path,
        registry_snapshot_id="registry-snapshot://sha256/" + ("a" * 64),
    )
    assert resolved.profile_id == "minimax_adman_clear_01"
    assert resolved.resolve_mode == "fixed"
    assert resolved.speed == 1.2
    assert resolved.provider_voice_ref == "local:minimax.voice_id"
    assert len(resolved.voice_ref_fingerprint) == 64
    # Artifact must keep only the fingerprint, never the resolved provider voice id.
    assert "adman_ai_clone_test" not in resolved.model_dump_json()

    patched = apply_resolved_voice_to_case_voice(
        {"provider": "minimax", "model": "speech-2.8-hd", "voice_id": "old", "speed": 1.0, "subtitle_type": "word"},
        resolved,
        repo_root=tmp_path,
    )
    assert patched["voice_id"] == "adman_ai_clone_test"
    assert patched["speed"] == 1.2


def test_case_speed_overrides_registry_when_profile_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)
    monkeypatch.setattr(
        "video_agent.speech.v4.voice_resolve.load_minimax_local_config",
        lambda _root: {"voice_id": "adman_ai_clone_test"},
    )
    resolved = resolve_fixed_voice_profile(
        hub,
        repo_root=tmp_path,
        voice_profile_id="minimax_adman_clear_01",
        speed_override=1.35,
        registry_snapshot_id="registry-snapshot://sha256/" + ("b" * 64),
    )
    assert resolved.speed == 1.35


def test_missing_voice_profile_fails_loud(tmp_path: Path) -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)
    with pytest.raises(VoiceResolveError) as exc:
        resolve_fixed_voice_profile(hub, repo_root=tmp_path, voice_profile_id="no_such_voice")
    assert exc.value.code == "voice_profile_missing"


def test_voice_entry_is_typed() -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)
    entry = hub.require_entry("voice", "minimax_adman_clear_01")
    assert isinstance(entry, VoiceEntry)
    assert entry.capabilities.provider == "minimax"

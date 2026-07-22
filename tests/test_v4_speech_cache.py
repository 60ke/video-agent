from __future__ import annotations

from pathlib import Path
from typing import Any

import video_agent.speech.v4.tts as tts
from video_agent.contracts.v4 import ResolvedVoiceProfile
from video_agent.io import sha256_json, write_json_atomic
from video_agent.speech.minimax import MinimaxResult


def _voice() -> ResolvedVoiceProfile:
    return ResolvedVoiceProfile(
        schema_version=1,
        profile_id="minimax_adman_clear_01",
        profile_version="1",
        provider="minimax",
        provider_voice_ref="voice_x",
        voice_ref_fingerprint="b" * 64,
        language="zh-CN",
        speed=1.0,
        emotion=None,
        subtitle_type="default",
        resolve_mode="fixed",
        registry_snapshot_id="reg",
    )


def test_speech_cache_reuses_minimax_across_runs(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    case = tmp_path / "case"
    run1 = case / "runs" / "run_a"
    run2 = case / "runs" / "run_b"
    run1.mkdir(parents=True)
    run2.mkdir(parents=True)

    voice = _voice()
    text = "你好世界"
    narr_sha = sha256_json({"text": text})
    calls = {"n": 0}

    def fake_synthesize(*, repo_root: Path, text: str, voice_profile: ResolvedVoiceProfile, work_dir: Path) -> MinimaxResult:
        calls["n"] += 1
        work_dir.mkdir(parents=True, exist_ok=True)
        mp3 = work_dir / "voice.mp3"
        mp3.write_bytes(b"fake-mp3")
        align = work_dir / "minimax_alignment.json"
        tokens = [{"text": "你好", "start_ms": 0, "end_ms": 200}, {"text": "世界", "start_ms": 200, "end_ms": 400}]
        write_json_atomic(align, {"duration_ms": 400, "tokens": tokens})
        raw = work_dir / "minimax_response.json"
        write_json_atomic(raw, {"trace_id": "t1"})
        return MinimaxResult(mp3, align, raw, 400, tokens, "t1")

    def fake_mp3_to_wav(mp3_path: Path, wav_path: Path) -> None:
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path.write_bytes(b"RIFF")

    def fake_build_speech_timing_lock(**kwargs: Any) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "case_id": kwargs["case_id"],
            "run_id": kwargs["run_id"],
            "narration_sha256": kwargs["narration_sha256"],
            "fps": kwargs["fps"],
            "duration_ms": kwargs["duration_ms"],
            "tokens": kwargs["raw_tokens"],
        }

    monkeypatch.setattr(tts, "synthesize_plain_text", fake_synthesize)
    monkeypatch.setattr(tts, "_mp3_to_wav", fake_mp3_to_wav)
    monkeypatch.setattr(tts, "build_speech_timing_lock", fake_build_speech_timing_lock)
    monkeypatch.setattr(tts, "load_minimax_local_config", lambda _root: {"model": "speech-2.8-hd"})

    class _FakeClient:
        endpoint = "https://example.test"

        def __init__(self, _root: Path) -> None:
            pass

    monkeypatch.setattr(tts, "MinimaxClient", _FakeClient)

    first = tts.ensure_native_speech_timing_lock(
        case_id="c1",
        run_id="run_a",
        run_dir=run1,
        repo_root=repo,
        frozen_text=text,
        narration_sha256=narr_sha,
        voice_profile=voice,
        fps=30,
    )
    second = tts.ensure_native_speech_timing_lock(
        case_id="c1",
        run_id="run_b",
        run_dir=run2,
        repo_root=repo,
        frozen_text=text,
        narration_sha256=narr_sha,
        voice_profile=voice,
        fps=30,
    )
    assert first.is_file()
    assert second.is_file()
    assert calls["n"] == 1
    import json

    fp2 = json.loads((run2 / "speech_provider_fingerprint.json").read_text(encoding="utf-8"))
    assert fp2["speech_cache_reused"] is True

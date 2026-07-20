"""Native MiniMax TTS → SpeechTimingLock (no V3 TimingLock / Narration)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from video_agent.contracts.v4 import ResolvedVoiceProfile, SpeechTimingLock
from video_agent.io import sha256_json, write_json_atomic
from video_agent.speech.minimax import MinimaxClient, MinimaxResult, load_minimax_local_config, normalize_tokens
from video_agent.speech.v4.voice_resolve import resolve_provider_voice_value
from video_agent.timing.v4.speech_lock import build_speech_timing_lock


def _duration_ms(path: Path) -> int:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for voice audio: {proc.stderr[-1000:]}")
    return int(round(float(proc.stdout.strip()) * 1000))


def _mp3_to_wav(mp3_path: Path, wav_path: Path) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(mp3_path),
        "-ac",
        "1",
        "-ar",
        "32000",
        str(wav_path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mp3→wav failed: {proc.stderr[-1000:]}")


def synthesize_plain_text(
    *,
    repo_root: Path,
    text: str,
    voice_profile: ResolvedVoiceProfile,
    work_dir: Path,
) -> MinimaxResult:
    """One complete MiniMax TTS request for frozen narration text."""
    client = MinimaxClient(repo_root)
    local = load_minimax_local_config(repo_root)
    voice_id = resolve_provider_voice_value(voice_profile.provider_voice_ref, repo_root=repo_root)
    model = str(local.get("model") or "speech-2.8-hd").strip()
    payload = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": float(voice_profile.speed),
            "vol": float(local.get("vol", 1.0)),
            "pitch": int(local.get("pitch", 0)),
        },
        "audio_setting": {
            "sample_rate": int(local.get("sample_rate", 32000)),
            "bitrate": int(local.get("bitrate", 128000)),
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": True,
        "subtitle_type": "word",
    }
    if voice_profile.emotion:
        payload["voice_setting"]["emotion"] = voice_profile.emotion

    import httpx

    headers = {"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=180.0) as http:
        response = http.post(client.endpoint, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        base = body.get("base_resp", {})
        if base.get("status_code") not in (0, None):
            raise RuntimeError(f"Minimax API error: {base.get('status_msg')}")
        data = body.get("data") or {}
        audio_hex = data.get("audio")
        if not audio_hex:
            raise RuntimeError("Minimax returned no audio")
        subtitle_url = data.get("subtitle_file")
        if not subtitle_url:
            raise RuntimeError("Minimax returned no word subtitle file")
        subtitle_response = http.get(subtitle_url)
        subtitle_response.raise_for_status()
        raw_subtitles = subtitle_response.json()

    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / "voice.mp3"
    raw_path = work_dir / "minimax_response.json"
    alignment_path = work_dir / "minimax_alignment.json"
    audio_path.write_bytes(bytes.fromhex(audio_hex))
    tokens = normalize_tokens(raw_subtitles)
    duration_ms = _duration_ms(audio_path)
    write_json_atomic(
        raw_path,
        {
            "trace_id": body.get("trace_id"),
            "base_resp": body.get("base_resp"),
            "extra_info": body.get("extra_info"),
            "subtitle_file": subtitle_url,
            "request": {
                "model": payload["model"],
                "voice_setting": payload["voice_setting"],
                "text": text,
                "voice_profile_id": voice_profile.profile_id,
            },
            "subtitles": raw_subtitles,
        },
    )
    write_json_atomic(alignment_path, {"duration_ms": duration_ms, "tokens": tokens})
    return MinimaxResult(audio_path, alignment_path, raw_path, duration_ms, tokens, body.get("trace_id"))


def ensure_native_speech_timing_lock(
    *,
    case_id: str,
    run_id: str,
    run_dir: Path,
    repo_root: Path,
    frozen_text: str,
    narration_sha256: str,
    voice_profile: ResolvedVoiceProfile,
    fps: int = 30,
    output_path: Path | None = None,
) -> Path:
    """Run native TTS and write speech_timing_lock.json under the run directory."""
    speech_path = output_path or (run_dir / "speech_timing_lock.json")
    if speech_path.is_file():
        return speech_path

    work_dir = run_dir / "work" / "speech"
    result = synthesize_plain_text(
        repo_root=repo_root,
        text=frozen_text,
        voice_profile=voice_profile,
        work_dir=work_dir,
    )
    audio_object_key = "audio/speech.wav"
    audio_dest = run_dir / audio_object_key
    _mp3_to_wav(result.audio_path, audio_dest)

    speech = build_speech_timing_lock(
        case_id=case_id,
        run_id=run_id,
        narration_text=frozen_text,
        narration_sha256=narration_sha256.removeprefix("sha256:"),
        raw_tokens=result.tokens,
        audio_object_key=audio_object_key,
        audio_path=audio_dest,
        duration_ms=result.duration_ms,
        fps=fps,
        voice_profile=voice_profile,
    )
    # Keep provider fingerprint metadata beside the lock for Resume inputs.
    write_json_atomic(
        run_dir / "speech_provider_fingerprint.json",
        {
            "schema_version": "v4.speech_provider_fingerprint.1",
            "endpoint": MinimaxClient(repo_root).endpoint,
            "model": load_minimax_local_config(repo_root).get("model") or "speech-2.8-hd",
            "voice_profile_id": voice_profile.profile_id,
            "voice_profile_sha256": sha256_json(voice_profile.model_dump(mode="json")),
            "trace_id": result.trace_id,
        },
    )
    write_json_atomic(speech_path, speech)
    return speech_path


# Re-export for type checkers / callers that import SpeechTimingLock from this module.
_ = SpeechTimingLock

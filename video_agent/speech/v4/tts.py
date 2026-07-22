"""Native MiniMax TTS → SpeechTimingLock (no V3 TimingLock / Narration)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from video_agent.contracts.v4 import ResolvedVoiceProfile, SpeechTimingLock
from video_agent.io import load_json, sha256_json, utc_now, write_json_atomic
from video_agent.progress import get_logger
from video_agent.speech.minimax import MinimaxClient, MinimaxResult, load_minimax_local_config, normalize_tokens
from video_agent.speech.v4.voice_resolve import resolve_provider_voice_value
from video_agent.timing.v4.speech_lock import build_speech_timing_lock, voice_profile_content_sha256


logger = get_logger()


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


def speech_cache_enabled() -> bool:
    """Disable with VIDEO_AGENT_SPEECH_CACHE=0/false/off."""
    raw = str(os.environ.get("VIDEO_AGENT_SPEECH_CACHE", "1")).strip().lower()
    return raw not in {"0", "false", "off", "no"}


def speech_cache_key(
    *,
    narration_sha256: str,
    voice_profile: ResolvedVoiceProfile,
    model: str,
    fps: int,
) -> str:
    return sha256_json(
        {
            "narration_sha256": narration_sha256.removeprefix("sha256:"),
            "voice_profile_sha256": voice_profile_content_sha256(voice_profile),
            "model": model,
            "fps": int(fps),
        }
    )


def speech_cache_dir(repo_root: Path, cache_key: str) -> Path:
    return repo_root / "var" / "v4" / "speech_cache" / cache_key


def _cache_complete(cache_dir: Path) -> bool:
    return (
        (cache_dir / "meta.json").is_file()
        and (cache_dir / "speech.wav").is_file()
        and (cache_dir / "minimax_alignment.json").is_file()
    )


def _write_speech_cache(
    cache_dir: Path,
    *,
    narration_sha256: str,
    voice_profile: ResolvedVoiceProfile,
    model: str,
    fps: int,
    result: MinimaxResult,
    wav_path: Path,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wav_path, cache_dir / "speech.wav")
    if result.audio_path.is_file():
        shutil.copy2(result.audio_path, cache_dir / "voice.mp3")
    if result.alignment_path.is_file():
        shutil.copy2(result.alignment_path, cache_dir / "minimax_alignment.json")
    if result.raw_path.is_file():
        shutil.copy2(result.raw_path, cache_dir / "minimax_response.json")
    write_json_atomic(
        cache_dir / "meta.json",
        {
            "schema_version": "v4.speech_cache.1",
            "cache_key": cache_dir.name,
            "narration_sha256": narration_sha256.removeprefix("sha256:"),
            "voice_profile_id": voice_profile.profile_id,
            "voice_profile_sha256": voice_profile_content_sha256(voice_profile),
            "model": model,
            "fps": int(fps),
            "duration_ms": result.duration_ms,
            "trace_id": result.trace_id,
            "cached_at": utc_now(),
        },
    )


def _load_cached_alignment(cache_dir: Path) -> tuple[int, list[dict[str, Any]]]:
    payload = load_json(cache_dir / "minimax_alignment.json")
    tokens = list(payload.get("tokens") or [])
    duration_ms = int(payload.get("duration_ms") or 0)
    if not tokens or duration_ms <= 0:
        raise RuntimeError(f"invalid speech cache alignment: {cache_dir}")
    return duration_ms, tokens


def _iter_prior_run_dirs(run_dir: Path, repo_root: Path) -> list[Path]:
    """Prefer sibling runs in the same case, then other cases under cases/."""
    ordered: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.is_dir():
            return
        if resolved == run_dir.resolve():
            return
        seen.add(resolved)
        ordered.append(path)

    case_runs = run_dir.parent
    if case_runs.is_dir():
        for prior in sorted(case_runs.iterdir(), reverse=True):
            _add(prior)

    cases_root = repo_root / "cases"
    if cases_root.is_dir():
        # Newest runs first across cases (by run_id / directory mtime name sort).
        cross: list[Path] = []
        for case_dir in cases_root.iterdir():
            runs = case_dir / "runs"
            if not runs.is_dir():
                continue
            for prior in runs.iterdir():
                if prior.is_dir():
                    cross.append(prior)
        for prior in sorted(cross, key=lambda p: p.name, reverse=True):
            _add(prior)
    return ordered


def _try_promote_from_prior_runs(
    *,
    run_dir: Path,
    repo_root: Path,
    cache_dir: Path,
    narration_sha256: str,
    voice_profile: ResolvedVoiceProfile,
    model: str,
    fps: int,
) -> bool:
    """Seed content cache from an earlier run with the same narration+voice."""
    if _cache_complete(cache_dir):
        return True
    narr = narration_sha256.removeprefix("sha256:")
    voice_sha = voice_profile_content_sha256(voice_profile)
    for prior in _iter_prior_run_dirs(run_dir, repo_root):
        speech_path = prior / "speech_timing_lock.json"
        wav_path = prior / "audio" / "speech.wav"
        align_path = prior / "work" / "speech" / "minimax_alignment.json"
        if not (speech_path.is_file() and wav_path.is_file() and align_path.is_file()):
            continue
        speech = load_json(speech_path)
        if isinstance(speech, dict) and "payload" in speech:
            speech = speech["payload"]
        if str(speech.get("narration_sha256") or "") != narr:
            continue
        if int(speech.get("fps") or 0) != int(fps):
            continue
        fp_path = prior / "speech_provider_fingerprint.json"
        if fp_path.is_file():
            fp = load_json(fp_path)
            if fp.get("voice_profile_sha256") and fp.get("voice_profile_sha256") != voice_sha:
                continue
            if fp.get("model") and str(fp.get("model")) != model:
                continue
        cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wav_path, cache_dir / "speech.wav")
        shutil.copy2(align_path, cache_dir / "minimax_alignment.json")
        mp3 = prior / "work" / "speech" / "voice.mp3"
        raw = prior / "work" / "speech" / "minimax_response.json"
        if mp3.is_file():
            shutil.copy2(mp3, cache_dir / "voice.mp3")
        if raw.is_file():
            shutil.copy2(raw, cache_dir / "minimax_response.json")
        align = load_json(align_path)
        write_json_atomic(
            cache_dir / "meta.json",
            {
                "schema_version": "v4.speech_cache.1",
                "cache_key": cache_dir.name,
                "narration_sha256": narr,
                "voice_profile_id": voice_profile.profile_id,
                "voice_profile_sha256": voice_sha,
                "model": model,
                "fps": int(fps),
                "duration_ms": int(align.get("duration_ms") or speech.get("duration_ms") or 0),
                "trace_id": (load_json(fp_path).get("trace_id") if fp_path.is_file() else None),
                "cached_at": utc_now(),
                "promoted_from_run": f"{prior.parent.parent.name}/{prior.name}",
            },
        )
        logger.info(
            "[V4][speech] promoted cache from %s/%s key=%s",
            prior.parent.parent.name,
            prior.name,
            cache_dir.name[:12],
        )
        return _cache_complete(cache_dir)
    return False


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
    """Run native TTS and write speech_timing_lock.json under the run directory.

    When narration text + voice profile (+ model/fps) are unchanged, reuse the
    content-addressed MiniMax cache under ``var/v4/speech_cache/`` instead of
    calling the provider again. Disable with ``VIDEO_AGENT_SPEECH_CACHE=0``.
    """
    speech_path = output_path or (run_dir / "speech_timing_lock.json")
    if speech_path.is_file():
        return speech_path

    local = load_minimax_local_config(repo_root)
    model = str(local.get("model") or "speech-2.8-hd").strip()
    cache_key = speech_cache_key(
        narration_sha256=narration_sha256,
        voice_profile=voice_profile,
        model=model,
        fps=fps,
    )
    cache_dir = speech_cache_dir(repo_root, cache_key)
    work_dir = run_dir / "work" / "speech"
    work_dir.mkdir(parents=True, exist_ok=True)
    audio_object_key = "audio/speech.wav"
    audio_dest = run_dir / audio_object_key
    audio_dest.parent.mkdir(parents=True, exist_ok=True)

    reused = False
    trace_id: str | None = None
    duration_ms: int
    tokens: list[dict[str, Any]]

    if speech_cache_enabled() and not _cache_complete(cache_dir):
        _try_promote_from_prior_runs(
            run_dir=run_dir,
            repo_root=repo_root,
            cache_dir=cache_dir,
            narration_sha256=narration_sha256,
            voice_profile=voice_profile,
            model=model,
            fps=fps,
        )

    if speech_cache_enabled() and _cache_complete(cache_dir):
        duration_ms, tokens = _load_cached_alignment(cache_dir)
        shutil.copy2(cache_dir / "speech.wav", audio_dest)
        shutil.copy2(cache_dir / "minimax_alignment.json", work_dir / "minimax_alignment.json")
        if (cache_dir / "voice.mp3").is_file():
            shutil.copy2(cache_dir / "voice.mp3", work_dir / "voice.mp3")
        if (cache_dir / "minimax_response.json").is_file():
            shutil.copy2(cache_dir / "minimax_response.json", work_dir / "minimax_response.json")
        meta = load_json(cache_dir / "meta.json")
        trace_id = meta.get("trace_id")
        reused = True
        logger.info(
            "[V4][speech] reuse cache key=%s case=%s run=%s",
            cache_key[:12],
            case_id,
            run_id,
        )
    else:
        result = synthesize_plain_text(
            repo_root=repo_root,
            text=frozen_text,
            voice_profile=voice_profile,
            work_dir=work_dir,
        )
        _mp3_to_wav(result.audio_path, audio_dest)
        duration_ms = result.duration_ms
        tokens = list(result.tokens)
        trace_id = result.trace_id
        if speech_cache_enabled():
            _write_speech_cache(
                cache_dir,
                narration_sha256=narration_sha256,
                voice_profile=voice_profile,
                model=model,
                fps=fps,
                result=result,
                wav_path=audio_dest,
            )
            logger.info(
                "[V4][speech] wrote cache key=%s case=%s run=%s",
                cache_key[:12],
                case_id,
                run_id,
            )

    speech = build_speech_timing_lock(
        case_id=case_id,
        run_id=run_id,
        narration_text=frozen_text,
        narration_sha256=narration_sha256.removeprefix("sha256:"),
        raw_tokens=tokens,
        audio_object_key=audio_object_key,
        audio_path=audio_dest,
        duration_ms=duration_ms,
        fps=fps,
        voice_profile=voice_profile,
    )
    write_json_atomic(
        run_dir / "speech_provider_fingerprint.json",
        {
            "schema_version": "v4.speech_provider_fingerprint.1",
            "endpoint": MinimaxClient(repo_root).endpoint,
            "model": model,
            "voice_profile_id": voice_profile.profile_id,
            "voice_profile_sha256": voice_profile_content_sha256(voice_profile),
            "trace_id": trace_id,
            "speech_cache_key": cache_key,
            "speech_cache_reused": reused,
        },
    )
    write_json_atomic(speech_path, speech)
    return speech_path


# Re-export for type checkers / callers that import SpeechTimingLock from this module.
_ = SpeechTimingLock

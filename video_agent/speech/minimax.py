from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_agent.io import load_json


DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
LOCAL_CONFIG_NAME = "minimax.local.json"


def load_minimax_local_config(repo_root: Path) -> dict[str, Any]:
    config_path = repo_root / "config" / LOCAL_CONFIG_NAME
    return load_json(config_path) if config_path.is_file() else {}


def local_minimax_voice_id(repo_root: Path) -> str | None:
    voice_id = str(load_minimax_local_config(repo_root).get("voice_id") or "").strip()
    return voice_id or None


def apply_minimax_local_voice_defaults(case_data: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """Apply the machine-local MiniMax voice settings as runtime authority."""
    local = load_minimax_local_config(repo_root)
    configured = {
        key: local[key]
        for key in ("model", "voice_id", "speed", "emotion", "subtitle_type")
        if key in local and local[key] not in (None, "")
    }
    if not configured:
        return case_data
    patched = dict(case_data)
    voice = case_data.get("voice")
    patched_voice = dict(voice) if isinstance(voice, dict) else {}
    patched_voice.update(configured)
    patched["voice"] = patched_voice
    return patched


@dataclass(frozen=True)
class MinimaxResult:
    audio_path: Path
    alignment_path: Path
    raw_path: Path
    duration_ms: int
    tokens: list[dict[str, Any]]
    trace_id: str | None


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


def _items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        words: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("timestamped_words"), list):
                words.extend(word for word in item["timestamped_words"] if isinstance(word, dict))
            elif isinstance(item, dict):
                words.append(item)
        return words
    if isinstance(raw, dict):
        if isinstance(raw.get("timestamped_words"), list):
            return [item for item in raw["timestamped_words"] if isinstance(item, dict)]
        for key in ("subtitles", "segments", "words", "tokens", "data", "result"):
            found = _items(raw.get(key))
            if found:
                return found
    return []


def _value(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item:
            return item[key]
    return None


def normalize_tokens(raw: Any) -> list[dict[str, Any]]:
    items = _items(raw)
    observed = [
        float(value)
        for item in items
        for value in (_value(item, ("time_begin", "start_time", "start", "begin")), _value(item, ("time_end", "end_time", "end", "finish")))
        if value is not None
    ]
    divisor = 1000.0 if observed and max(observed) > 1000 else 1.0
    result: list[dict[str, Any]] = []
    seen_source_spans: set[tuple[str, int, int]] = set()
    for item in items:
        text = str(_value(item, ("text", "word", "token", "char")) or "")
        start = float(_value(item, ("time_begin", "start_time", "start", "begin")) or 0)
        end = float(_value(item, ("time_end", "end_time", "end", "finish")) or 0)
        start_ms = int(round(start / divisor * 1000))
        end_ms = int(round(end / divisor * 1000))
        if text and end_ms > start_ms:
            token = {"text": text, "start_ms": start_ms, "end_ms": end_ms}
            source_begin = _value(item, ("word_begin", "token_begin"))
            source_end = _value(item, ("word_end", "token_end"))
            source_span = (text, int(source_begin), int(source_end)) if source_begin is not None and source_end is not None else None
            if source_span and source_span in seen_source_spans:
                continue
            if source_span:
                seen_source_spans.add(source_span)
            result.append(token)
    return result


class MinimaxClient:
    """Shared MiniMax auth/endpoint shell. Plain-text TTS lives in speech.v4.tts."""

    def __init__(self, repo_root: Path) -> None:
        config = load_minimax_local_config(repo_root)
        self.api_key = str(os.getenv("MINIMAX_API_KEY") or config.get("api_key") or "").strip()
        self.endpoint = str(config.get("endpoint") or DEFAULT_ENDPOINT)
        self.defaults = config
        if not self.api_key:
            raise ValueError("Minimax API key missing in config/minimax.local.json or MINIMAX_API_KEY")

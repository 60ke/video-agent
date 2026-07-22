from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx

DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def probe_duration_ms(path: Path) -> int:
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
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-1000:]}")
    return round(float(result.stdout.strip()) * 1000)


def _items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        result: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("timestamped_words"), list):
                result.extend(value for value in item["timestamped_words"] if isinstance(value, dict))
            elif isinstance(item, dict):
                result.append(item)
        return result
    if isinstance(raw, dict):
        if isinstance(raw.get("timestamped_words"), list):
            return [value for value in raw["timestamped_words"] if isinstance(value, dict)]
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
        for value in (
            _value(item, ("time_begin", "start_time", "start", "begin")),
            _value(item, ("time_end", "end_time", "end", "finish")),
        )
        if value is not None
    ]
    divisor = 1000.0 if observed and max(observed) > 1000 else 1.0
    tokens: list[dict[str, Any]] = []
    seen_spans: set[tuple[str, int, int]] = set()
    for item in items:
        text = str(_value(item, ("text", "word", "token", "char")) or "")
        start = float(_value(item, ("time_begin", "start_time", "start", "begin")) or 0)
        end = float(_value(item, ("time_end", "end_time", "end", "finish")) or 0)
        start_ms = round(start / divisor * 1000)
        end_ms = round(end / divisor * 1000)
        source_begin = _value(item, ("word_begin", "token_begin"))
        source_end = _value(item, ("word_end", "token_end"))
        span = (text, int(source_begin), int(source_end)) if source_begin is not None and source_end is not None else None
        if not text or end_ms <= start_ms or (span and span in seen_spans):
            continue
        if span:
            seen_spans.add(span)
        tokens.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
    return tokens


def load_config(repo_root: Path, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {}
    local_path = repo_root / "config" / "minimax.local.json"
    if local_path.is_file():
        config.update(read_json(local_path))
    if overrides:
        config.update(overrides)
    config["api_key"] = str(os.getenv("MINIMAX_API_KEY") or config.get("api_key") or "").strip()
    return config


def synthesize(script: str, config: dict[str, Any], output_dir: Path) -> tuple[Path, list[dict[str, Any]], int]:
    api_key = str(config.get("api_key") or "").strip()
    voice_id = str(config.get("voice_id") or "").strip()
    if not api_key or not voice_id:
        raise ValueError("MiniMax requires api_key/MINIMAX_API_KEY and voice_id")

    payload: dict[str, Any] = {
        "model": str(config.get("model") or "speech-02-hd"),
        "text": script,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": float(config.get("speed", 1.0)),
            "vol": float(config.get("vol", 1.0)),
            "pitch": int(config.get("pitch", 0)),
        },
        "audio_setting": {
            "sample_rate": int(config.get("sample_rate", 32000)),
            "bitrate": int(config.get("bitrate", 128000)),
            "format": "mp3",
            "channel": 1,
        },
        "subtitle_enable": True,
        "subtitle_type": "word",
    }
    emotion = str(config.get("emotion") or "").strip()
    if emotion:
        payload["voice_setting"]["emotion"] = emotion

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    endpoint = str(config.get("endpoint") or DEFAULT_ENDPOINT)
    with httpx.Client(timeout=180.0) as client:
        response = client.post(endpoint, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()
        base = body.get("base_resp") or {}
        if base.get("status_code") not in (0, None):
            raise RuntimeError(f"MiniMax API error: {base.get('status_msg')}")
        data = body.get("data") or {}
        audio_hex = data.get("audio")
        subtitle_url = data.get("subtitle_file")
        if not audio_hex or not subtitle_url:
            raise RuntimeError("MiniMax did not return audio and word subtitles")
        subtitle_response = client.get(subtitle_url)
        subtitle_response.raise_for_status()
        raw_subtitles = subtitle_response.json()

    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / "voice.mp3"
    audio_path.write_bytes(bytes.fromhex(audio_hex))
    tokens = normalize_tokens(raw_subtitles)
    if not tokens:
        raise RuntimeError("MiniMax returned no valid word timing tokens")
    duration_ms = probe_duration_ms(audio_path)
    write_json(
        output_dir / "minimax_response.json",
        {
            "trace_id": body.get("trace_id"),
            "request": {"model": payload["model"], "voice_setting": payload["voice_setting"], "text": script},
            "subtitle_file": subtitle_url,
            "subtitles": raw_subtitles,
        },
    )
    return audio_path, tokens, duration_ms

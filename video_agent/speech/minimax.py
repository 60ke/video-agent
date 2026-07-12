from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from video_agent.contracts import CaseConfig, Narration
from video_agent.io import load_json, write_json_atomic
from video_agent.speech.pause_compiler import compile_narration_markup


DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"


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
    for item in items:
        text = str(_value(item, ("text", "word", "token", "char")) or "")
        start = float(_value(item, ("time_begin", "start_time", "start", "begin")) or 0)
        end = float(_value(item, ("time_end", "end_time", "end", "finish")) or 0)
        start_ms = int(round(start / divisor * 1000))
        end_ms = int(round(end / divisor * 1000))
        if text and end_ms > start_ms:
            result.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
    return result


class MinimaxClient:
    def __init__(self, repo_root: Path) -> None:
        config_path = repo_root / "config" / "minimax.local.json"
        config = load_json(config_path) if config_path.is_file() else {}
        self.api_key = str(os.getenv("MINIMAX_API_KEY") or config.get("api_key") or "").strip()
        self.endpoint = str(config.get("endpoint") or DEFAULT_ENDPOINT)
        self.defaults = config
        if not self.api_key:
            raise ValueError("Minimax API key missing in config/minimax.local.json or MINIMAX_API_KEY")

    def synthesize(self, case: CaseConfig, narration: Narration, work_dir: Path) -> MinimaxResult:
        markup_text = compile_narration_markup(narration)
        payload: dict[str, Any] = {
            "model": case.voice.model,
            "text": markup_text,
            "stream": False,
            "voice_setting": {
                "voice_id": case.voice.voice_id,
                "speed": case.voice.speed,
                "vol": float(self.defaults.get("vol", 1.0)),
                "pitch": int(self.defaults.get("pitch", 0)),
            },
            "audio_setting": {
                "sample_rate": int(self.defaults.get("sample_rate", 32000)),
                "bitrate": int(self.defaults.get("bitrate", 128000)),
                "format": "mp3",
                "channel": 1,
            },
            "subtitle_enable": True,
            "subtitle_type": "word",
        }
        if case.voice.emotion:
            payload["voice_setting"]["emotion"] = case.voice.emotion
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=180.0) as client:
            response = client.post(self.endpoint, headers=headers, json=payload)
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
            subtitle_response = client.get(subtitle_url)
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
                "request": {"model": payload["model"], "voice_setting": payload["voice_setting"], "text": markup_text},
                "subtitles": raw_subtitles,
            },
        )
        write_json_atomic(alignment_path, {"duration_ms": duration_ms, "tokens": tokens})
        return MinimaxResult(audio_path, alignment_path, raw_path, duration_ms, tokens, body.get("trace_id"))

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "speech-2.8-turbo"
DEFAULT_VOICE_ID = "male-qn-qingse"
DEFAULT_SPEED = 1.5
DEFAULT_ENDPOINT = "https://api.minimaxi.com/v1/t2a_v2"
DEFAULT_SUBTITLE_TYPE = "word"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_local_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    local_path = repo_root() / "config" / "minimax.local.json"
    if local_path.is_file():
        config.update(load_json(local_path))
    env_key = os.getenv("MINIMAX_API_KEY", "").strip()
    if env_key:
        config["api_key"] = env_key
    config.setdefault("model", DEFAULT_MODEL)
    config.setdefault("voice_id", DEFAULT_VOICE_ID)
    config.setdefault("speed", DEFAULT_SPEED)
    config.setdefault("endpoint", DEFAULT_ENDPOINT)
    config.setdefault("subtitle_type", DEFAULT_SUBTITLE_TYPE)
    if not str(config.get("api_key", "")).strip():
        raise ValueError("Minimax API key missing. Set MINIMAX_API_KEY or config/minimax.local.json.")
    return config


def read_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()

    case_dir = Path(args.case)
    voice_plan = case_dir / "voice_plan.json"
    if voice_plan.is_file():
        data = load_json(voice_plan)
        text = data.get("text") or data.get("source_text")
        if text:
            return str(text).strip()

    video_script = case_dir / "video_script.json"
    if video_script.is_file():
        data = load_json(video_script)
        segments = data.get("segments", [])
        if isinstance(segments, list) and segments:
            text = " ".join(str(seg.get("text", "")).strip() for seg in segments if isinstance(seg, dict) and seg.get("text"))
            if text.strip():
                return text.strip()

    raise ValueError("voice text is required: pass --text, --text-file, or provide video_script.json")


def media_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def _iter_subtitle_items(raw: Any, *, prefer_words: bool = True) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        dict_items = [item for item in raw if isinstance(item, dict)]
        if prefer_words:
            word_items: list[dict[str, Any]] = []
            for item in dict_items:
                words = item.get("timestamped_words")
                if isinstance(words, list):
                    word_items.extend(word for word in words if isinstance(word, dict))
            if word_items:
                return word_items
        return dict_items
    if isinstance(raw, dict):
        if prefer_words and isinstance(raw.get("timestamped_words"), list):
            return [item for item in raw["timestamped_words"] if isinstance(item, dict)]
        for key in ("subtitles", "segments", "words", "tokens", "data", "result"):
            value = raw.get(key)
            items = _iter_subtitle_items(value, prefer_words=prefer_words)
            if items:
                return items
    return []


def _time_value(item: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in item:
            try:
                return float(item.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _text_value(item: dict[str, Any]) -> str:
    for key in ("text", "word", "token", "char"):
        value = item.get(key)
        if value:
            return str(value).strip()
    return ""


def normalize_minimax_subtitles(raw: Any) -> list[dict[str, Any]]:
    items = _iter_subtitle_items(raw)

    segments: list[dict[str, Any]] = []
    for item in items:
        start_ms = _time_value(item, "time_begin", "start_time", "start", "begin")
        end_ms = _time_value(item, "time_end", "end_time", "end", "finish")
        divisor = 1000.0 if max(float(start_ms or 0), float(end_ms or 0)) > 100 else 1.0
        text = _text_value(item)
        if not text:
            continue
        start = float(start_ms or 0) / divisor
        end = float(end_ms or 0) / divisor
        if end <= start:
            continue
        segments.append({"text": text, "start": round(start, 3), "end": round(end, 3)})
    return segments


def sanitize_subtitle_segments(
    segments: list[dict[str, Any]],
    *,
    max_duration: float | None = None,
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for segment in segments:
        text = "".join(str(segment.get("text", "")).split())
        if not text:
            continue
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))
        if end <= start:
            continue
        if max_duration is not None and start >= max_duration:
            continue
        if max_duration is not None and end > max_duration + 0.05:
            end = max_duration
        per_char = (end - start) / max(len(text), 1)
        if per_char > 1.5:
            continue
        cleaned.append({"text": text, "start": round(start, 3), "end": round(end, 3)})
    cleaned.sort(key=lambda item: (item["start"], item["end"], item["text"]))
    return cleaned


def fetch_subtitles(url: str | None) -> tuple[Any, list[dict[str, Any]]]:
    if not url:
        return [], []
    with urllib.request.urlopen(url) as response:
        raw = json.loads(response.read().decode("utf-8"))
    return raw, normalize_minimax_subtitles(raw)


def call_minimax_api(text: str, output_audio: Path, output_alignment: Path, raw_subtitle_path: Path) -> dict[str, Any]:
    config = load_local_config()
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.get("model", DEFAULT_MODEL),
        "text": text,
        "voice_setting": {
            "voice_id": config.get("voice_id", DEFAULT_VOICE_ID),
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
        "subtitle_type": str(config.get("subtitle_type", DEFAULT_SUBTITLE_TYPE)),
    }
    language_boost = config.get("language_boost")
    if language_boost:
        payload["language_boost"] = language_boost
    emotion = config.get("emotion")
    if emotion:
        payload["voice_setting"]["emotion"] = emotion

    req = urllib.request.Request(
        str(config.get("endpoint", DEFAULT_ENDPOINT)),
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    with urllib.request.urlopen(req) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    base_resp = response_data.get("base_resp", {})
    if base_resp.get("status_code") != 0:
        raise RuntimeError(f"Minimax API error: {base_resp.get('status_msg')}")

    data = response_data.get("data", {})
    audio_hex = data.get("audio")
    if not audio_hex:
        raise RuntimeError("Minimax API returned no audio data")

    output_audio.parent.mkdir(parents=True, exist_ok=True)
    output_audio.write_bytes(bytes.fromhex(audio_hex))

    raw_subtitles, segments = fetch_subtitles(data.get("subtitle_file"))
    probed_duration = media_duration(output_audio)
    segments = sanitize_subtitle_segments(segments, max_duration=probed_duration)
    if probed_duration:
        duration = probed_duration
    else:
        duration = max((float(seg["end"]) for seg in segments), default=0.0)

    write_json(
        raw_subtitle_path,
        {
            "schema_version": 1,
            "provider": "minimax",
            "subtitle_type": payload["subtitle_type"],
            "subtitle_file": data.get("subtitle_file"),
            "trace_id": response_data.get("trace_id"),
            "base_resp": response_data.get("base_resp", {}),
            "extra_info": response_data.get("extra_info", {}),
            "normalized_segments": segments,
            "raw": raw_subtitles,
        },
    )

    alignment = {
        "schema_version": 1,
        "provider": "minimax",
        "engine": "minimax_t2a",
        "duration": round(duration, 3),
        "subtitle_type": payload["subtitle_type"],
        "segments": segments,
    }
    write_json(output_alignment, alignment)

    return {
        "audio_path": str(output_audio),
        "alignment_path": str(output_alignment),
        "duration": round(duration, 3),
        "subtitle_count": len(segments),
        "model": payload["model"],
        "voice_id": payload["voice_setting"]["voice_id"],
        "subtitle_type": payload["subtitle_type"],
        "speed": payload["voice_setting"]["speed"],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")

    text = read_text(args)
    output_audio = case_dir / "audio" / "voice.mp3"
    output_dir = case_dir / "output" / "minimax"
    output_alignment = output_dir / "minimax_alignment.json"
    raw_subtitle_path = output_dir / "minimax_subtitles_raw.json"

    result = call_minimax_api(text, output_audio, output_alignment, raw_subtitle_path)

    report = {
        "schema_version": 1,
        "engine": "minimax_t2a",
        "text": text,
        "audio_path": result["audio_path"],
        "alignment_path": result["alignment_path"],
        "duration": result["duration"],
        "model": result["model"],
        "voice_id": result["voice_id"],
        "subtitle_type": result["subtitle_type"],
        "speed": result.get("speed"),
        "chars": len(text),
        "chars_per_second": round(len(text) / result["duration"], 3) if result["duration"] > 0 else None,
    }
    report_path = output_dir / "voice_report.json"
    write_json(report_path, report)

    return {"ok": True, "code": "ok", "reason": "", "data": report}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate voice and native subtitle timing using Minimax T2A.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}

    if args.json:
        sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    elif output["ok"]:
        print(f"Generated voice: {output['data']['audio_path']}")
        print(f"Generated alignment: {output['data']['alignment_path']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

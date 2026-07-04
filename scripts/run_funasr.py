from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def ffprobe_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nk=1:nw=1",
        str(path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def _seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 1000:
        return round(number / 1000, 3)
    return round(number, 3)


def normalize_segments(raw_result: Any, duration: float | None) -> list[dict[str, Any]]:
    results = raw_result if isinstance(raw_result, list) else [raw_result]
    segments: list[dict[str, Any]] = []

    for item in results:
        if not isinstance(item, dict):
            continue

        sentence_info = item.get("sentence_info")
        if isinstance(sentence_info, list):
            for sentence in sentence_info:
                if not isinstance(sentence, dict):
                    continue
                text = clean_asr_text(str(sentence.get("text") or ""))
                start = _seconds(sentence.get("start"))
                end = _seconds(sentence.get("end"))
                if text and start is not None and end is not None and end > start:
                    segments.append(
                        {
                            "id": f"asr_{len(segments) + 1:03d}",
                            "text": text,
                            "start": start,
                            "end": end,
                        }
                    )

        if segments:
            continue

        text = clean_asr_text(str(item.get("text") or ""))
        if text:
            segments.append(
                {
                    "id": f"asr_{len(segments) + 1:03d}",
                    "text": text,
                    "start": 0.0,
                    "end": round(duration or 0.0, 3),
                }
            )

    return segments


def clean_asr_text(text: str) -> str:
    return re.sub(r"<\|[^<>\s]*\|>?", "", text).strip()


def run_model(audio_path: Path, model_name: str, language: str) -> Any:
    try:
        from funasr import AutoModel
    except ImportError as exc:
        raise ImportError("FunASR is not importable. Install and verify FunASR before running ASR.") from exc

    model = AutoModel(
        model=model_name,
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
    )
    return model.generate(
        input=str(audio_path),
        cache={},
        language=language,
        use_itn=True,
        batch_size_s=60,
        merge_vad=True,
        merge_length_s=8,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    audio_path = Path(args.audio).expanduser().resolve(strict=False) if args.audio else case_dir / "audio" / "voice.wav"
    if not audio_path.is_file():
        raise FileNotFoundError(f"audio file not found: {audio_path}")

    output_dir = case_dir / "output" / "funasr"
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "voice_raw.json"
    alignment_path = output_dir / "funasr_alignment.json"

    duration = ffprobe_duration(audio_path)
    log_buffer = io.StringIO()
    with contextlib.redirect_stdout(log_buffer), contextlib.redirect_stderr(log_buffer):
        raw_result = run_model(audio_path, args.model, args.language)
    log_path = output_dir / "funasr_log.txt"
    log_path.write_text(log_buffer.getvalue(), encoding="utf-8")
    raw_path.write_text(json.dumps(raw_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    segments = normalize_segments(raw_result, duration)
    alignment = {
        "schema_version": 1,
        "engine": "funasr",
        "model": args.model,
        "audio_path": str(audio_path),
        "duration": duration,
        "segments": segments,
    }
    alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "audio_path": str(audio_path),
            "raw_path": str(raw_path),
            "alignment_path": str(alignment_path),
            "log_path": str(log_path),
            "segment_count": len(segments),
            "duration": duration,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run FunASR on case voice audio.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--audio")
    parser.add_argument("--model", default="iic/SenseVoiceSmall")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {},
        }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"FunASR alignment: {output['data']['alignment_path']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


MIN_SPEECH_UNITS_PER_SECOND = 6.0


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def silence_events(path: Path, threshold: str, min_duration: float) -> list[dict[str, float]]:
    cmd = [
        "ffmpeg",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={threshold}:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    text = proc.stderr
    def safe_float(value: str) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    starts = [value for value in (safe_float(v) for v in re.findall(r"silence_start: ([0-9.]+)", text)) if value is not None]
    ends = [
        (end, duration)
        for end, duration in (
            (safe_float(a), safe_float(b))
            for a, b in re.findall(r"silence_end: ([0-9.]+) \\| silence_duration: ([0-9.]+)", text)
        )
        if end is not None and duration is not None
    ]
    events: list[dict[str, float]] = []
    for idx, start in enumerate(starts):
        end, duration = ends[idx] if idx < len(ends) else (start, 0.0)
        events.append({"start": start, "end": end, "duration": duration})
    return events


def normalized_text(value: str) -> str:
    value = re.sub(r"<\|[^<>\s]*\|>?", "", value)
    return re.sub(r"\s+", "", value).lower()


def extract_script_text(case_dir: Path, args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.text_file:
        return Path(args.text_file).read_text(encoding="utf-8").strip()
    voice_plan = load_json(case_dir / "voice_plan.json")
    if voice_plan.get("text"):
        return str(voice_plan["text"]).strip()
    report = load_json(case_dir / "output" / "minimax" / "voice_report.json")
    if report.get("text"):
        return str(report["text"]).strip()
    return ""


def extract_asr_text(alignment: dict[str, Any]) -> str:
    segments = alignment.get("segments", [])
    if not isinstance(segments, list):
        return ""
    text = "".join(str(seg.get("text", "")) for seg in segments if isinstance(seg, dict))
    return re.sub(r"<\|[^<>\s]*\|>?", "", text).strip()


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    audio_path = Path(args.audio).expanduser().resolve(strict=False) if args.audio else case_dir / "audio" / "voice.mp3"
    alignment_path = Path(args.alignment).expanduser().resolve(strict=False) if args.alignment else case_dir / "output" / "minimax" / "minimax_alignment.json"

    errors: list[str] = []
    warnings: list[str] = []

    if not audio_path.is_file():
        errors.append(f"voice audio missing: {audio_path}")
        duration = None
    else:
        duration = ffprobe_duration(audio_path)
        if duration is None:
            errors.append(f"voice audio is not probeable: {audio_path}")

    alignment = load_json(alignment_path)
    if not alignment:
        errors.append(f"Minimax alignment missing: {alignment_path}")

    script_text = extract_script_text(case_dir, args)
    asr_text = extract_asr_text(alignment)
    chars = len(normalized_text(script_text))
    cps = round(chars / duration, 3) if duration and chars else None

    if cps is not None:
        if cps < MIN_SPEECH_UNITS_PER_SECOND:
            errors.append(f"speech density below minimum policy: {cps} chars/sec")

    high_risk_terms = list(args.high_risk_term or [])
    voice_plan = load_json(case_dir / "voice_plan.json")
    for term in voice_plan.get("high_risk_terms", []) if isinstance(voice_plan.get("high_risk_terms"), list) else []:
        if term not in high_risk_terms:
            high_risk_terms.append(str(term))

    normalized_asr = normalized_text(asr_text)
    missing_terms: list[str] = []
    for term in high_risk_terms:
        normalized_term = normalized_text(term)
        if normalized_term and normalized_term not in normalized_asr:
            missing_terms.append(term)

    if missing_terms:
        errors.append(f"ASR did not recognize high-risk terms: {', '.join(missing_terms)}")

    silence = []
    if audio_path.is_file():
        silence = silence_events(audio_path, args.silence_noise, args.max_internal_silence)
        internal = [
            item
            for item in silence
            if duration is not None and item["start"] > 0.05 and item["end"] < max(duration - 0.05, 0)
        ]
        if len(internal) > args.max_silence_events:
            warnings.append(f"too many internal silence events: {len(internal)}")

    ok = not errors
    report = {
        "schema_version": 1,
        "status": "passed" if ok else "failed",
        "audio_path": str(audio_path),
        "alignment_path": str(alignment_path),
        "duration": duration,
        "script_text": script_text,
        "asr_text": asr_text,
        "chars": chars,
        "chars_per_second": cps,
        "minimum_units_per_second": MIN_SPEECH_UNITS_PER_SECOND,
        "high_risk_terms": high_risk_terms,
        "missing_terms": missing_terms,
        "silence_events": silence,
        "errors": errors,
        "warnings": warnings,
    }
    report_path = case_dir / "output" / "reports" / "voice_qa_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": ok,
        "code": "ok" if ok else "voice_qa_failed",
        "reason": "" if ok else f"{len(errors)} voice QA error(s)",
        "data": report | {"report_path": str(report_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check voice timing, ASR, risk terms, and silence.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--audio")
    parser.add_argument("--alignment")
    parser.add_argument("--text")
    parser.add_argument("--text-file")
    parser.add_argument("--high-risk-term", action="append", default=[])
    parser.add_argument("--silence-noise", default="-35dB")
    parser.add_argument("--max-internal-silence", type=float, default=0.12)
    parser.add_argument("--max-silence-events", type=int, default=2)
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
        print("Voice QA passed")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

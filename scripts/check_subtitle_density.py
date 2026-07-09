from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DEFAULT_SOFT_TOTAL_SECONDS = 20.0
DEFAULT_HARD_TOTAL_SECONDS = 24.0
DEFAULT_SOFT_CHARS_PER_SEGMENT = 16
DEFAULT_HARD_CHARS_PER_SEGMENT = 22
DEFAULT_SOFT_SEGMENT_SECONDS = 2.4
DEFAULT_HARD_SEGMENT_SECONDS = 3.0
DEFAULT_MIN_SEGMENT_SECONDS = 1.1
DEFAULT_MAX_CHARS_PER_SECOND = 8.5


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compact_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text)))


def load_segments(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, dict):
        if isinstance(payload.get("segments"), list):
            return [seg for seg in payload["segments"] if isinstance(seg, dict)]
        track = payload.get("subtitle_track")
        if isinstance(track, dict) and isinstance(track.get("segments"), list):
            return [seg for seg in track["segments"] if isinstance(seg, dict)]
        if isinstance(track, list):
            return [seg for seg in track if isinstance(seg, dict)]
    if isinstance(payload, list):
        return [seg for seg in payload if isinstance(seg, dict)]
    raise ValueError(f"Cannot find subtitle segments in {path}")


def classify(issue_level: str, message: str, segment: dict[str, Any] | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"level": issue_level, "message": message}
    if segment:
        item["id"] = segment.get("id")
        item["text"] = segment.get("text")
        item["start"] = segment.get("start")
        item["end"] = segment.get("end")
    return item


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    path = Path(args.subtitle).expanduser().resolve(strict=False)
    segments = load_segments(path)
    issues: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    valid = [seg for seg in segments if isinstance(seg.get("start"), (int, float)) and isinstance(seg.get("end"), (int, float)) and float(seg["end"]) > float(seg["start"])]
    if not valid:
        raise ValueError("subtitle file has no timed segments")
    total_duration = max(float(seg["end"]) for seg in valid) - min(float(seg["start"]) for seg in valid)
    total_chars = sum(compact_chars(str(seg.get("text") or "")) for seg in valid)
    avg_chars_per_second = total_chars / max(total_duration, 0.001)

    if total_duration > args.hard_total_seconds:
        issues.append(classify("error", f"total duration {total_duration:.2f}s exceeds hard limit {args.hard_total_seconds:.2f}s; feature-seeding videos should normally compress to 15-20s"))
    elif total_duration > args.soft_total_seconds:
        issues.append(classify("warning", f"total duration {total_duration:.2f}s exceeds preferred limit {args.soft_total_seconds:.2f}s; tighten copy or reduce beats"))

    for seg in valid:
        text = str(seg.get("text") or "")
        chars = compact_chars(text)
        duration = float(seg["end"]) - float(seg["start"])
        cps = chars / max(duration, 0.001)
        row = {
            "id": seg.get("id"),
            "start": round(float(seg["start"]), 3),
            "end": round(float(seg["end"]), 3),
            "duration": round(duration, 3),
            "chars": chars,
            "chars_per_second": round(cps, 3),
            "text": text,
        }
        rows.append(row)
        if chars > args.hard_chars_per_segment:
            issues.append(classify("error", f"{seg.get('id')} has {chars} chars; hard limit is {args.hard_chars_per_segment}. Use one conclusion plus one keyword, not a full sentence chain.", seg))
        elif chars > args.soft_chars_per_segment:
            issues.append(classify("warning", f"{seg.get('id')} has {chars} chars; preferred limit is {args.soft_chars_per_segment}. Consider 10-14 oral chars.", seg))
        if duration > args.hard_segment_seconds:
            issues.append(classify("error", f"{seg.get('id')} lasts {duration:.2f}s; hard per-image duration is {args.hard_segment_seconds:.2f}s.", seg))
        elif duration > args.soft_segment_seconds:
            issues.append(classify("warning", f"{seg.get('id')} lasts {duration:.2f}s; preferred per-image duration is {args.soft_segment_seconds:.2f}s.", seg))
        if duration < args.min_segment_seconds:
            issues.append(classify("warning", f"{seg.get('id')} lasts only {duration:.2f}s; may be too fast for a visual beat.", seg))
        if cps > args.max_chars_per_second:
            issues.append(classify("warning", f"{seg.get('id')} is {cps:.2f} chars/s; TTS may sound rushed.", seg))

    error_count = sum(1 for item in issues if item["level"] == "error")
    warning_count = sum(1 for item in issues if item["level"] == "warning")
    return {
        "schema_version": 1,
        "ok": error_count == 0,
        "subtitle": str(path),
        "summary": {
            "segment_count": len(valid),
            "total_duration": round(total_duration, 3),
            "total_chars": total_chars,
            "avg_chars_per_second": round(avg_chars_per_second, 3),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "limits": {
            "soft_total_seconds": args.soft_total_seconds,
            "hard_total_seconds": args.hard_total_seconds,
            "soft_chars_per_segment": args.soft_chars_per_segment,
            "hard_chars_per_segment": args.hard_chars_per_segment,
            "soft_segment_seconds": args.soft_segment_seconds,
            "hard_segment_seconds": args.hard_segment_seconds,
            "min_segment_seconds": args.min_segment_seconds,
            "max_chars_per_second": args.max_chars_per_second,
        },
        "segments": rows,
        "issues": issues,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    report = analyze(args)
    if args.report:
        write_json(Path(args.report).expanduser().resolve(strict=False), report)
    return {"ok": bool(report["ok"]), "code": "ok" if report["ok"] else "density_check_failed", "reason": "" if report["ok"] else "subtitle density constraints failed", "data": report}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check subtitle/copy density for short product demo videos.")
    parser.add_argument("--subtitle", required=True, help="subtitle_track.json or a video_project JSON containing subtitle_track.segments")
    parser.add_argument("--report", help="Optional output report JSON")
    parser.add_argument("--soft-total-seconds", type=float, default=DEFAULT_SOFT_TOTAL_SECONDS)
    parser.add_argument("--hard-total-seconds", type=float, default=DEFAULT_HARD_TOTAL_SECONDS)
    parser.add_argument("--soft-chars-per-segment", type=int, default=DEFAULT_SOFT_CHARS_PER_SEGMENT)
    parser.add_argument("--hard-chars-per-segment", type=int, default=DEFAULT_HARD_CHARS_PER_SEGMENT)
    parser.add_argument("--soft-segment-seconds", type=float, default=DEFAULT_SOFT_SEGMENT_SECONDS)
    parser.add_argument("--hard-segment-seconds", type=float, default=DEFAULT_HARD_SEGMENT_SECONDS)
    parser.add_argument("--min-segment-seconds", type=float, default=DEFAULT_MIN_SEGMENT_SECONDS)
    parser.add_argument("--max-chars-per-second", type=float, default=DEFAULT_MAX_CHARS_PER_SECOND)
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
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        data = output["data"]["summary"]
        print(f"Subtitle density ok: {data['segment_count']} segments, {data['total_duration']}s, {data['total_chars']} chars")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

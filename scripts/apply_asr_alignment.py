from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def text_weight(text: str) -> int:
    stripped = "".join(str(text).split())
    return max(len(stripped), 1)


def load_script_segments(case_dir: Path) -> list[dict[str, Any]]:
    data = load_json(case_dir / "video_script.json")
    segments = data.get("segments", [])
    if not isinstance(segments, list) or not segments:
        raise ValueError("video_script.json must contain non-empty segments")
    normalized: list[dict[str, Any]] = []
    for idx, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"video_script.segments[{idx}] must be an object")
        text = str(segment.get("text") or "").strip()
        if not text:
            raise ValueError(f"video_script.segments[{idx}] missing text")
        normalized.append(
            {
                "id": segment.get("id") or f"seg_{idx + 1:03d}",
                "text": text,
                "stage": segment.get("stage"),
                "visual_intent": segment.get("visual_intent"),
                "duration_hint": segment.get("duration_hint"),
            }
        )
    return normalized


def alignment_bounds(alignment: dict[str, Any]) -> tuple[float, float]:
    segments = alignment.get("segments", [])
    if not isinstance(segments, list) or not segments:
        duration = alignment.get("duration")
        if isinstance(duration, (int, float)) and duration > 0:
            return 0.0, float(duration)
        raise ValueError("alignment has no segments or duration")

    starts = [float(seg.get("start", 0)) for seg in segments if isinstance(seg, dict)]
    ends = [float(seg.get("end", 0)) for seg in segments if isinstance(seg, dict)]
    if not starts or not ends or max(ends) <= min(starts):
        raise ValueError("alignment has invalid start/end values")
    return min(starts), max(ends)


def allocate_subtitles(script_segments: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    total_duration = end - start
    weights = [text_weight(seg["text"]) for seg in script_segments]
    total_weight = sum(weights)
    cursor = start
    subtitles: list[dict[str, Any]] = []

    for idx, (segment, weight) in enumerate(zip(script_segments, weights)):
        if idx == len(script_segments) - 1:
            seg_end = end
        else:
            seg_duration = total_duration * weight / total_weight
            seg_end = cursor + seg_duration
        subtitles.append(
            {
                "id": f"sub_{idx + 1:03d}",
                "script_segment_id": segment["id"],
                "text": segment["text"],
                "start": round(cursor, 3),
                "end": round(seg_end, 3),
            }
        )
        cursor = seg_end

    return subtitles


def normalized_chars(text: str) -> str:
    return "".join(str(text).split())


def build_char_timeline(alignment_segments: list[dict[str, Any]]) -> tuple[str, list[float], list[float]]:
    chars: list[str] = []
    starts: list[float] = []
    ends: list[float] = []
    for segment in alignment_segments:
        text = normalized_chars(str(segment.get("text", "")))
        if not text:
            continue
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))
        duration = max(end - start, 0.001)
        count = len(text)
        for idx, char in enumerate(text):
            chars.append(char)
            starts.append(start + duration * idx / count)
            ends.append(start + duration * (idx + 1) / count)
    return "".join(chars), starts, ends


def allocate_from_alignment_text(script_segments: list[dict[str, Any]], alignment: dict[str, Any]) -> list[dict[str, Any]] | None:
    alignment_segments = alignment.get("segments", [])
    if not isinstance(alignment_segments, list) or not alignment_segments:
        return None

    combined, starts, ends = build_char_timeline([seg for seg in alignment_segments if isinstance(seg, dict)])
    if not combined or len(starts) != len(combined) or len(ends) != len(combined):
        return None

    subtitles: list[dict[str, Any]] = []
    search_from = 0
    for idx, segment in enumerate(script_segments):
        needle = normalized_chars(segment["text"])
        if not needle:
            return None
        found = combined.find(needle, search_from)
        if found < 0:
            return None
        end_index = found + len(needle)
        subtitles.append(
            {
                "id": f"sub_{idx + 1:03d}",
                "script_segment_id": segment["id"],
                "text": segment["text"],
                "start": round(starts[found], 3),
                "end": round(ends[min(end_index - 1, len(ends) - 1)], 3),
            }
        )
        search_from = end_index
    return subtitles


def update_project(case_dir: Path, script_segments: list[dict[str, Any]], subtitle_track: dict[str, Any]) -> None:
    project_path = case_dir / "video_project.json"
    project = load_json(project_path)
    project["schema_version"] = project.get("schema_version", 1)
    project["status"] = "subtitle_aligned"
    project["script_segments"] = [
        {
            "id": seg["id"],
            "stage": seg.get("stage"),
            "text": seg["text"],
            "visual_intent": seg.get("visual_intent"),
            "duration_hint": seg.get("duration_hint"),
        }
        for seg in script_segments
    ]
    project["subtitle_track"] = subtitle_track
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    alignment_path = Path(args.alignment).expanduser().resolve(strict=False) if args.alignment else case_dir / "output" / "minimax" / "minimax_alignment.json"
    alignment = load_json(alignment_path)
    script_segments = load_script_segments(case_dir)
    start, end = alignment_bounds(alignment)
    subtitles = allocate_from_alignment_text(script_segments, alignment)
    allocation_format = "minimax_text_matched_reviewed_text"
    warnings: list[str] = []
    if subtitles is None:
        subtitles = allocate_subtitles(script_segments, start, end)
        allocation_format = "duration_allocated_reviewed_text"
        warnings.append("exact Minimax text matching failed; fell back to proportional duration allocation")

    subtitle_track = {
        "source": str(alignment_path),
        "format": allocation_format,
        "segments": subtitles,
    }
    output_path = case_dir / "subtitle_track.json"
    output_path.write_text(json.dumps(subtitle_track, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.update_project:
        update_project(case_dir, script_segments, subtitle_track)

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "alignment": str(alignment_path),
            "subtitle_track": str(output_path),
            "segment_count": len(subtitles),
            "start": start,
            "end": end,
            "warnings": warnings,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply Minimax timing to reviewed script subtitles.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--alignment")
    parser.add_argument("--update-project", action="store_true")
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
        print(f"Subtitle track: {output['data']['subtitle_track']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

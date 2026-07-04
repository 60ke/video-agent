from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ffprobe_duration(path: Path) -> float:
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
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()}")
    return float(proc.stdout.strip())


def choose_video(case_dir: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve(strict=False)
        if not path.is_file():
            raise FileNotFoundError(f"video not found: {path}")
        return path
    versions = case_dir / "output" / "versions"
    candidates = sorted(
        [p for p in versions.glob("*.mp4") if p.is_file() and not p.name.endswith("_main.mp4")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"no final mp4 found under {versions}")
    return candidates[0]


def event_times(project: dict[str, Any], total_duration: float, max_frames: int) -> list[float]:
    times = {0.05, max(total_duration - 0.08, 0.05)}
    for event in project.get("visual_track", []) if isinstance(project.get("visual_track"), list) else []:
        if not isinstance(event, dict):
            continue
        start = event.get("start")
        end = event.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            times.add(max(float(start), 0.05))
            times.add((float(start) + float(end)) / 2)
            times.add(min(float(end) - 0.05, total_duration - 0.08))

    filtered = sorted(t for t in times if 0 <= t < total_duration)
    if len(filtered) <= max_frames:
        return filtered
    step = len(filtered) / max_frames
    return [filtered[min(math.floor(i * step), len(filtered) - 1)] for i in range(max_frames)]


def extract_frame(video: Path, timestamp: float, output: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed at {timestamp:.3f}s: {proc.stderr[-1000:]}")


def build_sheet(frames_dir: Path, count: int, output: Path, columns: int) -> None:
    rows = math.ceil(count / columns)
    pattern = str(frames_dir / "frame_%03d.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        "1",
        "-i",
        pattern,
        "-vf",
        f"scale=270:-1,tile={columns}x{rows}:padding=8:margin=8:color=black",
        "-frames:v",
        "1",
        str(output),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg contact sheet failed: {proc.stderr[-1000:]}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    video = choose_video(case_dir, args.video)
    project = load_json(case_dir / "video_project.json")
    total_duration = ffprobe_duration(video)
    times = event_times(project, total_duration, args.max_frames)

    label = args.label or video.stem
    qa_dir = case_dir / "output" / "qa" / f"{label}_frames"
    if qa_dir.exists():
        for file in qa_dir.glob("*.jpg"):
            file.unlink()
    qa_dir.mkdir(parents=True, exist_ok=True)

    frame_records = []
    for idx, timestamp in enumerate(times, start=1):
        frame = qa_dir / f"frame_{idx:03d}.jpg"
        extract_frame(video, timestamp, frame)
        frame_records.append({"index": idx, "time": round(timestamp, 3), "path": str(frame)})

    sheet = case_dir / "output" / "qa" / f"{label}_contact_sheet.jpg"
    build_sheet(qa_dir, len(frame_records), sheet, args.columns)

    manifest = {
        "schema_version": 1,
        "video": str(video),
        "duration": total_duration,
        "contact_sheet": str(sheet),
        "frames": frame_records,
    }
    manifest_path = case_dir / "output" / "qa" / f"{label}_contact_sheet.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": manifest | {"manifest_path": str(manifest_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract QA frames and build a contact sheet.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--video")
    parser.add_argument("--label")
    parser.add_argument("--max-frames", type=int, default=24)
    parser.add_argument("--columns", type=int, default=3)
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
        print(f"Contact sheet: {output['data']['contact_sheet']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ffprobe(path: Path) -> dict[str, Any]:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


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


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    video = choose_video(case_dir, args.video)
    project = load_json(case_dir / "video_project.json")
    data = ffprobe(video)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    errors: list[str] = []
    warnings: list[str] = []

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream:
        errors.append("no video stream")
    if not audio_stream:
        errors.append("no audio stream")

    meta = project.get("meta", {})
    expected_width = int(meta.get("width", 1080)) if isinstance(meta, dict) else 1080
    expected_height = int(meta.get("height", 1920)) if isinstance(meta, dict) else 1920
    if video_stream:
        width = video_stream.get("width")
        height = video_stream.get("height")
        if width != expected_width or height != expected_height:
            warnings.append(f"resolution differs from project meta: {width}x{height}, expected {expected_width}x{expected_height}")

    duration = float(fmt.get("duration", 0)) if fmt.get("duration") else 0
    if duration <= 0:
        errors.append("video duration is zero")

    contact_sheet = None
    qa_dir = case_dir / "output" / "qa"
    sheets = sorted(qa_dir.glob("*_contact_sheet.jpg"), key=lambda p: p.stat().st_mtime, reverse=True) if qa_dir.is_dir() else []
    if sheets:
        contact_sheet = str(sheets[0])
    else:
        warnings.append("no contact sheet found")

    ending = project.get("ending_track", {})
    if isinstance(ending, dict) and ending.get("policy") in ("default", "custom"):
        if duration <= float(ending.get("duration", 0) or 0):
            errors.append("final video duration is not longer than declared ending duration")

    ok = not errors
    report = {
        "schema_version": 1,
        "status": "passed" if ok else "failed",
        "video": str(video),
        "duration": duration,
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "contact_sheet": contact_sheet,
        "errors": errors,
        "warnings": warnings,
    }
    report_path = case_dir / "output" / "reports" / f"{video.stem}_qa_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": ok,
        "code": "ok" if ok else "render_qa_failed",
        "reason": "" if ok else f"{len(errors)} render QA error(s)",
        "data": report | {"report_path": str(report_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run machine-checkable render QA.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--video")
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
        print("Render QA passed")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

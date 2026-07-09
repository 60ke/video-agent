from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
DEFAULT_COVER_FRAME_COUNT = 1


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resolve_case_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else case_dir / path


def as_case_relative(case_dir: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(case_dir.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path)


def run_command(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")


def ffprobe_duration(path: Path) -> float | None:
    proc = run_command(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], path.parent)
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def normalize_filter(width: int, height: int, fps: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"


def create_cover_clip(case_dir: Path, cover_path: Path, output_path: Path, *, width: int, height: int, fps: int, frame_count: int) -> None:
    duration = frame_count / fps
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-i",
        str(cover_path),
        "-f",
        "lavfi",
        "-t",
        f"{duration:.6f}",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf",
        normalize_filter(width, height, fps),
        "-frames:v",
        str(frame_count),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        str(output_path),
    ]
    proc = run_command(cmd, case_dir)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg cover clip creation failed:\n{proc.stderr[-4000:]}")


def normalize_video(case_dir: Path, input_path: Path, output_path: Path, *, width: int, height: int, fps: int) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        normalize_filter(width, height, fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        str(output_path),
    ]
    proc = run_command(cmd, case_dir)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg video normalize failed:\n{proc.stderr[-4000:]}")


def concat_videos(case_dir: Path, cover_clip: Path, video_clip: Path, output_path: Path, concat_list: Path) -> None:
    concat_list.write_text(f"file '{cover_clip.as_posix()}'\nfile '{video_clip.as_posix()}'\n", encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart", str(output_path)]
    proc = run_command(cmd, case_dir)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg cover prepend concat failed:\n{proc.stderr[-4000:]}")


def prepend_cover(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    video_path = resolve_case_path(case_dir, args.video)
    cover_path = resolve_case_path(case_dir, args.cover) if args.cover else case_dir / "output" / "cover" / "cover_main.png"
    if not video_path or not video_path.is_file():
        if args.skip_if_missing:
            return {"ok": True, "skipped": True, "skip_reason": "video_missing", "video": str(video_path) if video_path else None}
        raise FileNotFoundError(f"video not found: {args.video}")
    if not cover_path or not cover_path.is_file():
        if args.skip_if_missing:
            return {"ok": True, "skipped": True, "skip_reason": "cover_missing", "cover": str(cover_path) if cover_path else None}
        raise FileNotFoundError(f"cover image not found: {args.cover or 'output/cover/cover_main.png'}")

    fps = int(args.fps or DEFAULT_FPS)
    frame_count = max(1, int(args.cover_frame_count or DEFAULT_COVER_FRAME_COUNT))
    width = int(args.width or DEFAULT_WIDTH)
    height = int(args.height or DEFAULT_HEIGHT)
    temp_dir = case_dir / "output" / "ffmpeg_temp" / "cover_prepend"
    temp_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    cover_clip = temp_dir / f"{stem}_cover_{frame_count}f.mp4"
    video_norm = temp_dir / f"{stem}_body_norm.mp4"
    concat_list = temp_dir / f"{stem}_cover_concat.txt"
    work_output = temp_dir / f"{stem}_with_cover_work.mp4"

    if args.output:
        output_path = resolve_case_path(case_dir, args.output)
        if not output_path:
            raise ValueError("invalid --output")
    elif args.replace:
        output_path = work_output
    else:
        output_path = video_path.with_name(f"{video_path.stem}_with_cover{video_path.suffix}")

    create_cover_clip(case_dir, cover_path, cover_clip, width=width, height=height, fps=fps, frame_count=frame_count)
    normalize_video(case_dir, video_path, video_norm, width=width, height=height, fps=fps)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    concat_videos(case_dir, cover_clip, video_norm, output_path, concat_list)

    final_path = output_path
    if args.replace:
        backup_path = video_path.with_name(f"{video_path.stem}_without_cover{video_path.suffix}")
        if args.keep_backup and video_path != backup_path:
            shutil.copy2(video_path, backup_path)
        shutil.move(str(output_path), str(video_path))
        final_path = video_path
    report = {
        "schema_version": 1,
        "ok": True,
        "skipped": False,
        "video": as_case_relative(case_dir, video_path),
        "cover": as_case_relative(case_dir, cover_path),
        "output": as_case_relative(case_dir, final_path),
        "replaced_input": bool(args.replace),
        "backup": as_case_relative(case_dir, backup_path) if args.replace and args.keep_backup else None,
        "fps": fps,
        "cover_frame_count": frame_count,
        "cover_duration_seconds": round(frame_count / fps, 6),
        "duration_after": ffprobe_duration(final_path),
        "temp": {
            "cover_clip": as_case_relative(case_dir, cover_clip),
            "video_norm": as_case_relative(case_dir, video_norm),
            "concat_list": as_case_relative(case_dir, concat_list),
        },
    }
    report_path = case_dir / "output" / "reports" / "prepend_cover_report.json"
    write_json(report_path, report)
    report["report"] = as_case_relative(case_dir, report_path)
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    data = prepend_cover(args)
    return {"ok": True, "code": "ok", "reason": "", "data": data}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepend a platform cover image as the first N frames of a rendered video.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--video", required=True, help="Rendered video path, relative to case dir or absolute.")
    parser.add_argument("--cover", help="Cover image path. Defaults to output/cover/cover_main.png.")
    parser.add_argument("--output", help="Output video path. Defaults to <video>_with_cover.mp4 unless --replace is used.")
    parser.add_argument("--replace", action="store_true", help="Replace the input video with the cover-prepended version.")
    parser.add_argument("--keep-backup", action="store_true", help="When replacing, keep <video>_without_cover.mp4 as a backup.")
    parser.add_argument("--skip-if-missing", action="store_true", help="Return ok/skipped instead of failing when video or cover is missing.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--cover-frame-count", type=int, default=DEFAULT_COVER_FRAME_COUNT)
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
        data = output.get("data", {})
        if data.get("skipped"):
            print(f"Cover prepend skipped: {data.get('skip_reason')}")
        else:
            print(f"Cover-prepended video: {data.get('output')}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

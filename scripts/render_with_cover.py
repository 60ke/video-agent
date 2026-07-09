from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def run_command(cmd: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError("command failed: " + " ".join(cmd) + "\nSTDOUT:\n" + proc.stdout[-3000:] + "\nSTDERR:\n" + proc.stderr[-3000:])
    try:
        parsed = json.loads(proc.stdout)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"ok": True, "stdout": proc.stdout.strip()}


def script_cmd(script: str, *args: str) -> list[str]:
    return [sys.executable, str(Path("scripts") / script), *args]


def latest_rendered_video(case_dir: Path) -> Path | None:
    versions_dir = case_dir / "output" / "versions"
    if not versions_dir.is_dir():
        return None
    candidates = [
        path
        for path in versions_dir.glob("*.mp4")
        if path.is_file()
        and not path.stem.endswith("_main")
        and not path.stem.endswith("_without_cover")
        and not path.stem.endswith("_with_cover")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.effects.json"
    if not project_path.is_file():
        project_path = case_dir / "video_project.json"

    steps: list[dict[str, Any]] = []
    build_cmd = script_cmd(
        "build_cover_plan.py",
        "--case",
        str(case_dir),
        "--project",
        str(project_path),
        "--title",
        args.title,
        "--max-refs",
        str(args.max_refs),
        "--json",
    )
    if args.subtitle_hint:
        build_cmd.extend(["--subtitle-hint", args.subtitle_hint])
    if args.style_hint:
        build_cmd.extend(["--style-hint", args.style_hint])
    if args.reference_asset_ids:
        build_cmd.append("--reference-asset-ids")
        build_cmd.extend(args.reference_asset_ids)
    steps.append({"name": "build_cover_plan", **run_command(build_cmd, ROOT)})

    render_cmd = script_cmd("render_cover_image.py", "--case", str(case_dir), "--json")
    if args.config:
        render_cmd.extend(["--config", args.config])
    if args.output:
        render_cmd.extend(["--output", args.output])
    if args.dry_run:
        render_cmd.append("--dry-run")
    steps.append({"name": "render_cover_image", **run_command(render_cmd, ROOT)})

    render_data = steps[-1].get("data", {}) if isinstance(steps[-1].get("data"), dict) else {}
    target_video = Path(args.video).expanduser().resolve(strict=False) if args.video else latest_rendered_video(case_dir)
    if args.prepend_cover:
        if target_video and target_video.is_file():
            prepend_cmd = script_cmd(
                "prepend_cover_frame.py",
                "--case",
                str(case_dir),
                "--video",
                str(target_video),
                "--cover",
                str(render_data.get("cover") or case_dir / "output" / "cover" / "cover_main.png"),
                "--cover-frame-count",
                str(args.cover_frame_count),
                "--fps",
                str(args.fps),
                "--replace",
                "--json",
            )
            if args.keep_video_backup:
                prepend_cmd.append("--keep-backup")
            steps.append({"name": "prepend_cover_frame", **run_command(prepend_cmd, ROOT)})
        else:
            steps.append({"name": "prepend_cover_frame", "ok": True, "code": "skipped", "reason": "target video not found", "data": {"skipped": True, "skip_reason": "video_missing"}})

    prepend_data = steps[-1].get("data", {}) if steps and steps[-1].get("name") == "prepend_cover_frame" and isinstance(steps[-1].get("data"), dict) else {}
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "project": str(project_path),
            "cover": render_data.get("cover"),
            "crop_preview": render_data.get("crop_preview"),
            "cover_report": render_data.get("report"),
            "video": str(target_video) if target_video else None,
            "prepend_cover": bool(args.prepend_cover),
            "prepend_skipped": bool(prepend_data.get("skipped")) if prepend_data else not bool(target_video),
            "prepend_report": prepend_data.get("report") if prepend_data else None,
            "steps": steps,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build, render, and optionally prepend a platform-safe short-video cover image in one command.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project", help="Defaults to video_project.effects.json if present, otherwise video_project.json.")
    parser.add_argument("--title", required=True, help="Exact front-end supplied cover title. This must be rendered verbatim.")
    parser.add_argument("--subtitle-hint")
    parser.add_argument("--style-hint")
    parser.add_argument("--reference-asset-ids", nargs="*", help="Explicit cover reference asset IDs, comma-separated or repeated.")
    parser.add_argument("--max-refs", type=int, default=3)
    parser.add_argument("--config", help="GPT image config path for non-dry runs.")
    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true", help="Use local Pillow rendering instead of GPT Image.")
    parser.add_argument("--video", help="Rendered video to receive the cover first frame. Defaults to newest output/versions/*.mp4.")
    prepend_group = parser.add_mutually_exclusive_group()
    prepend_group.add_argument("--prepend-cover", dest="prepend_cover", action="store_true", default=True, help="Prepend cover_main.png as the first video frame. Default: on.")
    prepend_group.add_argument("--no-prepend-cover", dest="prepend_cover", action="store_false", help="Do not modify the rendered video.")
    parser.add_argument("--cover-frame-count", type=int, default=1, help="Number of cover frames to prepend. Default: 1 frame.")
    parser.add_argument("--fps", type=int, default=30, help="Frame rate used to calculate cover duration. Default: 30fps.")
    parser.add_argument("--keep-video-backup", action="store_true", help="When prepending, keep <video>_without_cover.mp4 backup.")
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
        print(f"Cover image: {output['data']['cover']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

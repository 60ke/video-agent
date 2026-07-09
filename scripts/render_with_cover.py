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
    for asset_id in args.reference_asset_ids or []:
        build_cmd.extend(["--reference-asset-ids", asset_id])
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
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "project": str(project_path),
            "cover": render_data.get("cover"),
            "crop_preview": render_data.get("crop_preview"),
            "report": render_data.get("report"),
            "steps": steps,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and render a platform-safe short-video cover image in one command.")
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

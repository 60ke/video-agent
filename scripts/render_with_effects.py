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
    base_project = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.gpt_image.json"
    if not base_project.is_file():
        base_project = case_dir / "video_project.json"
    effects_project = case_dir / "video_project.effects.json"
    steps: list[dict[str, Any]] = []

    apply_cmd = script_cmd(
        "apply_effect_plan.py",
        "--case",
        str(case_dir),
        "--project",
        str(base_project),
        "--output-project",
        str(effects_project),
        "--preset",
        args.preset,
        "--freeze-motion",
        args.freeze_motion,
        "--json",
    )
    if args.force_effect_plan:
        apply_cmd.append("--force")
    steps.append({"name": "apply_effect_plan", **run_command(apply_cmd, ROOT)})

    prepare_cmd = script_cmd("prepare_effect_assets.py", "--case", str(case_dir), "--project", str(effects_project), "--output-project", str(effects_project), "--json")
    if args.effect_assets_dry_run:
        prepare_cmd.append("--dry-run")
    if args.force_effect_assets:
        prepare_cmd.append("--force")
    if args.config:
        prepare_cmd.extend(["--config", args.config])
    steps.append({"name": "prepare_effect_assets", **run_command(prepare_cmd, ROOT)})

    render_cmd = script_cmd("render_simple_ffmpeg.py", "--case", str(case_dir), "--project", str(effects_project), "--label", args.label, "--json")
    if args.skip_outro:
        render_cmd.append("--skip-outro")
    steps.append({"name": "render_simple_ffmpeg", **run_command(render_cmd, ROOT)})
    return {"ok": True, "code": "ok", "reason": "", "data": {"case_dir": str(case_dir), "base_project": str(base_project), "effects_project": str(effects_project), "label": args.label, "steps": steps}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply image effects, prepare auxiliary overlays, and render a Pipeline V2 project.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project", help="Input project. Defaults to video_project.gpt_image.json if present, otherwise video_project.json.")
    parser.add_argument("--label", default="effects_preview")
    parser.add_argument("--preset", choices=("none", "minimal", "balanced"), default="balanced")
    parser.add_argument("--freeze-motion", choices=("auto", "always", "never"), default="auto")
    parser.add_argument("--config", help="GPT image config path for auxiliary effect assets.")
    parser.add_argument("--force-effect-plan", action="store_true")
    parser.add_argument("--force-effect-assets", action="store_true")
    parser.add_argument("--effect-assets-dry-run", action="store_true", help="Generate local procedural highlight overlays instead of calling GPT Image.")
    parser.add_argument("--skip-outro", action="store_true")
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
        print(f"Effects render complete: {output['data']['effects_project']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

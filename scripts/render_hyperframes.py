from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def ffprobe(path: Path) -> dict[str, Any]:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def duration(path: Path) -> float:
    data = ffprobe(path)
    return float(data.get("format", {}).get("duration", 0))


def has_audio(path: Path) -> bool:
    data = ffprobe(path)
    return any(stream.get("codec_type") == "audio" for stream in data.get("streams", []))


def resolve_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    case_path = case_dir / path
    if case_path.exists():
        return case_path
    return Path(__file__).resolve().parents[1] / value


def run_command(cmd: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    return {
        "cmd": cmd,
        "cwd": str(cwd),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }


def npx_command() -> str:
    return shutil.which("npx.cmd") or shutil.which("npx") or "npx"


def concat_outro(main_path: Path, outro_path: Path, final_path: Path, width: int, height: int) -> None:
    main_duration = duration(main_path)
    outro_duration = duration(outro_path)
    main_audio = has_audio(main_path)
    outro_audio = has_audio(outro_path)

    filter_parts = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v0]",
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v1]",
    ]
    if main_audio:
        filter_parts.append("[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0]")
    else:
        filter_parts.append(f"anullsrc=r=44100:cl=stereo:d={main_duration:.3f}[a0]")
    if outro_audio:
        filter_parts.append("[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1]")
    else:
        filter_parts.append(f"anullsrc=r=44100:cl=stereo:d={outro_duration:.3f}[a1]")
    filter_parts.append("[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(main_path),
        "-i",
        str(outro_path),
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(final_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg outro concat failed: {proc.stderr[-4000:]}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project = load_json(case_dir / "video_project.json")
    hyperframes_dir = case_dir / "hyperframes"
    if not (hyperframes_dir / "index.html").is_file():
        raise FileNotFoundError(f"HyperFrames index not found: {hyperframes_dir / 'index.html'}")

    label = args.label or datetime.now().strftime("hyperframes_%Y%m%d_%H%M%S")
    versions_dir = case_dir / "output" / "versions"
    reports_dir = case_dir / "output" / "reports"
    versions_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    main_output = versions_dir / f"{label}_main.mp4"
    final_output = versions_dir / f"{label}.mp4"

    commands: list[dict[str, Any]] = []
    npx = npx_command()
    if not args.skip_checks:
        for subcommand in ("lint", "validate", "inspect"):
            result = run_command([npx, "hyperframes", subcommand], hyperframes_dir)
            commands.append(result)
            if result["returncode"] != 0 and args.strict:
                raise RuntimeError(f"npx hyperframes {subcommand} failed")

    render_cmd = [npx, "hyperframes", "render", "--quality", args.quality, "--output", str(main_output)]
    if args.strict:
        render_cmd.append("--strict")
    render_result = run_command(render_cmd, hyperframes_dir)
    commands.append(render_result)
    if render_result["returncode"] != 0:
        raise RuntimeError("npx hyperframes render failed")
    if not main_output.is_file() or main_output.stat().st_size == 0:
        raise RuntimeError(f"render produced no output: {main_output}")

    ending = project.get("ending_track", {})
    policy = ending.get("policy") if isinstance(ending, dict) else "none"
    meta = project.get("meta", {})
    width = int(meta.get("width", 1080)) if isinstance(meta, dict) else 1080
    height = int(meta.get("height", 1920)) if isinstance(meta, dict) else 1920

    if policy in ("default", "custom"):
        outro = resolve_path(case_dir, ending.get("source"))
        if not outro or not outro.is_file():
            raise FileNotFoundError(f"ending video not found: {ending.get('source')}")
        concat_outro(main_output, outro, final_output, width, height)
    else:
        shutil.copy2(main_output, final_output)

    final_probe = ffprobe(final_output)
    report = {
        "schema_version": 1,
        "status": "rendered",
        "case_dir": str(case_dir),
        "composition_dir": str(hyperframes_dir),
        "label": label,
        "main_output": str(main_output),
        "final_output": str(final_output),
        "ending_policy": policy,
        "commands": commands,
        "final_probe": final_probe,
    }
    report_path = reports_dir / f"{label}_render_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": report | {"report_path": str(report_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a video-agent HyperFrames composition.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--label")
    parser.add_argument("--quality", default="draft")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--skip-checks", action="store_true")
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
        sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    elif output["ok"]:
        print(f"Final video: {output['data']['final_output']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

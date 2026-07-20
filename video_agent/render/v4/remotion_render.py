"""Render V4Timeline via Remotion from frozen remotion.timeline.json."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from video_agent.contracts.v4 import CompiledVideoTimeline
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.io import write_json_atomic


def _safe_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _remotion_command(repo_root: Path) -> Path:
    base = repo_root / "remotion" / "node_modules" / ".bin"
    candidates = [base / "remotion.cmd", base / "remotion"]
    executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None:
        raise Stage6Error(
            "media_decode_preflight_failed",
            "Remotion dependencies missing; run npm install in remotion/",
        )
    return executable


def stage_v4_remotion_public(
    *,
    timeline: CompiledVideoTimeline,
    remotion_timeline_path: Path,
    run_render_dir: Path,
    repo_root: Path,
) -> Path:
    """Copy render/ assets into remotion/public and write props for V4Timeline."""
    run_name = f"{_safe_segment(timeline.case_id)}_{_safe_segment(timeline.run_id)}"
    public_dir = repo_root / "remotion" / "public" / "runs" / run_name
    if public_dir.exists():
        shutil.rmtree(public_dir)
    public_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(remotion_timeline_path.read_text(encoding="utf-8"))
    # Copy media referenced by relative object_key under run/render/
    for asset in payload.get("render_assets", []):
        rel = asset["object_key"]
        source = run_render_dir / rel
        if not source.is_file():
            raise Stage6Error("material_snapshot_mismatch", f"render asset missing: {rel}")
        dest = public_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        asset["object_key"] = (Path("runs") / run_name / rel).as_posix()

    for track in payload.get("audio_tracks", []):
        rel = track["object_key"]
        source = run_render_dir / rel
        if source.is_file():
            dest = public_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            track["object_key"] = (Path("runs") / run_name / rel).as_posix()

    props = public_dir / "remotion.timeline.json"
    write_json_atomic(props, payload)
    return props


def render_v4_silent_mp4(
    *,
    timeline: CompiledVideoTimeline,
    remotion_timeline_path: Path,
    run_render_dir: Path,
    repo_root: Path,
    output: Path,
    crf: int = 18,
    preset: str = "medium",
) -> Path:
    props = stage_v4_remotion_public(
        timeline=timeline,
        remotion_timeline_path=remotion_timeline_path,
        run_render_dir=run_render_dir,
        repo_root=repo_root,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    preset_arg = "ultrafast" if preset in {"ultrafast", "veryfast"} else "medium"
    command = [
        str(_remotion_command(repo_root)),
        "render",
        "src/index.ts",
        "V4Timeline",
        str(output),
        f"--props={props}",
        "--codec=h264",
        "--muted",
        f"--crf={crf}",
        f"--x264-preset={preset_arg}",
        "--log=warn",
    ]
    proc = subprocess.run(
        command,
        cwd=repo_root / "remotion",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise Stage6Error(
            "media_decode_preflight_failed",
            f"Remotion V4Timeline render failed: {(proc.stderr or proc.stdout)[-4000:]}",
        )
    if not output.is_file():
        raise Stage6Error("media_decode_preflight_failed", f"silent mp4 missing after render: {output}")
    return output

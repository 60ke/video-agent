from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from video_agent.contracts import RenderPlan
from video_agent.io import write_json_atomic

from .ffmpeg import mux_audio_tracks


def _safe_segment(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def export_remotion_props(plan: RenderPlan, repo_root: Path) -> Path:
    """Copy immutable media into Remotion's public tree and serialize render props."""

    run_name = f"{_safe_segment(plan.case_id)}_{_safe_segment(plan.run_id)}"
    public_dir = repo_root / "remotion" / "public" / "runs" / run_name
    asset_dir = public_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    payload = plan.model_dump(mode="json")
    for index, asset in enumerate(payload["assets"]):
        source = Path(asset["path"])
        if not source.is_file():
            raise FileNotFoundError(f"Remotion render asset missing: {source}")
        suffix = source.suffix.lower() or ".bin"
        destination = asset_dir / f"{index:03d}_{_safe_segment(asset['asset_id'])}{suffix}"
        # A render run must read the exact input captured in its RenderPlan.
        # Copying on each invocation avoids a stale public asset when source
        # pixels change without affecting dimensions or file size.
        shutil.copy2(source, destination)
        asset["path"] = destination.relative_to(repo_root / "remotion" / "public").as_posix()
    props = public_dir / "timeline.json"
    write_json_atomic(props, payload)
    return props


def _remotion_command(repo_root: Path) -> Path:
    base = repo_root / "remotion" / "node_modules" / ".bin"
    candidates = [base / "remotion.cmd", base / "remotion"]
    executable = next((candidate for candidate in candidates if candidate.is_file()), None)
    if executable is None:
        raise FileNotFoundError("Remotion dependencies are missing; run npm install in remotion")
    return executable


def render_remotion_video(plan: RenderPlan, output: Path, *, preset: str = "medium", crf: int = 18) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    props = export_remotion_props(plan, repo_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    silent_output = output.with_name(f"{output.stem}.remotion-silent.mp4")
    preset_arg = "ultrafast" if preset in {"ultrafast", "veryfast"} else "medium"
    command = [
        str(_remotion_command(repo_root)),
        "render",
        "src/index.ts",
        "VerticalDemo",
        str(silent_output),
        f"--props={props}",
        "--codec=h264",
        "--muted",
        f"--crf={crf}",
        f"--x264-preset={preset_arg}",
        "--log=warn",
    ]
    proc = subprocess.run(command, cwd=repo_root / "remotion", capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"Remotion render failed: {(proc.stderr or proc.stdout)[-4000:]}")
    mux_audio_tracks(plan, silent_output, output)
    silent_output.unlink(missing_ok=True)
    return output

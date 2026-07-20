from __future__ import annotations

import shutil
from pathlib import Path

from video_agent.contracts import RenderPlan
from video_agent.io import write_json_atomic


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
    raise RuntimeError(
        "V3 VerticalDemo production composition has been removed; "
        "use V4Timeline via V4 Stage6 / V4ProductionOrchestrator"
    )

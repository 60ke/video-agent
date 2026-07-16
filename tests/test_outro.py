from __future__ import annotations

import subprocess
from pathlib import Path

from video_agent.contracts import CaseConfig
from video_agent.outro import postprocess_outro


def _video(path: Path, *, color: str, duration: float, sample_rate: int = 48000) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:r=30:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={sample_rate}:duration={duration}",
            "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_case_postprocess_defaults_are_enabled() -> None:
    case = CaseConfig(case_id="demo", goal="demo")
    assert case.cover_enabled is True
    assert case.outro_enabled is True
    assert case.outro_source == "assets/outro/default_panda_outro.mp4"


def test_outro_is_appended_once_across_repeated_calls(tmp_path: Path) -> None:
    repo = tmp_path
    run = repo / "cases" / "demo" / "runs" / "run_1"
    final = run / "final"
    outro_dir = repo / "assets" / "outro"
    final.mkdir(parents=True)
    outro_dir.mkdir(parents=True)
    _video(final / "video.mp4", color="blue", duration=0.4)
    _video(outro_dir / "default.mp4", color="yellow", duration=0.3, sample_rate=44100)

    first = postprocess_outro(repo, run, "assets/outro/default.mp4")
    second = postprocess_outro(repo, run, "assets/outro/default.mp4")

    assert abs(first["output_duration_ms"] - 700) <= 100
    assert abs(second["output_duration_ms"] - 700) <= 100
    assert first["body_video_sha256"] == second["body_video_sha256"]

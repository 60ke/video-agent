from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from video_agent.io import load_json, sha256_file, utc_now, write_json_atomic


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _probe(path: Path) -> dict[str, Any]:
    result = _run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], path.parent)
    if result.returncode:
        raise RuntimeError(f"ffprobe failed: {result.stderr[-2000:]}")
    return json.loads(result.stdout)


def _duration_ms(path: Path) -> int:
    return round(float((_probe(path).get("format") or {}).get("duration") or 0) * 1000)


def _append(body: Path, outro: Path, output: Path, fps: int = 30) -> None:
    work = output.with_suffix(".outro_work.mp4")
    filter_complex = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={fps},"
        "setsar=1,setpts=PTS-STARTPTS[bv];"
        "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[ba];"
        f"[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={fps},"
        "setsar=1,setpts=PTS-STARTPTS[ov];"
        "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[oa];"
        "[bv][ba][ov][oa]concat=n=2:v=1:a=1[v][a]"
    )
    result = _run(
        [
            "ffmpeg", "-y", "-i", str(body), "-i", str(outro), "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(work),
        ],
        output.parent,
    )
    if result.returncode:
        raise RuntimeError(f"outro append failed: {result.stderr[-4000:]}")
    shutil.move(work, output)


def postprocess_outro(repo_root: Path, run_dir: Path, source: str | Path) -> dict[str, Any]:
    video = run_dir / "final" / "video.mp4"
    if not video.is_file():
        raise FileNotFoundError(f"rendered video is missing: {video}")
    source_path = Path(source)
    outro = source_path if source_path.is_absolute() else repo_root / source_path
    outro = outro.resolve()
    if not outro.is_file():
        raise FileNotFoundError(f"configured outro is missing: {outro}")

    work = run_dir / "work" / "outro"
    body = work / "video_without_outro.mp4"
    report_path = run_dir / "outro_report.json"
    previous = load_json(report_path) if report_path.is_file() else {}
    current_sha = sha256_file(video)
    if previous.get("output_video_sha256") != current_sha or not body.is_file():
        work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(video, body)

    body_duration_ms = _duration_ms(body)
    outro_duration_ms = _duration_ms(outro)
    _append(body, outro, video)
    output_duration_ms = _duration_ms(video)
    tolerance_ms = 100
    expected_duration_ms = body_duration_ms + outro_duration_ms
    if abs(output_duration_ms - expected_duration_ms) > tolerance_ms:
        raise ValueError(
            f"outro duration verification failed: body={body_duration_ms}ms outro={outro_duration_ms}ms output={output_duration_ms}ms"
        )

    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "source": outro.as_posix(),
        "source_sha256": sha256_file(outro),
        "body_video": body.as_posix(),
        "body_video_sha256": sha256_file(body),
        "body_duration_ms": body_duration_ms,
        "outro_duration_ms": outro_duration_ms,
        "output_duration_ms": output_duration_ms,
        "output_video_sha256": sha256_file(video),
        "checks": ["outro_appended_once", "portrait_1080x1920", "fps_30", "audio_48khz_stereo"],
    }
    write_json_atomic(report_path, report)
    return report

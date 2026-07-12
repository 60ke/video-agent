from __future__ import annotations

import subprocess
import json
import re
from pathlib import Path

from video_agent.contracts import CheckResult, QaReport, RenderPlan
from video_agent.qa.plan import validate_render_plan
from video_agent.render.ffmpeg import ffprobe


LOUDNESS_JSON_RE = re.compile(r"\{\s*\"input_i\".*?\}", re.DOTALL)


def _measure_loudness(video: Path) -> dict[str, float]:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(video),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "NUL",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    match = LOUDNESS_JSON_RE.search(proc.stderr)
    if proc.returncode != 0 or not match:
        raise RuntimeError("unable to measure final audio loudness")
    payload = json.loads(match.group(0))
    return {"integrated_lufs": float(payload["input_i"]), "true_peak_dbtp": float(payload["input_tp"])}


def _contact_sheet(video: Path, output: Path, plan: RenderPlan, frames: int = 16) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    selected: list[int] = []
    for shot in plan.shots:
        span = shot.end_frame - shot.start_frame
        selected.append(min(shot.end_frame - 1, shot.start_frame + max(10, round(span * 0.45))))
        if shot.cues:
            selected.extend(min(shot.end_frame - 1, cue.hit_frame + cue.settle_frames) for cue in shot.cues)
        else:
            selected.append(min(shot.end_frame - 1, shot.start_frame + max(12, round(span * 0.72))))
    selected = sorted(set(max(0, value) for value in selected))
    if len(selected) > frames:
        selected = [selected[round(index * (len(selected) - 1) / (frames - 1))] for index in range(frames)]
    select_expr = "+".join(f"eq(n\\,{frame})" for frame in selected)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video),
        "-vf",
        f"select='{select_expr}',scale=180:320:force_original_aspect_ratio=decrease,pad=180:320:(ow-iw)/2:(oh-ih)/2:black,tile=4x4:padding=4:margin=4",
        "-vsync",
        "vfr",
        "-frames:v",
        "1",
        str(output),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"contact sheet failed: {proc.stderr[-1000:]}")


def run_final_qa(plan: RenderPlan, video: Path, run_dir: Path) -> QaReport:
    checks = validate_render_plan(plan)
    if not video.is_file():
        checks.append(CheckResult(check_id="final_video_exists", status="failed", message=str(video)))
        return QaReport(case_id=plan.case_id, run_id=plan.run_id, status="failed", checks=checks)
    probe = ffprobe(video)
    video_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)
    dimensions_ok = bool(video_stream and video_stream.get("width") == plan.width and video_stream.get("height") == plan.height)
    checks.append(CheckResult(check_id="final_dimensions", status="passed" if dimensions_ok else "failed", details=video_stream or {}))
    checks.append(CheckResult(check_id="final_audio", status="passed" if audio_stream else "failed", details=audio_stream or {}))
    duration = float((probe.get("format") or {}).get("duration") or 0)
    expected = plan.frame_count / plan.fps
    duration_ok = abs(duration - expected) <= max(1 / plan.fps, 0.05) and duration <= plan.hard_max_sec
    checks.append(
        CheckResult(
            check_id="final_duration",
            status="passed" if duration_ok else "failed",
            details={"actual": duration, "expected": expected, "hard_max": plan.hard_max_sec},
        )
    )
    preferred = plan.preferred_min_sec <= duration <= plan.preferred_max_sec
    checks.append(
        CheckResult(
            check_id="preferred_duration",
            status="passed" if preferred else "warning",
            details={"actual": duration, "preferred_min": plan.preferred_min_sec, "preferred_max": plan.preferred_max_sec},
        )
    )
    loudness = _measure_loudness(video)
    loudness_ok = -18.0 <= loudness["integrated_lufs"] <= -14.0 and loudness["true_peak_dbtp"] <= -1.0
    checks.append(CheckResult(check_id="final_audio_loudness", status="passed" if loudness_ok else "failed", details=loudness))
    sheet = run_dir / "final" / "contact_sheet.jpg"
    _contact_sheet(video, sheet, plan)
    failed = any(check.status == "failed" for check in checks)
    return QaReport(
        case_id=plan.case_id,
        run_id=plan.run_id,
        status="failed" if failed else "passed",
        final_video=video.as_posix(),
        checks=checks,
    )

"""FFmpeg mix for V4 compiled audio tracks + silent visual MP4."""

from __future__ import annotations

import subprocess
from pathlib import Path

from video_agent.contracts.v4 import CompiledVideoTimeline
from video_agent.contracts.v4.stage6_errors import Stage6Error


def mix_compiled_audio(
    *,
    timeline: CompiledVideoTimeline,
    visual_input: Path,
    run_render_dir: Path,
    output: Path,
) -> Path:
    if not visual_input.is_file():
        raise Stage6Error("media_decode_preflight_failed", f"visual missing: {visual_input}")
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = timeline.frame_count / timeline.fps
    command = ["ffmpeg", "-y", "-i", str(visual_input)]
    resolved_paths: list[Path] = []
    for track in timeline.audio_tracks:
        path = run_render_dir / track.object_key
        if not path.is_file():
            raise Stage6Error("media_decode_preflight_failed", f"audio missing: {track.object_key}")
        resolved_paths.append(path)
        command.extend(["-i", str(path)])

    filters: list[str] = []
    labels: list[str] = []
    for index, track in enumerate(timeline.audio_tracks, start=1):
        delay_ms = int(round(track.start_frame * 1000 / timeline.fps))
        gain = 10 ** (track.gain_db / 20)
        label = f"a{index}"
        chain = [f"[{index}:a]aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo"]
        if track.trim_start_ms or track.max_duration_ms:
            trim_args = []
            if track.trim_start_ms:
                trim_args.append(f"start={track.trim_start_ms / 1000:.6f}")
            if track.max_duration_ms:
                trim_args.append(f"duration={track.max_duration_ms / 1000:.6f}")
            chain.extend([f"atrim={':'.join(trim_args)}", "asetpts=PTS-STARTPTS"])
        if track.fade_in_ms:
            chain.append(f"afade=t=in:st=0:d={track.fade_in_ms / 1000:.6f}")
        if track.fade_out_ms and track.max_duration_ms:
            fade_start = max(0, track.max_duration_ms - track.fade_out_ms) / 1000
            chain.append(f"afade=t=out:st={fade_start:.6f}:d={track.fade_out_ms / 1000:.6f}")
        chain.extend(
            [
                f"adelay={delay_ms}|{delay_ms}",
                f"volume={gain:.8f}",
                "apad",
                f"atrim=0:{duration:.6f}[{label}]",
            ]
        )
        filters.append(",".join(chain))
        labels.append(label)

    mix_inputs = "".join(f"[{label}]" for label in labels)
    filters.append(
        f"{mix_inputs}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,"
        f"aformat=sample_rates=48000:sample_fmts=fltp:channel_layouts=stereo,"
        f"atrim=0:{duration:.6f}[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-t",
            f"{duration:.6f}",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise Stage6Error("media_decode_preflight_failed", f"ffmpeg mix failed: {proc.stderr[-2000:]}")
    _ = resolved_paths
    return output

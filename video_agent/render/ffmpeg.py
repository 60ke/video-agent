from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from video_agent.contracts import RenderPlan
from video_agent.scene import FrameRenderer


def ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def render_video(plan: RenderPlan, output: Path, *, preset: str = "medium", crf: int = 18) -> Path:
    voice_tracks = [track for track in plan.audio_tracks if track.kind == "voice"]
    if len(voice_tracks) != 1:
        raise ValueError("V3 currently requires exactly one voice track")
    voice_path = Path(voice_tracks[0].path)
    if not voice_path.is_file():
        raise FileNotFoundError(f"voice track missing: {voice_path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = plan.frame_count / plan.fps
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{plan.width}x{plan.height}",
        "-r",
        str(plan.fps),
        "-i",
        "-",
    ]
    for track in plan.audio_tracks:
        if not Path(track.path).is_file():
            raise FileNotFoundError(f"audio track missing: {track.path}")
        if track.loop:
            command.extend(["-stream_loop", "-1"])
        command.extend(["-i", track.path])

    filters: list[str] = []
    labels: list[str] = []
    voice_label = ""
    bgm_track_index: int | None = None
    for index, track in enumerate(plan.audio_tracks, start=1):
        delay_ms = int(round(track.start_frame * 1000 / plan.fps))
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
        chain.extend([f"adelay={delay_ms}|{delay_ms}", f"volume={gain:.8f}", "apad", f"atrim=0:{duration:.6f}[{label}]"])
        filters.append(",".join(chain))
        if track.kind == "voice":
            voice_label = label
        elif track.kind == "bgm" and track.duck_under_voice:
            bgm_track_index = index
        else:
            labels.append(label)

    if bgm_track_index is not None:
        bgm_label = f"a{bgm_track_index}"
        filters.append(f"[{voice_label}]asplit=2[voice_mix][voice_side]")
        filters.append(
            f"[{bgm_label}][voice_side]sidechaincompress=threshold=0.025:ratio=8:attack=12:release=260[bgm_duck]"
        )
        labels = ["voice_mix", "bgm_duck"] + labels
    else:
        labels = [voice_label] + labels
    mix_inputs = "".join(f"[{label}]" for label in labels)
    filters.append(
        f"{mix_inputs}amix=inputs={len(labels)}:duration=longest:normalize=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{duration:.6f}[aout]"
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
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
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
    renderer = FrameRenderer(plan)
    log_path = output.with_suffix(".ffmpeg.log")
    with log_path.open("wb") as log:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
        try:
            if proc.stdin is None:
                raise RuntimeError("ffmpeg stdin was not created")
            for frame in range(plan.frame_count):
                proc.stdin.write(renderer.render(frame).tobytes())
            proc.stdin.close()
            returncode = proc.wait()
        except Exception:
            proc.kill()
            proc.wait()
            raise
        finally:
            renderer.close()
    if returncode != 0:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        raise RuntimeError(f"ffmpeg render failed: {log_text[-4000:]}")
    return output

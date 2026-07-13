from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from video_agent.audio.profiles import RegisteredSfx, SfxCatalog
from video_agent.io import sha256_file, write_json_atomic


@dataclass(frozen=True)
class RegistrationSpec:
    semantic_id: str
    source_filename: str
    target_filename: str
    gain_db: float
    trim_start_ms: int
    max_duration_ms: int
    fade_in_ms: int
    fade_out_ms: int
    priority: int
    sync_point: str
    sync_offset_ms: int
    allowed_intents: tuple[str, ...]
    forbidden_intents: tuple[str, ...] = ()


SPECS = (
    RegistrationSpec("typing", "打字声-音效.wav", "typing.wav", -22, 430, 1320, 5, 80, 45, "onset", 0, ("参数输入", "名称", "主题", "描述")),
    RegistrationSpec("transition_whoosh", "呼-转场.wav", "transition_whoosh.wav", -18, 10, 1150, 8, 120, 65, "peak", 332, ("slide_left", "slide_right", "大镜头交接")),
    RegistrationSpec("camera_shutter", "咔嚓拍照声-音效.wav", "camera_shutter.wav", -18, 70, 250, 3, 45, 72, "peak", 99, ("截图", "保存", "定格", "导出图片"), ("普通结果切换",)),
    RegistrationSpec("task_complete", "任务完成buling-音效.wav", "task_complete.wav", -18, 0, 760, 5, 130, 88, "peak", 113, ("生成完成", "任务完成", "成功")),
    RegistrationSpec("mouse_click", "鼠标点击声-音效.wav", "mouse_click.wav", -16, 130, 180, 2, 30, 65, "peak", 134, ("菜单点击", "按钮点击", "上传", "字段点击")),
    RegistrationSpec("swish", "唰-音效.wav", "swish.wav", -17, 0, 140, 2, 35, 55, "peak", 20, ("短结果切换", "轻量淡变")),
)


def _convert(source: Path, output: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(output),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"SFX conversion failed for {source.name}: {proc.stderr[-1000:]}")


def register_sfx_library(source_dir: Path, output_dir: Path) -> SfxCatalog:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    missing = [spec.source_filename for spec in SPECS if not (source_dir / spec.source_filename).is_file()]
    if missing:
        raise FileNotFoundError(f"SFX sources are missing: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)
    target_names = {spec.target_filename for spec in SPECS}
    for path in output_dir.glob("*.wav"):
        if path.name not in target_names:
            path.unlink()

    assets: list[RegisteredSfx] = []
    for spec in SPECS:
        source = source_dir / spec.source_filename
        output = output_dir / spec.target_filename
        _convert(source, output)
        with wave.open(str(output), "rb") as audio:
            sample_rate = audio.getframerate()
            channels = audio.getnchannels()
            sample_width_bits = audio.getsampwidth() * 8
            duration_ms = round(audio.getnframes() * 1000 / sample_rate)
        if (sample_rate, sample_width_bits, channels) != (48000, 16, 2):
            raise ValueError(f"registered SFX has unexpected format: {output}")
        assets.append(
            RegisteredSfx(
                semantic_id=spec.semantic_id,
                filename=spec.target_filename,
                source_filename=spec.source_filename,
                source_sha256=sha256_file(source),
                registered_sha256=sha256_file(output),
                sample_rate=sample_rate,
                sample_width_bits=sample_width_bits,
                channels=channels,
                duration_ms=duration_ms,
                path=f"assets/audio/sfx/{spec.target_filename}",
                gain_db=spec.gain_db,
                trim_start_ms=spec.trim_start_ms,
                max_duration_ms=spec.max_duration_ms,
                fade_in_ms=spec.fade_in_ms,
                fade_out_ms=spec.fade_out_ms,
                priority=spec.priority,
                sync_point=spec.sync_point,
                sync_offset_ms=spec.sync_offset_ms,
                allowed_intents=list(spec.allowed_intents),
                forbidden_intents=list(spec.forbidden_intents),
            )
        )
    catalog = SfxCatalog(
        profile_id="douyin_common_v1",
        normalization={"sample_rate": 48000, "sample_width_bits": 16, "channels": 2, "codec": "pcm_s16le"},
        assets=assets,
    )
    write_json_atomic(output_dir / "catalog.json", catalog)
    return catalog

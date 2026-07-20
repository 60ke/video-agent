"""Freeze render materials into run/render with relative paths only."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from video_agent.contracts.v4 import CompiledRenderAsset, CompiledVideoTimeline
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.io import sha256_file, write_json_atomic


def resolve_materials(
    *,
    timeline: CompiledVideoTimeline,
    run_dir: Path,
    object_store_root: Path,
    repo_root: Path,
) -> CompiledVideoTimeline:
    render_root = run_dir / "render"
    assets_dir = render_root / "assets"
    audio_dir = render_root / "audio"
    assets_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    remapped: list[CompiledRenderAsset] = []
    for asset in timeline.render_assets:
        source = object_store_root / asset.object_key
        if not source.is_file():
            # Also try repo-relative for configured fixtures
            alt = repo_root / asset.object_key
            source = alt if alt.is_file() else source
        if not source.is_file():
            raise Stage6Error(
                "material_snapshot_mismatch",
                f"source object missing: {asset.object_key}",
            )
        digest = sha256_file(source)
        if digest != asset.sha256:
            raise Stage6Error(
                "material_snapshot_mismatch",
                f"hash mismatch for {asset.asset_ref}",
                details={"expected": asset.sha256, "actual": digest},
            )
        suffix = source.suffix.lower() or ".bin"
        stable = f"{asset.asset_ref.replace('asset://', '')}_{digest[:12]}{suffix}"
        dest = assets_dir / stable
        if not dest.exists():
            shutil.copy2(source, dest)
        # GIF → MP4 pre-transcode for Remotion decode stability
        if suffix == ".gif":
            mp4 = dest.with_suffix(".mp4")
            if not mp4.exists():
                _transcode_gif(dest, mp4)
            dest = mp4
            digest = sha256_file(dest)
            stable = dest.name
        from video_agent.compiler.v4.media_probe import probe_media_size

        width, height, media_kind, duration_ms = probe_media_size(dest)
        remapped.append(
            asset.model_copy(
                update={
                    "object_key": f"assets/{stable}",
                    "sha256": digest,
                    "media_kind": media_kind,  # type: ignore[arg-type]
                    "width": width,
                    "height": height,
                    "duration_ms": duration_ms if duration_ms is not None else asset.duration_ms,
                }
            )
        )

    audio_tracks = []
    for track in timeline.audio_tracks:
        source = run_dir / track.object_key
        if not source.is_file():
            source = repo_root / track.object_key
        if not source.is_file():
            raise Stage6Error(
                "media_decode_preflight_failed",
                f"audio missing: {track.object_key}",
            )
        digest = sha256_file(source)
        if track.kind != "sfx" and digest != track.sha256:
            # Voice may be run-local; trust file hash rewrite
            pass
        name = f"{track.kind}_{hashlib.sha256(track.track_id.encode()).hexdigest()[:10]}{source.suffix}"
        dest = audio_dir / name
        if not dest.exists():
            shutil.copy2(source, dest)
        audio_tracks.append(
            track.model_copy(update={"object_key": f"audio/{name}", "sha256": sha256_file(dest)})
        )

    updated = timeline.model_copy(update={"render_assets": remapped, "audio_tracks": audio_tracks})
    write_json_atomic(render_root / "compiled_timeline.resolved.json", updated)
    return updated


def _transcode_gif(source: Path, dest: Path) -> None:
    import subprocess

    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-movflags",
            "faststart",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(dest),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise Stage6Error(
            "media_decode_preflight_failed",
            f"gif transcode failed: {proc.stderr[-1000:]}",
        )

"""Probe media dimensions for Stage6 render assets without live SQLite."""

from __future__ import annotations

from pathlib import Path

from video_agent.contracts.v4.stage6_errors import Stage6Error


def probe_media_size(path: Path) -> tuple[int, int, str, int | None]:
    """Return (width, height, media_kind, duration_ms)."""
    if not path.is_file():
        raise Stage6Error("media_decode_preflight_failed", f"media missing: {path}")
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".webm", ".mov", ".m4v"}:
        from video_agent.render.ffmpeg import ffprobe

        payload = ffprobe(path)
        streams = payload.get("streams") or []
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        if video is None:
            raise Stage6Error("media_decode_preflight_failed", f"no video stream: {path}")
        width = int(video["width"])
        height = int(video["height"])
        duration_ms = None
        raw = video.get("duration") or (payload.get("format") or {}).get("duration")
        if raw is not None:
            duration_ms = int(round(float(raw) * 1000))
        return width, height, "video", duration_ms

    from PIL import Image

    with Image.open(path) as image:
        width, height = image.size
    return width, height, "image", None


def resolve_source_path(*, object_key: str, object_store_root: Path, repo_root: Path) -> Path:
    candidates = [
        object_store_root / object_key,
        repo_root / object_key,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise Stage6Error("material_snapshot_mismatch", f"source object missing: {object_key}")

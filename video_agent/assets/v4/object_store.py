from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from PIL import Image

from video_agent.contracts.v4 import Orientation
from video_agent.io import sha256_file
from video_agent.render.ffmpeg import ffprobe


class ObjectStoreError(RuntimeError):
    pass


class ObjectConflictError(ObjectStoreError):
    pass


@dataclass(frozen=True)
class MediaObjectInfo:
    object_key: str
    content_sha256: str
    byte_size: int
    media_type: str
    width: int
    height: int
    orientation: Orientation
    animated: bool


class AssetObjectStore(Protocol):
    def resolve(self, object_key: str) -> Path: ...
    def inspect(self, object_key: str) -> MediaObjectInfo: ...
    def verify(self, object_key: str, expected_sha256: str) -> MediaObjectInfo: ...
    def put_file(self, source: Path, object_key: str) -> MediaObjectInfo: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, object_key: str) -> Path:
        path = PurePosixPath(object_key)
        if (
            not object_key
            or "\\" in object_key
            or path.is_absolute()
            or ".." in path.parts
            or ":" in path.parts[0]
            or object_key != path.as_posix()
        ):
            raise ObjectStoreError(f"invalid object key: {object_key!r}")
        target = (self.root / Path(*path.parts)).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ObjectStoreError(f"object key escapes store root: {object_key!r}") from exc
        return target

    def inspect(self, object_key: str) -> MediaObjectInfo:
        path = self.resolve(object_key)
        if not path.is_file():
            raise FileNotFoundError(f"object not found: {object_key}")
        return self._inspect_path(path, object_key, content_sha256=sha256_file(path))

    def verify(self, object_key: str, expected_sha256: str) -> MediaObjectInfo:
        info = self.inspect(object_key)
        if info.content_sha256 != expected_sha256:
            raise ObjectStoreError(
                f"content hash mismatch for {object_key}: expected {expected_sha256}, got {info.content_sha256}"
            )
        return info

    def put_file(self, source: Path, object_key: str) -> MediaObjectInfo:
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        target = self.resolve(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        source_hash = sha256_file(source)
        if target.exists():
            existing = self.inspect(object_key)
            if existing.content_sha256 == source_hash:
                return existing
            raise ObjectConflictError(f"object key already has different content: {object_key}")
        fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as destination, source.open("rb") as incoming:
                for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            temporary = Path(temporary_name)
            temporary_info = self._inspect_path(temporary, object_key, content_sha256=source_hash)
            if temporary_info.content_sha256 != source_hash:
                raise ObjectStoreError(f"copy hash mismatch for {object_key}")
            try:
                os.link(temporary, target)
            except FileExistsError:
                existing = self.inspect(object_key)
                if existing.content_sha256 != source_hash:
                    raise ObjectConflictError(f"object key already has different content: {object_key}") from None
            except OSError:
                temporary.replace(target)
            return self.inspect(object_key)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    def _inspect_path(self, path: Path, object_key: str, *, content_sha256: str | None = None) -> MediaObjectInfo:
        media_type = mimetypes.guess_type(object_key)[0] or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if media_type.startswith("audio/"):
            raise ObjectStoreError(f"audio objects are not allowed in the visual asset store: {object_key}")
        if media_type.startswith("image/"):
            width, height, animated = self._probe_image(path, object_key)
        elif media_type.startswith("video/"):
            width, height, animated = self._probe_video(path, object_key)
        else:
            raise ObjectStoreError(f"visual object must be an image or video: {object_key} ({media_type})")
        orientation = (
            Orientation.LANDSCAPE if width > height else Orientation.PORTRAIT if height > width else Orientation.SQUARE
        )
        digest = content_sha256 or hashlib.sha256(path.read_bytes()).hexdigest()
        return MediaObjectInfo(
            object_key, digest, path.stat().st_size, media_type, width, height, orientation, animated
        )

    def _probe_image(self, path: Path, object_key: str) -> tuple[int, int, bool]:
        try:
            with Image.open(path) as image:
                width, height = image.size
                image.verify()
            with Image.open(path) as image:
                animated = bool(getattr(image, "is_animated", False))
        except Exception as exc:  # Pillow exposes format-specific exception types.
            raise ObjectStoreError(f"invalid image object: {object_key}") from exc
        return width, height, animated

    def _probe_video(self, path: Path, object_key: str) -> tuple[int, int, bool]:
        try:
            payload = ffprobe(path)
        except Exception as exc:
            raise ObjectStoreError(f"invalid video object: {object_key}") from exc
        video_streams = [
            stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"
        ]
        if not video_streams:
            raise ObjectStoreError(f"video object has no video stream: {object_key}")
        stream = video_streams[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        if width <= 0 or height <= 0:
            raise ObjectStoreError(f"video object missing dimensions: {object_key}")
        return width, height, True

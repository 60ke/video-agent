"""Bulk case lifecycle operations for local production workspaces."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ExportedVideo:
    case_id: str
    source: str
    destination: str
    sha256: str
    size_bytes: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _video_candidates(case_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    runs = case_dir / "runs"
    if runs.is_dir():
        candidates.extend(sorted(runs.glob("*/final/video.mp4")))
    versions = case_dir / "output" / "versions"
    if versions.is_dir():
        candidates.extend(sorted(versions.glob("*.mp4")))
    return [path for path in candidates if path.is_file()]


def export_case_videos(cases_dir: Path, destination: Path) -> dict[str, object]:
    cases_dir = cases_dir.resolve()
    destination = destination.resolve()
    if not cases_dir.is_dir():
        raise FileNotFoundError(f"cases directory does not exist: {cases_dir}")
    destination.mkdir(parents=True, exist_ok=True)
    exported: list[ExportedVideo] = []
    used_names: set[str] = set()
    for case_dir in sorted(item for item in cases_dir.iterdir() if item.is_dir()):
        candidates = _video_candidates(case_dir)
        for index, source in enumerate(candidates, start=1):
            stem = case_dir.name if len(candidates) == 1 else f"{case_dir.name}__{source.parent.name or source.stem}__{index:02d}"
            name = f"{stem}.mp4"
            if name in used_names:
                name = f"{case_dir.name}__{source.stem}__{index:02d}.mp4"
            used_names.add(name)
            target = destination / name
            shutil.copy2(source, target)
            exported.append(ExportedVideo(case_dir.name, source.as_posix(), target.as_posix(), _sha256(target), target.stat().st_size))
    manifest = destination / "video_agent_case_export_manifest.json"
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_cases": cases_dir.as_posix(),
        "destination": destination.as_posix(),
        "videos": [item.__dict__ for item in exported],
    }
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"destination": destination.as_posix(), "manifest": manifest.as_posix(), "cases": len(list(item for item in cases_dir.iterdir() if item.is_dir())), "videos": len(exported)}


def clean_cases(cases_dir: Path, *, require_export_manifest: Path | None = None) -> dict[str, object]:
    cases_dir = cases_dir.resolve()
    if not cases_dir.is_dir():
        raise FileNotFoundError(f"cases directory does not exist: {cases_dir}")
    if require_export_manifest is not None:
        manifest = require_export_manifest.resolve()
        if not manifest.is_file():
            raise FileNotFoundError(f"export manifest is required before cleanup: {manifest}")
    children = [item.resolve() for item in cases_dir.iterdir() if item.is_dir()]
    for child in children:
        if child.parent != cases_dir:
            raise RuntimeError(f"refusing to remove path outside cases directory: {child}")
    for child in children:
        shutil.rmtree(child)
    return {"cases_dir": cases_dir.as_posix(), "removed_cases": len(children)}

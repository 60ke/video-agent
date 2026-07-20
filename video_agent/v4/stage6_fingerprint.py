"""Stage6 Resume fingerprint helpers."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from video_agent.io import sha256_file


def _hash_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def compiler_source_fingerprint(repo_root: Path) -> str:
    roots = [
        repo_root / "video_agent" / "compiler" / "v4",
        repo_root / "video_agent" / "timing" / "v4",
        repo_root / "video_agent" / "render" / "v4",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return _hash_paths(files)


def remotion_adapter_fingerprint(repo_root: Path) -> str:
    root = repo_root / "remotion" / "src" / "v4"
    files = sorted(root.rglob("*.ts*")) if root.is_dir() else []
    return _hash_paths(files)


def font_fingerprint(repo_root: Path) -> str | None:
    candidates = [
        repo_root / "remotion" / "public" / "fonts",
        repo_root / "assets" / "fonts",
    ]
    files: list[Path] = []
    for root in candidates:
        if root.is_dir():
            files.extend(path for path in root.rglob("*") if path.suffix.lower() in {".ttf", ".otf", ".ttc", ".woff2"})
    if files:
        return _hash_paths(files)
    try:
        from video_agent.compiler.v4.font_measure import subtitle_font_fingerprint

        return subtitle_font_fingerprint()
    except Exception:
        return None


def tool_version(command: list[str]) -> str | None:
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else None


def build_stage6_fingerprint_components(
    *,
    repo_root: Path,
    base: dict,
) -> dict:
    components = dict(base)
    components["compiler_source_sha256"] = compiler_source_fingerprint(repo_root)
    components["remotion_adapter_sha256"] = remotion_adapter_fingerprint(repo_root)
    font = font_fingerprint(repo_root)
    if font:
        components["font_files_sha256"] = font
    ffmpeg = tool_version(["ffmpeg", "-version"])
    if ffmpeg:
        components["ffmpeg_version"] = ffmpeg
    remotion = tool_version(
        [
            str(repo_root / "remotion" / "node_modules" / ".bin" / ("remotion.cmd" if (repo_root / "remotion" / "node_modules" / ".bin" / "remotion.cmd").is_file() else "remotion")),
            "versions",
        ]
    )
    if remotion:
        components["remotion_version"] = remotion
    return components

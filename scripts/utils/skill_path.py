from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, NamedTuple


SKILL_MARKER = "SKILL.md"
ENV_VAR = "VIDEO_AGENT_SKILL_ROOT"
DEFAULT_VOICE_PROMPT = Path("assets") / "voice" / "default_voice_clone_prompt_5s.wav"
DEFAULT_OUTRO = Path("assets") / "outro" / "default_panda_outro.mp4"


class SkillRootResult(NamedTuple):
    root: Path | None
    attempted: tuple[Path, ...]


def _dedupe(paths: Iterable[Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        normalized = str(path.expanduser().resolve(strict=False)).lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(path.expanduser().resolve(strict=False))
    return tuple(result)


def _is_skill_root(path: Path) -> bool:
    return (
        (path / SKILL_MARKER).is_file()
        and (path / "references").is_dir()
        and (path / "assets").is_dir()
        and (path / "scripts").is_dir()
    )


def build_skill_root_candidates(start: str | os.PathLike[str] | None = None) -> tuple[Path, ...]:
    """Return likely video-agent skill roots for mixed editor and local layouts."""
    start_path = Path(start or os.getcwd()).expanduser().resolve(strict=False)
    cwd = Path.cwd().resolve(strict=False)
    home = Path.home().resolve(strict=False)

    candidates: list[Path] = []

    env_root = os.getenv(ENV_VAR, "").strip()
    if env_root:
        candidates.append(Path(env_root))

    for base in (start_path, cwd):
        current = base if base.is_dir() else base.parent
        candidates.extend([current, current.parent, current.parent.parent])
        candidates.extend(
            [
                current / "video-agent",
                current / "skills" / "video-agent",
                current / ".codex" / "skills" / "video-agent",
                current / ".agent" / "skills" / "video-agent",
                current / ".claude" / "skills" / "video-agent",
                current / ".trae" / "skills" / "video-agent",
            ]
        )

    candidates.extend(
        [
            home / ".codex" / "skills" / "video-agent",
            home / ".agent" / "skills" / "video-agent",
            home / ".claude" / "skills" / "video-agent",
            home / ".trae" / "skills" / "video-agent",
        ]
    )

    return _dedupe(candidates)


def resolve_skill_root(start: str | os.PathLike[str] | None = None) -> SkillRootResult:
    attempted = build_skill_root_candidates(start)
    for candidate in attempted:
        if _is_skill_root(candidate):
            return SkillRootResult(candidate, attempted)
    return SkillRootResult(None, attempted)


def require_skill_root(start: str | os.PathLike[str] | None = None) -> Path:
    result = resolve_skill_root(start)
    if result.root:
        return result.root

    attempted = "\n- ".join(str(path) for path in result.attempted)
    raise FileNotFoundError(
        "Could not resolve video-agent skill root.\n"
        f"Set {ENV_VAR} or install/copy the skill to a known skills directory.\n"
        f"Tried:\n- {attempted}"
    )


def default_voice_prompt_path(root: str | os.PathLike[str] | None = None) -> Path:
    skill_root = Path(root).resolve(strict=False) if root else require_skill_root()
    return skill_root / DEFAULT_VOICE_PROMPT


def default_outro_path(root: str | os.PathLike[str] | None = None) -> Path:
    skill_root = Path(root).resolve(strict=False) if root else require_skill_root()
    return skill_root / DEFAULT_OUTRO


def require_default_assets(root: str | os.PathLike[str] | None = None) -> dict[str, str]:
    skill_root = Path(root).resolve(strict=False) if root else require_skill_root()
    voice_prompt = skill_root / DEFAULT_VOICE_PROMPT
    outro = skill_root / DEFAULT_OUTRO

    missing = [path for path in (voice_prompt, outro) if not path.is_file()]
    if missing:
        formatted = "\n- ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing bundled video-agent assets:\n- {formatted}")

    return {
        "skill_root": str(skill_root),
        "default_voice_prompt": str(voice_prompt),
        "default_outro": str(outro),
    }


if __name__ == "__main__":
    root = require_skill_root(Path(__file__).resolve())
    assets = require_default_assets(root)
    for key, value in assets.items():
        print(f"{key}={value}")

"""Locate and validate the external jianying-editor-skill runtime."""

from __future__ import annotations

import hashlib
import importlib
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


MINIMUM_SKILL_VERSION = (1, 5, 0)
_IMPORT_LOCK = threading.Lock()
_LOADED_ROOT: Path | None = None
_LOADED_MODULES: tuple[Any, Any] | None = None


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = value.strip().split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"invalid jianying skill version: {value!r}")
    return tuple(int(part) for part in parts)


def _deduplicate(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            result.append(resolved)
    return result


@dataclass(frozen=True)
class JianyingSkillCapabilities:
    version: str
    capability_sha256: str
    draft_creation: bool
    native_transitions: bool
    native_clip_animations: bool
    rich_subtitles: bool
    audio_tracks: bool
    screen_recording_tools: bool
    auto_export_tool_present: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "capability_sha256": self.capability_sha256,
            "draft_creation": self.draft_creation,
            "native_transitions": self.native_transitions,
            "native_clip_animations": self.native_clip_animations,
            "rich_subtitles": self.rich_subtitles,
            "audio_tracks": self.audio_tracks,
            "screen_recording_tools": self.screen_recording_tools,
            "auto_export_tool_present": self.auto_export_tool_present,
        }


class JianyingSkillRuntime:
    """Validated handle to one installed jianying-editor-skill checkout."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.scripts_root = self.root / "scripts"
        self.version = self._validate_layout()

    @classmethod
    def discover(
        cls,
        *,
        explicit_root: str | Path | None = None,
        repo_root: str | Path | None = None,
    ) -> "JianyingSkillRuntime":
        candidates: list[Path] = []
        if explicit_root:
            candidates.append(Path(explicit_root))
        env_root = os.getenv("JY_SKILL_ROOT", "").strip()
        if env_root:
            candidates.append(Path(env_root))
        if repo_root:
            repo = Path(repo_root).resolve()
            candidates.extend(
                (
                    repo / "skills" / "jianying-editor-skill",
                    repo / ".skills" / "jianying-editor-skill",
                )
            )
        candidates.append(Path.home() / "Desktop" / "jianying-editor-skill")

        attempted: list[str] = []
        for candidate in _deduplicate(candidates):
            attempted.append(candidate.as_posix())
            if (candidate / "scripts" / "jy_wrapper.py").is_file():
                return cls(candidate)
        raise FileNotFoundError(
            "jianying-editor-skill not found; set JY_SKILL_ROOT or pass "
            f"--jianying-skill-root. attempted={attempted}"
        )

    def _validate_layout(self) -> str:
        required = (
            self.root / "SKILL.md",
            self.root / "VERSION",
            self.scripts_root / "jy_wrapper.py",
            self.scripts_root / "vendor" / "pyJianYingDraft" / "__init__.py",
        )
        missing = [path.relative_to(self.root).as_posix() for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"incomplete jianying skill installation: {missing}")
        version = (self.root / "VERSION").read_text(encoding="utf-8-sig").strip()
        if _version_tuple(version) < MINIMUM_SKILL_VERSION:
            minimum = ".".join(str(part) for part in MINIMUM_SKILL_VERSION)
            raise RuntimeError(f"jianying skill {version} is older than required {minimum}")
        return version

    def load_modules(self) -> tuple[Any, Any]:
        global _LOADED_MODULES, _LOADED_ROOT
        with _IMPORT_LOCK:
            if _LOADED_MODULES is not None:
                if _LOADED_ROOT != self.root:
                    raise RuntimeError(
                        "a different jianying skill root is already loaded in this process: "
                        f"{_LOADED_ROOT}"
                    )
                return _LOADED_MODULES

            scripts_value = str(self.scripts_root)
            if scripts_value not in sys.path:
                sys.path.insert(0, scripts_value)
            wrapper = importlib.import_module("jy_wrapper")
            draft = importlib.import_module("pyJianYingDraft")
            _LOADED_ROOT = self.root
            _LOADED_MODULES = (wrapper, draft)
            return _LOADED_MODULES

    def probe(self, *, import_modules: bool = True) -> JianyingSkillCapabilities:
        wrapper: Any | None = None
        draft: Any | None = None
        if import_modules:
            wrapper, draft = self.load_modules()

        jy_project = getattr(wrapper, "JyProject", None) if wrapper else None
        capability_material = {
            "version": self.version,
            "jy_wrapper_sha256": self._sha256(self.scripts_root / "jy_wrapper.py"),
            "pyjianyingdraft_sha256": self._sha256(
                self.scripts_root / "vendor" / "pyJianYingDraft" / "__init__.py"
            ),
        }
        digest = hashlib.sha256(
            repr(sorted(capability_material.items())).encode("utf-8")
        ).hexdigest()
        return JianyingSkillCapabilities(
            version=self.version,
            capability_sha256=digest,
            draft_creation=bool(jy_project and hasattr(jy_project, "save")),
            native_transitions=bool(draft and getattr(draft, "TransitionType", None)),
            native_clip_animations=bool(draft and getattr(draft, "IntroType", None)),
            rich_subtitles=bool(jy_project and hasattr(jy_project, "add_rich_text")),
            audio_tracks=bool(jy_project and hasattr(jy_project, "add_audio_safe")),
            screen_recording_tools=(
                (self.root / "tools" / "recording" / "recorder.py").is_file()
                and (self.scripts_root / "web_recorder.py").is_file()
            ),
            auto_export_tool_present=(self.scripts_root / "auto_exporter.py").is_file(),
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

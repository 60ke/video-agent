"""Production-facing Jianying draft backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapter import JianyingDraftAdapter, MotionBackend, write_manifest
from .compiler import compile_jianying_blueprint
from .runtime import JianyingSkillRuntime


@dataclass(frozen=True)
class JianyingBackendResult:
    blueprint_path: Path
    manifest_path: Path
    draft_path: Path
    project_name: str
    skill_version: str
    capability_sha256: str


class JianyingEditorBackend:
    """Compile a frozen timeline and execute it through the external Skill."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        skill_root: str | Path | None = None,
        drafts_root: str | Path | None = None,
        motion_backend: MotionBackend = "jianying_native",
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.runtime = JianyingSkillRuntime.discover(
            explicit_root=skill_root,
            repo_root=self.repo_root,
        )
        self.drafts_root = Path(drafts_root).resolve() if drafts_root else None
        self.motion_backend = motion_backend

    def build_from_timeline(
        self,
        *,
        resolved_timeline_path: str | Path,
        output_dir: str | Path,
        project_name: str | None = None,
    ) -> JianyingBackendResult:
        output_root = Path(output_dir).resolve()
        capabilities = self.runtime.probe(import_modules=True)
        required = {
            "draft_creation": capabilities.draft_creation,
            "native_transitions": capabilities.native_transitions,
            "native_clip_animations": capabilities.native_clip_animations,
            "rich_subtitles": capabilities.rich_subtitles,
            "audio_tracks": capabilities.audio_tracks,
        }
        unavailable = [name for name, available in required.items() if not available]
        if unavailable:
            raise RuntimeError(f"jianying skill is missing required capabilities: {unavailable}")

        blueprint, blueprint_path = compile_jianying_blueprint(
            resolved_timeline_path,
            output_root,
        )
        name = project_name or f"video-agent_{blueprint.case_id}_{blueprint.run_id}"
        adapter = JianyingDraftAdapter(
            runtime=self.runtime,
            drafts_root=self.drafts_root,
        )
        manifest: dict[str, Any] = adapter.build(
            blueprint,
            blueprint_root=output_root,
            project_name=name,
            motion_backend=self.motion_backend,
        )
        manifest.update(
            {
                "editor_backend": "jianying",
                "skill_version": capabilities.version,
                "skill_capabilities": capabilities.as_dict(),
                "edit_blueprint_path": blueprint_path.relative_to(output_root).as_posix(),
            }
        )
        manifest_path = write_manifest(
            manifest,
            output_root / "jianying_project_manifest.json",
        )
        return JianyingBackendResult(
            blueprint_path=blueprint_path,
            manifest_path=manifest_path,
            draft_path=Path(manifest["draft_path"]),
            project_name=name,
            skill_version=capabilities.version,
            capability_sha256=capabilities.capability_sha256,
        )

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from video_agent.ai_runtime import AIRuntimeSession
from video_agent.assets.v4 import AssetQuery
from video_agent.contracts.v4 import FrozenNarration
from video_agent.io import sha256_json, utc_now, write_json_atomic
from video_agent.progress import get_logger
from video_agent.registries import CapabilityRegistryHub, project_registry_hub
from video_agent.runtime import RunContext
from video_agent.semantic import classify_video_scope, plan_scene_semantics
from video_agent.semantic.goal_narration import generate_goal_narration, goal_input_fingerprint
from video_agent.semantic.registry_payload import scene_material_availability_payload
from video_agent.speech.v4.narration_freeze import (
    freeze_goal_narration,
    freeze_script_narration,
    resolve_script_text,
    write_frozen_narration,
)
from video_agent.speech.v4.tts import ensure_native_speech_timing_lock
from video_agent.speech.v4.voice_resolve import resolve_fixed_voice_profile
from video_agent.v4.stage4 import V4Stage4Result, V4Stage4Runner, open_v4_repository
from video_agent.v4.stage5 import V4Stage5Result, V4Stage5Runner
from video_agent.v4.stage6 import V4Stage6Result, V4Stage6Runner
from video_agent.v4.stage6 import EditorBackend


logger = get_logger()
T = TypeVar("T")


@dataclass(frozen=True)
class V4Stage1Result:
    frozen_narration: Path
    timing_lock: Path
    video_scope: Path
    scene_semantic_plan: Path
    registry_snapshot: Path
    registry_projection: Path


async def run_fixed_voice_frontend(
    *,
    speech_job: Callable[[], Path],
    scope_job: Awaitable[T],
) -> tuple[Path, T]:
    speech_task = asyncio.create_task(asyncio.to_thread(speech_job))
    scope_task = asyncio.ensure_future(scope_job)
    try:
        speech_result, scope_result = await asyncio.gather(speech_task, scope_task)
    except BaseException:
        speech_task.cancel()
        scope_task.cancel()
        await asyncio.gather(speech_task, scope_task, return_exceptions=True)
        raise
    return speech_result, scope_result


class V4Orchestrator:
    """V4 orchestrator for completed stage entrypoints."""

    def __init__(self, context: RunContext) -> None:
        self.context = context

    def run_stage1(self) -> V4Stage1Result:
        return asyncio.run(self._run_stage1())

    def run_stage4(
        self,
        *,
        run_seed: str = "default",
        allow_fake_derivation: bool = False,
        db: Path | None = None,
        object_root: Path | None = None,
    ) -> V4Stage4Result:
        return V4Stage4Runner(self.context).run(
            run_seed=run_seed,
            allow_fake_derivation=allow_fake_derivation,
            db=db,
            object_root=object_root,
        )

    def run_stage5(
        self,
        *,
        run_seed: str = "default",
        sfx_profile_id: str = "normal",
    ) -> V4Stage5Result:
        return V4Stage5Runner(self.context).run(
            run_seed=run_seed,
            sfx_profile_id=sfx_profile_id,
        )

    def run_stage6(
        self,
        *,
        phase: str | None = None,
        postroll_frames: int = 0,
        object_root: Path | None = None,
        render: bool = False,
        skip_ffmpeg: bool = False,
        editor_backend: EditorBackend = "remotion",
        jianying_skill_root: Path | None = None,
        jianying_drafts_root: Path | None = None,
    ) -> V4Stage6Result:
        return V4Stage6Runner(self.context).run(
            phase=phase,
            postroll_frames=postroll_frames,
            object_root=object_root,
            render=render,
            skip_ffmpeg=skip_ffmpeg,
            editor_backend=editor_backend,
            jianying_skill_root=jianying_skill_root,
            jianying_drafts_root=jianying_drafts_root,
        )

    def _input_mode(self) -> str:
        case = self.context.case
        if case.mode == "script_locked" or case.narration_source:
            return "script"
        return "goal"

    async def _ensure_frozen_narration(self, gateway: object) -> FrozenNarration:
        frozen_path = self.context.artifact("frozen_narration.json")
        if frozen_path.is_file():
            from video_agent.io import load_model

            return load_model(frozen_path, FrozenNarration)

        mode = self._input_mode()
        agents_dir = self.context.run_dir / "agents"
        if mode == "script":
            text, raw = resolve_script_text(
                self.context.case_dir,
                narration_source=self.context.case.narration_source,
            )
            frozen = freeze_script_narration(text=text, source_bytes=raw)
            # Persist canonical script copy when missing.
            source_script = self.context.case_dir / "input" / "source_script.txt"
            if not source_script.is_file():
                source_script.parent.mkdir(parents=True, exist_ok=True)
                source_script.write_text(frozen.text + "\n", encoding="utf-8")
        else:
            goal = self.context.case.goal.strip()
            response, invocation = await generate_goal_narration(
                gateway=gateway,  # type: ignore[arg-type]
                repo_root=self.context.repo_root,
                run_id=self.context.run_id,
                goal=goal,
                trace_dir=agents_dir / "00_goal_narration",
            )
            write_json_atomic(
                self.context.artifact("goal_narration.response.json"),
                response,
            )
            write_json_atomic(
                self.context.artifact("goal_narration.input_fingerprint.json"),
                {"fingerprint": goal_input_fingerprint(goal), "goal": goal},
            )
            frozen = freeze_goal_narration(
                spoken_text=response.spoken_text,
                goal=goal,
                response_fingerprint=invocation.request_fingerprint,
            )
        write_frozen_narration(frozen_path, frozen)
        return frozen

    async def _run_stage1(self) -> V4Stage1Result:
        started = time.perf_counter()
        registry_hub = CapabilityRegistryHub.load(self.context.repo_root / "config" / "registries" / "v4")
        registry_snapshot_path = self.context.artifact("capability_registry.snapshot.json")
        registry_snapshot = registry_hub.freeze(registry_snapshot_path)
        registry = project_registry_hub(registry_hub)
        registry_projection_path = self.context.artifact("capability_registry.stage1.json")
        write_json_atomic(registry_projection_path, registry)

        case_voice = self.context.case.voice
        resolved_voice = resolve_fixed_voice_profile(
            registry_hub,
            repo_root=self.context.repo_root,
            voice_profile_id=case_voice.voice_profile_id,
            speed_override=case_voice.speed if case_voice.voice_profile_id is not None else None,
            emotion_override=case_voice.emotion,
            registry_snapshot_id=registry_snapshot.snapshot_id,
        )
        resolved_voice_path = self.context.artifact("resolved_voice_profile.json")
        write_json_atomic(resolved_voice_path, resolved_voice)

        agents_dir = self.context.run_dir / "agents"
        async with AIRuntimeSession(self.context.repo_root) as gateway:
            frozen = await self._ensure_frozen_narration(gateway)
            frozen_path = self.context.artifact("frozen_narration.json")
            narration_sha256 = sha256_json({"text": frozen.text})

            timing_path, scope_result = await run_fixed_voice_frontend(
                speech_job=lambda: ensure_native_speech_timing_lock(
                    case_id=self.context.case.case_id,
                    run_id=self.context.run_id,
                    run_dir=self.context.run_dir,
                    repo_root=self.context.repo_root,
                    frozen_text=frozen.text,
                    narration_sha256=narration_sha256,
                    voice_profile=resolved_voice,
                    fps=int(self.context.case.format.fps),
                ),
                scope_job=classify_video_scope(
                    gateway=gateway,
                    repo_root=self.context.repo_root,
                    run_id=self.context.run_id,
                    frozen_narration=frozen.text,
                    registry=registry,
                    trace_dir=agents_dir / "01_scope_classifier",
                ),
            )
            scope_envelope, scope_invocation = scope_result
            scope_path = self.context.artifact("video_scope.json")
            write_json_atomic(scope_path, scope_envelope)
            repository = open_v4_repository(self.context.repo_root, registry=registry_hub)
            try:
                material_availability = scene_material_availability_payload(
                    repository.query_assets(AssetQuery())
                )
            finally:
                repository.close()
            material_availability_path = self.context.artifact("material_availability.stage1.json")
            write_json_atomic(material_availability_path, material_availability)
            scene_envelope, scene_invocation = await plan_scene_semantics(
                gateway=gateway,
                repo_root=self.context.repo_root,
                run_id=self.context.run_id,
                frozen_narration=frozen.text,
                video_scope=scope_envelope.payload,
                registry=registry,
                trace_dir=agents_dir / "02_scene_semantics",
                material_availability=material_availability,
            )

        scene_path = self.context.artifact("scene_semantic_plan.json")
        write_json_atomic(scene_path, scene_envelope)
        write_json_atomic(
            self.context.artifact("v4_stage1_manifest.json"),
            {
                "schema_version": "v4.stage1_manifest.1",
                "case_id": self.context.case.case_id,
                "run_id": self.context.run_id,
                "status": "validated",
                "completed_at": utc_now(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "parallel_frontend": True,
                "input_mode": self._input_mode(),
                "legacy_orchestrator": False,
                "scope_replayed": scope_invocation.replayed,
                "scene_replayed": scene_invocation.replayed,
                "outputs": {
                    "frozen_narration": frozen_path.relative_to(self.context.run_dir).as_posix(),
                    "speech_timing_lock": timing_path.relative_to(self.context.run_dir).as_posix(),
                    "video_scope": scope_path.relative_to(self.context.run_dir).as_posix(),
                    "scene_semantic_plan": scene_path.relative_to(self.context.run_dir).as_posix(),
                    "registry_snapshot": registry_snapshot_path.relative_to(self.context.run_dir).as_posix(),
                    "registry_projection": registry_projection_path.relative_to(self.context.run_dir).as_posix(),
                    "material_availability": material_availability_path.relative_to(self.context.run_dir).as_posix(),
                    "resolved_voice_profile": resolved_voice_path.relative_to(self.context.run_dir).as_posix(),
                },
            },
        )
        logger.info(
            "[V4][Stage1] 完成 case=%s run=%s elapsed=%.2fs native_speech=1",
            self.context.case.case_id,
            self.context.run_id,
            time.perf_counter() - started,
        )
        return V4Stage1Result(
            frozen_narration=frozen_path,
            timing_lock=timing_path,
            video_scope=scope_path,
            scene_semantic_plan=scene_path,
            registry_snapshot=registry_snapshot_path,
            registry_projection=registry_projection_path,
        )

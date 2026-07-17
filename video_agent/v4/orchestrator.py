from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from video_agent.ai_runtime import AIRuntimeSession
from video_agent.contracts import Narration
from video_agent.contracts.v4 import FrozenNarration
from video_agent.io import load_model, sha256_json, utc_now, write_json_atomic
from video_agent.orchestrator import Orchestrator as LegacyOrchestrator
from video_agent.progress import get_logger
from video_agent.registries import load_bootstrap_registry
from video_agent.runtime import RunContext
from video_agent.semantic import classify_video_scope, plan_scene_semantics


logger = get_logger()
T = TypeVar("T")


@dataclass(frozen=True)
class V4Stage1Result:
    frozen_narration: Path
    timing_lock: Path
    video_scope: Path
    scene_semantic_plan: Path
    registry_snapshot: Path


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
    """V4 semantic frontend while later V4 stages are still being implemented."""

    def __init__(self, context: RunContext) -> None:
        self.context = context

    def run_stage1(self) -> V4Stage1Result:
        return asyncio.run(self._run_stage1())

    async def _run_stage1(self) -> V4Stage1Result:
        started = time.perf_counter()
        legacy = LegacyOrchestrator(self.context)
        catalog_path = self.context.artifact("asset_catalog.source.json")
        narration_path = self.context.artifact("narration.json")
        if not catalog_path.is_file():
            legacy.stage_catalog()
        if not narration_path.is_file():
            legacy.stage_narration()

        narration = load_model(narration_path, Narration)
        frozen = FrozenNarration(
            text=narration.spoken_text,
            source=self.context.case.mode,
            source_fingerprint=f"sha256:{sha256_json(narration)}",
        )
        frozen_path = self.context.artifact("frozen_narration.json")
        write_json_atomic(frozen_path, frozen)

        registry = load_bootstrap_registry(self.context.repo_root)
        registry_path = self.context.artifact("capability_registry.stage1.json")
        write_json_atomic(registry_path, registry)
        agents_dir = self.context.run_dir / "agents"

        async with AIRuntimeSession(self.context.repo_root) as gateway:
            timing_path, scope_result = await run_fixed_voice_frontend(
                speech_job=lambda: self._ensure_speech(legacy),
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
            scene_envelope, scene_invocation = await plan_scene_semantics(
                gateway=gateway,
                repo_root=self.context.repo_root,
                run_id=self.context.run_id,
                frozen_narration=frozen.text,
                video_scope=scope_envelope.payload,
                registry=registry,
                trace_dir=agents_dir / "02_scene_semantics",
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
                "scope_replayed": scope_invocation.replayed,
                "scene_replayed": scene_invocation.replayed,
                "outputs": {
                    "frozen_narration": frozen_path.relative_to(self.context.run_dir).as_posix(),
                    "timing_lock": timing_path.relative_to(self.context.run_dir).as_posix(),
                    "video_scope": scope_path.relative_to(self.context.run_dir).as_posix(),
                    "scene_semantic_plan": scene_path.relative_to(self.context.run_dir).as_posix(),
                    "registry_snapshot": registry_path.relative_to(self.context.run_dir).as_posix(),
                },
            },
        )
        logger.info(
            "[V4][Stage1] 完成 case=%s run=%s elapsed=%.2fs",
            self.context.case.case_id,
            self.context.run_id,
            time.perf_counter() - started,
        )
        return V4Stage1Result(
            frozen_narration=frozen_path,
            timing_lock=timing_path,
            video_scope=scope_path,
            scene_semantic_plan=scene_path,
            registry_snapshot=registry_path,
        )

    def _ensure_speech(self, legacy: LegacyOrchestrator) -> Path:
        timing_path = self.context.artifact("timing_lock.json")
        return timing_path if timing_path.is_file() else legacy.stage_speech()

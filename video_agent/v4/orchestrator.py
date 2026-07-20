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
from video_agent.registries import CapabilityRegistryHub, project_registry_hub
from video_agent.runtime import RunContext
from video_agent.semantic import classify_video_scope, plan_scene_semantics
from video_agent.speech.v4.voice_resolve import (
    apply_resolved_voice_to_case_voice,
    resolve_fixed_voice_profile,
)
from video_agent.v4.stage4 import V4Stage4Result, V4Stage4Runner
from video_agent.v4.stage5 import V4Stage5Result, V4Stage5Runner
from video_agent.v4.stage6 import V4Stage6Result, V4Stage6Runner


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
    ) -> V4Stage6Result:
        return V4Stage6Runner(self.context).run(
            phase=phase,
            postroll_frames=postroll_frames,
            object_root=object_root,
            render=render,
            skip_ffmpeg=skip_ffmpeg,
        )

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
        voice_payload = apply_resolved_voice_to_case_voice(
            case_voice.model_dump(mode="json"),
            resolved_voice,
            repo_root=self.context.repo_root,
        )
        self.context.case = self.context.case.model_copy(
            update={"voice": case_voice.model_validate(voice_payload)}
        )
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
                    "speech_timing_lock": timing_path.relative_to(self.context.run_dir).as_posix(),
                    "video_scope": scope_path.relative_to(self.context.run_dir).as_posix(),
                    "scene_semantic_plan": scene_path.relative_to(self.context.run_dir).as_posix(),
                    "registry_snapshot": registry_snapshot_path.relative_to(self.context.run_dir).as_posix(),
                    "registry_projection": registry_projection_path.relative_to(self.context.run_dir).as_posix(),
                    "resolved_voice_profile": resolved_voice_path.relative_to(self.context.run_dir).as_posix(),
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
            registry_snapshot=registry_snapshot_path,
            registry_projection=registry_projection_path,
        )

    def _ensure_speech(self, legacy: LegacyOrchestrator) -> Path:
        speech_path = self.context.artifact("speech_timing_lock.json")
        if speech_path.is_file():
            return speech_path

        from video_agent.contracts import TimingLock
        from video_agent.contracts.v4 import ResolvedVoiceProfile, SpeechBeatSpanV4, SpeechTimingLock, SpeechTokenTimingV4
        from video_agent.io import sha256_file
        from video_agent.timing.v4.speech_lock import voice_profile_content_sha256
        from video_agent.timing.v4.timebase import duration_frames, ms_to_hit_frame, ms_to_interval_end

        timing_path = self.context.artifact("timing_lock.json")
        if not timing_path.is_file():
            timing_path = legacy.stage_speech()
        timing = load_model(timing_path, TimingLock)
        voice_path = self.context.artifact("resolved_voice_profile.json")
        if not voice_path.is_file():
            raise FileNotFoundError("resolved_voice_profile.json required before SpeechTimingLock")
        voice = load_model(voice_path, ResolvedVoiceProfile)

        # Project V3 TimingLock voice facts only — never carry phrase_anchors forward.
        tokens: list[SpeechTokenTimingV4] = []
        for index, token in enumerate(timing.tokens):
            start_frame = ms_to_hit_frame(token.start_ms, timing.fps)
            end_frame = max(start_frame + 1, ms_to_interval_end(token.end_ms, timing.fps))
            tokens.append(
                SpeechTokenTimingV4(
                    token_id=f"tok_{index:04d}",
                    text=token.text,
                    start_ms=token.start_ms,
                    end_ms=token.end_ms,
                    start_frame=start_frame,
                    end_frame=end_frame,
                    beat_id=None,
                )
            )
        frames = max(duration_frames(timing.duration_ms, timing.fps), tokens[-1].end_frame if tokens else 0)
        audio_object_key = "audio/speech.wav"
        audio_src = Path(timing.audio_path)
        if not audio_src.is_file():
            audio_src = self.context.run_dir / timing.audio_path
        audio_dest = self.context.run_dir / audio_object_key
        audio_dest.parent.mkdir(parents=True, exist_ok=True)
        if audio_src.is_file() and audio_src.resolve() != audio_dest.resolve():
            import shutil

            shutil.copy2(audio_src, audio_dest)
        elif not audio_dest.is_file() and audio_src.is_file():
            import shutil

            shutil.copy2(audio_src, audio_dest)

        speech = SpeechTimingLock(
            schema_version=1,
            case_id=self.context.case.case_id,
            run_id=self.context.run_id,
            narration_sha256=sha256_json(load_model(self.context.artifact("narration.json"), Narration)),
            audio_object_key=audio_object_key,
            audio_sha256=sha256_file(audio_dest if audio_dest.is_file() else audio_src),
            voice_profile_id=voice.profile_id,
            voice_profile_version=voice.profile_version,
            voice_profile_sha256=voice_profile_content_sha256(voice),
            fps=timing.fps,
            duration_ms=timing.duration_ms,
            duration_frames=frames,
            tokens=tokens,
            pause_events=[],
            beat_spans=[
                SpeechBeatSpanV4(
                    beat_id="speech_full",
                    token_ids=[token.token_id for token in tokens],
                    start_frame=tokens[0].start_frame if tokens else 0,
                    end_frame=frames,
                )
            ],
        )
        write_json_atomic(speech_path, speech)
        return speech_path

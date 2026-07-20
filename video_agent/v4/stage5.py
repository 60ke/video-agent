from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    FrozenRegistrySnapshot,
    MotionAudioPlan,
    ResolvedAssetPlan,
    SpeechTimingLock,
)
from video_agent.io import load_json, load_model, sha256_file, sha256_json, utc_now, write_json_atomic
from video_agent.motion.v4.planner import MotionAudioPlanner
from video_agent.progress import get_logger
from video_agent.registries import CapabilityRegistryHub
from video_agent.runtime import RunContext
from video_agent.timing.v4.anchor_compiler import build_anchored_timing_plan
from video_agent.v4.stage4 import load_scene_semantic_plan


logger = get_logger()


@dataclass(frozen=True)
class V4Stage5Result:
    motion_audio_plan: Path
    manifest: Path
    anchored_timing_plan: Path


class V4Stage5Runner:
    def __init__(self, context: RunContext) -> None:
        self.context = context

    def run(
        self,
        *,
        run_seed: str = "default",
        sfx_profile_id: str = "normal",
    ) -> V4Stage5Result:
        started = time.perf_counter()
        scene_path = self.context.artifact("scene_semantic_plan.json")
        resolved_path = self.context.artifact("resolved_asset_plan.json")
        speech_path = self.context.artifact("speech_timing_lock.json")
        registry_snapshot = self.context.artifact("capability_registry.snapshot.json")

        for path, label in (
            (scene_path, "scene_semantic_plan.json"),
            (resolved_path, "resolved_asset_plan.json"),
            (speech_path, "speech_timing_lock.json"),
            (registry_snapshot, "capability_registry.snapshot.json"),
        ):
            if not path.is_file():
                raise FileNotFoundError(f"Stage5 requires {label}: {path}")

        scene_plan = load_scene_semantic_plan(scene_path)
        resolved = ResolvedAssetPlan.model_validate(load_json(resolved_path))
        speech = load_model(speech_path, SpeechTimingLock)
        frozen_registry = load_model(registry_snapshot, FrozenRegistrySnapshot)
        registry = CapabilityRegistryHub.from_snapshot(frozen_registry)

        anchored_path = self.context.artifact("anchored_timing_plan.json")
        if anchored_path.is_file():
            anchored = load_model(anchored_path, AnchoredTimingPlan)
        else:
            anchored = build_anchored_timing_plan(
                case_id=self.context.case.case_id,
                run_id=self.context.run_id,
                narration_sha256=speech.narration_sha256,
                speech=speech,
                scene_plan=scene_plan,
            )
            write_json_atomic(anchored_path, anchored)

        plan = MotionAudioPlanner(registry, sfx_profile_id=sfx_profile_id).build(
            scene_plan=scene_plan,
            resolved_assets=resolved,
            anchored_timing=anchored,
            run_seed=run_seed,
            registry_snapshot_id=frozen_registry.snapshot_id,
            scene_plan_sha256=sha256_json(scene_plan),
            resolved_asset_plan_sha256=sha256_file(resolved_path),
            speech_timing_lock_sha256=sha256_file(speech_path),
            anchored_timing_plan_sha256=sha256_json(anchored),
        )

        plan_path = self.context.artifact("motion_audio_plan.json")
        manifest_path = self.context.artifact("v4_stage5_manifest.json")
        write_json_atomic(plan_path, plan)
        fingerprint = {
            "scene_plan_sha256": sha256_json(scene_plan),
            "resolved_asset_plan_sha256": sha256_file(resolved_path),
            "speech_timing_lock_sha256": sha256_file(speech_path),
            "anchored_timing_plan_sha256": sha256_json(anchored),
            "registry_snapshot_id": frozen_registry.snapshot_id,
            "registry_snapshot_file_sha256": sha256_file(registry_snapshot),
            "run_seed": run_seed,
            "sfx_profile_id": sfx_profile_id,
        }
        write_json_atomic(
            manifest_path,
            {
                "schema_version": "v4.stage5_manifest.1",
                "case_id": self.context.case.case_id,
                "run_id": self.context.run_id,
                "status": "planned",
                "completed_at": utc_now(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "run_seed": run_seed,
                "input_fingerprint": sha256_json(fingerprint),
                "input_fingerprint_components": fingerprint,
                "outputs": {
                    "anchored_timing_plan": anchored_path.relative_to(self.context.run_dir).as_posix(),
                    "motion_audio_plan": plan_path.relative_to(self.context.run_dir).as_posix(),
                },
            },
        )
        logger.info(
            "[V4][Stage5] 完成 case=%s run=%s scenes=%s sfx=%s elapsed=%.2fs",
            self.context.case.case_id,
            self.context.run_id,
            len(plan.scenes),
            len(plan.sfx_intents),
            time.perf_counter() - started,
        )
        return V4Stage5Result(
            motion_audio_plan=plan_path,
            manifest=manifest_path,
            anchored_timing_plan=anchored_path,
        )


def load_motion_audio_plan(path: Path) -> MotionAudioPlan:
    return MotionAudioPlan.model_validate(load_json(path))

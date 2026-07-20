from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    MotionAudioPlan,
    ResolvedAssetPlan,
    SceneSemanticPlan,
)
from video_agent.contracts.v4.motion_audio import validate_motion_audio_plan
from video_agent.io import sha256_file, sha256_json, write_json_atomic
from video_agent.registries import CapabilityRegistryHub

from .assignment import assign_scene_motion
from .sfx_intents import emit_sfx_intents


@dataclass(frozen=True)
class MotionAudioPlanner:
    registry: CapabilityRegistryHub
    sfx_profile_id: str = "normal"

    def build(
        self,
        *,
        scene_plan: SceneSemanticPlan,
        resolved_assets: ResolvedAssetPlan,
        anchored_timing: AnchoredTimingPlan,
        run_seed: str,
        registry_snapshot_id: str,
        scene_plan_sha256: str | None = None,
        resolved_asset_plan_sha256: str | None = None,
        speech_timing_lock_sha256: str | None = None,
        anchored_timing_plan_sha256: str | None = None,
    ) -> MotionAudioPlan:
        if not anchored_timing_plan_sha256:
            anchored_timing_plan_sha256 = sha256_json(anchored_timing)
        if anchored_timing_plan_sha256 == ("0" * 64):
            raise ValueError("anchored_timing_plan_sha256 placeholder is forbidden")
        scenes = assign_scene_motion(
            scene_plan,
            resolved_assets,
            anchored_timing,
            registry=self.registry,
            run_seed=run_seed,
        )
        sfx_intents, profile_ref = emit_sfx_intents(
            scene_plan,
            scenes,
            registry=self.registry,
            profile_id=self.sfx_profile_id,
        )
        plan = MotionAudioPlan(
            schema_version=1,
            run_seed=run_seed,
            scene_plan_sha256=scene_plan_sha256 or sha256_json(scene_plan),
            resolved_asset_plan_sha256=resolved_asset_plan_sha256 or sha256_json(resolved_assets),
            speech_timing_lock_sha256=speech_timing_lock_sha256
            or anchored_timing.speech_timing_lock_sha256,
            anchored_timing_plan_sha256=anchored_timing_plan_sha256,
            registry_snapshot_id=registry_snapshot_id,
            scenes=scenes,
            sfx_profile=profile_ref,
            sfx_intents=sfx_intents,
        )
        validate_motion_audio_plan(plan, scene_plan)
        return plan


def build_motion_audio_plan(
    *,
    registry: CapabilityRegistryHub,
    scene_plan: SceneSemanticPlan,
    resolved_assets: ResolvedAssetPlan,
    anchored_timing: AnchoredTimingPlan,
    run_seed: str,
    registry_snapshot_id: str,
    sfx_profile_id: str = "normal",
    scene_plan_sha256: str | None = None,
    resolved_asset_plan_sha256: str | None = None,
    speech_timing_lock_sha256: str | None = None,
    anchored_timing_plan_sha256: str | None = None,
) -> MotionAudioPlan:
    return MotionAudioPlanner(registry, sfx_profile_id=sfx_profile_id).build(
        scene_plan=scene_plan,
        resolved_assets=resolved_assets,
        anchored_timing=anchored_timing,
        run_seed=run_seed,
        registry_snapshot_id=registry_snapshot_id,
        scene_plan_sha256=scene_plan_sha256,
        resolved_asset_plan_sha256=resolved_asset_plan_sha256,
        speech_timing_lock_sha256=speech_timing_lock_sha256,
        anchored_timing_plan_sha256=anchored_timing_plan_sha256,
    )


def write_motion_audio_plan(path: Path, plan: MotionAudioPlan) -> Path:
    write_json_atomic(path, plan)
    return path


def timing_lock_sha256(path: Path) -> str:
    return sha256_file(path)

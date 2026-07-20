"""V4 Stage6 runner: anchor + compile-render phases."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from video_agent.compiler.v4 import compile_video_timeline
from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    AssetRepositorySnapshot,
    FrozenRegistrySnapshot,
    MotionAudioPlan,
    ResolvedAssetPlan,
    SpeechTimingLock,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.io import load_json, load_model, sha256_file, sha256_json, utc_now, write_json_atomic
from video_agent.progress import get_logger
from video_agent.registries import CapabilityRegistryHub
from video_agent.render.v4 import export_remotion_timeline, mix_compiled_audio, resolve_materials
from video_agent.render.v4.remotion_render import render_v4_silent_mp4
from video_agent.runtime import RunContext
from video_agent.timing.v4.anchor_compiler import build_anchored_timing_plan
from video_agent.v4.stage4 import load_scene_semantic_plan
from video_agent.v4.stage6_fingerprint import build_stage6_fingerprint_components


logger = get_logger()


@dataclass(frozen=True)
class V4Stage6Result:
    phase: str
    anchored_timing_plan: Path | None
    compiled_timeline: Path | None
    remotion_timeline: Path | None
    final_video: Path | None
    manifest: Path


class V4Stage6Runner:
    def __init__(self, context: RunContext) -> None:
        self.context = context

    def run(
        self,
        *,
        phase: str | None = None,
        postroll_frames: int = 0,
        object_root: Path | None = None,
        render: bool = False,
        skip_ffmpeg: bool = False,
    ) -> V4Stage6Result:
        if phase in (None, "anchor"):
            anchor_result = self.run_anchor()
            if phase == "anchor":
                return anchor_result
        return self.run_compile_render(
            postroll_frames=postroll_frames,
            object_root=object_root,
            render=render if phase in (None, "compile-render") else False,
            skip_ffmpeg=skip_ffmpeg,
        )

    def run_anchor(self) -> V4Stage6Result:
        started = time.perf_counter()
        scene_path = self.context.artifact("scene_semantic_plan.json")
        speech_path = self.context.artifact("speech_timing_lock.json")
        for path, label in ((scene_path, "scene_semantic_plan.json"), (speech_path, "speech_timing_lock.json")):
            if not path.is_file():
                raise FileNotFoundError(f"Stage6 anchor requires {label}: {path}")

        scene_plan = load_scene_semantic_plan(scene_path)
        speech = load_model(speech_path, SpeechTimingLock)
        anchored = build_anchored_timing_plan(
            case_id=self.context.case.case_id,
            run_id=self.context.run_id,
            narration_sha256=speech.narration_sha256,
            speech=speech,
            scene_plan=scene_plan,
        )
        anchored_path = self.context.artifact("anchored_timing_plan.json")
        write_json_atomic(anchored_path, anchored)
        fingerprint = build_stage6_fingerprint_components(
            repo_root=self.context.repo_root,
            base={
                "speech_timing_lock_sha256": sha256_file(speech_path),
                "scene_plan_sha256": sha256_json(scene_plan),
                "anchored_timing_plan_sha256": sha256_json(anchored),
            },
        )
        manifest_path = self.context.artifact("v4_stage6_anchor_manifest.json")
        write_json_atomic(
            manifest_path,
            {
                "schema_version": "v4.stage6_anchor_manifest.1",
                "case_id": self.context.case.case_id,
                "run_id": self.context.run_id,
                "phase": "anchor",
                "status": "anchored",
                "completed_at": utc_now(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "input_fingerprint": sha256_json(fingerprint),
                "input_fingerprint_components": fingerprint,
                "outputs": {
                    "anchored_timing_plan": anchored_path.relative_to(self.context.run_dir).as_posix(),
                },
            },
        )
        logger.info("[V4][Stage6][anchor] done case=%s run=%s", self.context.case.case_id, self.context.run_id)
        return V4Stage6Result(
            phase="anchor",
            anchored_timing_plan=anchored_path,
            compiled_timeline=None,
            remotion_timeline=None,
            final_video=None,
            manifest=manifest_path,
        )

    def run_compile_render(
        self,
        *,
        postroll_frames: int = 0,
        object_root: Path | None = None,
        render: bool = False,
        skip_ffmpeg: bool = False,
    ) -> V4Stage6Result:
        started = time.perf_counter()
        required = {
            "scene_semantic_plan.json": self.context.artifact("scene_semantic_plan.json"),
            "speech_timing_lock.json": self.context.artifact("speech_timing_lock.json"),
            "anchored_timing_plan.json": self.context.artifact("anchored_timing_plan.json"),
            "resolved_asset_plan.json": self.context.artifact("resolved_asset_plan.json"),
            "motion_audio_plan.json": self.context.artifact("motion_audio_plan.json"),
            "capability_registry.snapshot.json": self.context.artifact("capability_registry.snapshot.json"),
            "used_assets.snapshot.json": self.context.artifact("asset_repository.snapshot.json"),
        }
        missing = [label for label, path in required.items() if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "Stage6 compile-render missing upstream artifacts: " + ", ".join(missing)
            )

        scene_plan = load_scene_semantic_plan(required["scene_semantic_plan.json"])
        speech = load_model(required["speech_timing_lock.json"], SpeechTimingLock)
        anchored = load_model(required["anchored_timing_plan.json"], AnchoredTimingPlan)
        resolved = load_model(required["resolved_asset_plan.json"], ResolvedAssetPlan)
        motion = load_model(required["motion_audio_plan.json"], MotionAudioPlan)
        snapshot = load_model(required["used_assets.snapshot.json"], AssetRepositorySnapshot)
        frozen = load_model(required["capability_registry.snapshot.json"], FrozenRegistrySnapshot)
        registry = CapabilityRegistryHub.from_snapshot(frozen)
        store_root = object_root or (self.context.repo_root / "data" / "object_store")

        # AnchoredTimingPlan is immutable. Effect/SFX intents resolve by phrase to
        # existing slot/operation/claim anchors at compile time — never rewrite.
        _assert_intent_phrases_bound(anchored, motion)

        fingerprint = build_stage6_fingerprint_components(
            repo_root=self.context.repo_root,
            base={
                "speech_timing_lock_sha256": sha256_file(required["speech_timing_lock.json"]),
                "anchored_timing_plan_sha256": sha256_json(anchored),
                "resolved_asset_plan_sha256": sha256_file(required["resolved_asset_plan.json"]),
                "motion_audio_plan_sha256": sha256_file(required["motion_audio_plan.json"]),
                "used_assets_snapshot_id": snapshot.snapshot_id,
                "registry_snapshot_id": frozen.snapshot_id,
                "postroll_frames": postroll_frames,
                "platform_profile_id": "douyin_portrait_v1",
            },
        )
        input_fingerprint_hash = sha256_json(fingerprint)
        manifest_path = self.context.artifact("v4_stage6_manifest.json")
        if manifest_path.is_file():
            previous = load_json(manifest_path)
            rendered_ok = previous.get("status") == "rendered" and (
                self.context.run_dir / "render" / "final.mp4"
            ).is_file()
            silent_ok = previous.get("status") == "rendered_silent" and (
                self.context.run_dir / "render" / "silent.mp4"
            ).is_file()
            if previous.get("input_fingerprint") == input_fingerprint_hash and (rendered_ok or silent_ok):
                logger.info("[V4][Stage6] resume hit fingerprint=%s", input_fingerprint_hash[:12])
                final = self.context.run_dir / "render" / "final.mp4"
                silent = self.context.run_dir / "render" / "silent.mp4"
                return V4Stage6Result(
                    phase="compile-render",
                    anchored_timing_plan=required["anchored_timing_plan.json"],
                    compiled_timeline=self.context.artifact("compiled_video_timeline.json"),
                    remotion_timeline=self.context.run_dir / "render" / "remotion.timeline.json",
                    final_video=final if final.is_file() else silent,
                    manifest=manifest_path,
                )

        timeline, report, sfx_audit = compile_video_timeline(
            case_id=self.context.case.case_id,
            run_id=self.context.run_id,
            speech=speech,
            scene_plan=scene_plan,
            anchored=anchored,
            resolved=resolved,
            motion_plan=motion,
            snapshot=snapshot,
            registry=registry,
            repo_root=self.context.repo_root,
            postroll_frames=postroll_frames,
            object_store_root=store_root,
        )

        timeline_path = self.context.artifact("compiled_video_timeline.json")
        write_json_atomic(timeline_path, timeline)
        write_json_atomic(self.context.artifact("stage6_validation.json"), report)
        write_json_atomic(self.context.artifact("stage6_sfx_audit.json"), {"intents": sfx_audit})

        resolved_timeline = resolve_materials(
            timeline=timeline,
            run_dir=self.context.run_dir,
            object_store_root=store_root,
            repo_root=self.context.repo_root,
        )
        remotion_path = self.context.run_dir / "render" / "remotion.timeline.json"
        export_remotion_timeline(resolved_timeline, remotion_path)

        final_video: Path | None = None
        status = "compiled"
        if render:
            silent = self.context.run_dir / "render" / "silent.mp4"
            render_v4_silent_mp4(
                timeline=resolved_timeline,
                remotion_timeline_path=remotion_path,
                run_render_dir=self.context.run_dir / "render",
                repo_root=self.context.repo_root,
                output=silent,
            )
            if not skip_ffmpeg:
                final_video = self.context.run_dir / "render" / "final.mp4"
                mix_compiled_audio(
                    timeline=resolved_timeline,
                    visual_input=silent,
                    run_render_dir=self.context.run_dir / "render",
                    output=final_video,
                )
                status = "rendered"
            else:
                final_video = silent
                status = "rendered_silent"

        output_fingerprint = {
            "compiled_video_timeline_sha256": sha256_json(timeline),
            "remotion_timeline_sha256": sha256_file(remotion_path),
            "status": status,
        }
        outputs = {
            "compiled_video_timeline": timeline_path.relative_to(self.context.run_dir).as_posix(),
            "remotion_timeline": remotion_path.relative_to(self.context.run_dir).as_posix(),
            "stage6_validation": "stage6_validation.json",
        }
        if final_video is not None:
            outputs["final_video"] = final_video.relative_to(self.context.run_dir).as_posix()
        write_json_atomic(
            manifest_path,
            {
                "schema_version": "v4.stage6_manifest.1",
                "case_id": self.context.case.case_id,
                "run_id": self.context.run_id,
                "phase": "compile-render",
                "status": status,
                "completed_at": utc_now(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000),
                "input_fingerprint": input_fingerprint_hash,
                "input_fingerprint_components": fingerprint,
                "output_fingerprint": sha256_json(output_fingerprint),
                "output_fingerprint_components": output_fingerprint,
                "outputs": outputs,
            },
        )
        logger.info(
            "[V4][Stage6][compile-render] done case=%s run=%s frames=%s status=%s",
            self.context.case.case_id,
            self.context.run_id,
            timeline.frame_count,
            status,
        )
        return V4Stage6Result(
            phase="compile-render",
            anchored_timing_plan=required["anchored_timing_plan.json"],
            compiled_timeline=timeline_path,
            remotion_timeline=remotion_path,
            final_video=final_video,
            manifest=manifest_path,
        )


def _assert_intent_phrases_bound(anchored: AnchoredTimingPlan, motion: MotionAudioPlan) -> None:
    """Fail-loud if Motion/SFX phrases cannot resolve against frozen anchors.

    Does not mutate AnchoredTimingPlan. Intents must reuse phrases already
    bound from slots/operations/claims/no_asset scene text.
    """
    by_scene: dict[str, set[str]] = {}
    for anchor in anchored.anchors:
        by_scene.setdefault(anchor.scene_id, set()).add(anchor.text)

    def _resolve(scene_id: str, phrase: str) -> bool:
        phrases = by_scene.get(scene_id, set())
        if phrase in phrases:
            return True
        # Allow Stage5 no_asset truncation (scene.text[:24]) when full scene text was anchored.
        return any(phrase and (phrase in text or text.startswith(phrase)) for text in phrases)

    for scene in motion.scenes:
        for event in scene.event_intents:
            if not _resolve(scene.scene_id, event.anchor_phrase):
                raise Stage6Error(
                    "anchor_unresolved",
                    f"effect event phrase not in AnchoredTimingPlan: {event.anchor_phrase!r}",
                    scene_id=scene.scene_id,
                    event_id=event.event_id,
                )
    for intent in motion.sfx_intents:
        if not _resolve(intent.scene_id, intent.anchor_phrase):
            raise Stage6Error(
                "anchor_unresolved",
                f"sfx intent phrase not in AnchoredTimingPlan: {intent.anchor_phrase!r}",
                scene_id=intent.scene_id,
            )

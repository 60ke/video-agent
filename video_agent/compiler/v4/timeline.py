"""Compile CompiledVideoTimeline from Stage5/6 inputs."""

from __future__ import annotations

from pathlib import Path

from video_agent.compiler.v4.evidence import validate_claim_evidence
from video_agent.compiler.v4.sfx import compile_sfx_tracks, compile_voice_track
from video_agent.compiler.v4.subtitles import compile_subtitles_v4
from video_agent.compiler.v4.validation import raise_if_invalid, validate_compiled_timeline
from video_agent.compiler.v4.visual_tracks import compile_visual_tracks
from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    AssetRepositorySnapshot,
    CompiledRenderAsset,
    CompiledVideoTimeline,
    MotionAudioPlan,
    ResolvedAssetPlan,
    SceneSemanticPlan,
    SpeechTimingLock,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.io import sha256_json
from video_agent.registries import CapabilityRegistryHub


def compile_video_timeline(
    *,
    case_id: str,
    run_id: str,
    speech: SpeechTimingLock,
    scene_plan: SceneSemanticPlan,
    anchored: AnchoredTimingPlan,
    resolved: ResolvedAssetPlan,
    motion_plan: MotionAudioPlan,
    snapshot: AssetRepositorySnapshot,
    registry: CapabilityRegistryHub,
    repo_root: Path,
    platform_profile_id: str = "douyin_portrait_v1",
    postroll_frames: int = 0,
    width: int = 1080,
    height: int = 1920,
    object_store_root: Path | None = None,
) -> tuple[CompiledVideoTimeline, dict, list[dict]]:
    visual_tracks, effect_instances = compile_visual_tracks(
        scene_plan=scene_plan,
        resolved=resolved,
        anchored=anchored,
        motion_plan=motion_plan,
        registry=registry,
        postroll_frames=postroll_frames,
    )
    base_clips = next(track.clips for track in visual_tracks if track.track_kind == "base")
    validate_claim_evidence(
        scene_plan=scene_plan,
        resolved=resolved,
        anchored=anchored,
        snapshot=snapshot,
        base_clips=base_clips,
    )
    subtitles = compile_subtitles_v4(
        speech=speech,
        scene_plan=scene_plan,
        anchored=anchored,
        platform_profile_id=platform_profile_id,
    )
    sfx_tracks, sfx_audit = compile_sfx_tracks(
        motion_plan=motion_plan,
        anchored=anchored,
        speech=speech,
        registry=registry,
        repo_root=repo_root,
    )
    audio_tracks = [compile_voice_track(speech), *sfx_tracks]

    render_assets = _render_assets_from_snapshot(
        snapshot,
        resolved,
        object_store_root=object_store_root or (repo_root / "data" / "object_store"),
        repo_root=repo_root,
    )
    narration_frames = speech.duration_frames
    frame_count = narration_frames + max(postroll_frames, 0)

    # Adapter coverage: every effect_id must exist in registry (Remotion adapters checked separately)
    for instance in effect_instances:
        if registry.entry("effect", instance.effect_id) is None:
            raise Stage6Error(
                "adapter_coverage_missing",
                f"effect missing from registry: {instance.effect_id}",
            )

    timeline = CompiledVideoTimeline(
        schema_version=1,
        case_id=case_id,
        run_id=run_id,
        width=width,
        height=height,
        fps=speech.fps,
        narration_frame_count=narration_frames,
        postroll_frames=postroll_frames,
        frame_count=frame_count,
        platform_profile_id=platform_profile_id,
        registry_snapshot_id=motion_plan.registry_snapshot_id,
        speech_timing_lock_sha256=sha256_json(speech),
        anchored_timing_plan_sha256=sha256_json(anchored),
        resolved_asset_plan_sha256=sha256_json(resolved),
        motion_audio_plan_sha256=sha256_json(motion_plan),
        used_assets_snapshot_id=snapshot.snapshot_id,
        render_assets=render_assets,
        visual_tracks=visual_tracks,
        effect_instances=effect_instances,
        subtitle_track=subtitles,
        audio_tracks=audio_tracks,
    )
    report = validate_compiled_timeline(timeline)
    raise_if_invalid(report)
    return timeline, report, sfx_audit


def _render_assets_from_snapshot(
    snapshot: AssetRepositorySnapshot,
    resolved: ResolvedAssetPlan,
    *,
    object_store_root: Path,
    repo_root: Path,
) -> list[CompiledRenderAsset]:
    from video_agent.compiler.v4.media_probe import probe_media_size, resolve_source_path

    used: set[str] = set()
    for scene in resolved.scenes:
        for slot in scene.slots:
            if slot.asset_ref:
                used.add(slot.asset_ref)
    assets: list[CompiledRenderAsset] = []
    by_ref = {item.asset_ref: item for item in snapshot.assets}
    for asset_ref in sorted(used):
        item = by_ref.get(asset_ref)
        if item is None:
            raise Stage6Error(
                "material_snapshot_mismatch",
                f"resolved asset missing from snapshot: {asset_ref}",
            )
        source = resolve_source_path(
            object_key=item.object_key,
            object_store_root=object_store_root,
            repo_root=repo_root,
        )
        width, height, media_kind, duration_ms = probe_media_size(source)
        assets.append(
            CompiledRenderAsset(
                asset_ref=asset_ref,
                object_key=item.object_key,
                sha256=item.content_sha256,
                media_kind=media_kind,  # type: ignore[arg-type]
                width=width,
                height=height,
                duration_ms=duration_ms,
                has_alpha=source.suffix.lower() == ".png",
            )
        )
    return assets

"""Structured Stage6 validation report."""

from __future__ import annotations

from typing import Any

from video_agent.contracts.v4 import CompiledVideoTimeline, STAGE6_ERROR_CODES
from video_agent.contracts.v4.stage6_errors import Stage6Error


def validate_compiled_timeline(timeline: CompiledVideoTimeline) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    base = next((track for track in timeline.visual_tracks if track.track_kind == "base"), None)
    if base is None or not base.clips:
        issues.append({"error_code": "timeline_base_track_gap", "detail": "missing base track"})
    else:
        cursor = 0
        for clip in sorted(base.clips, key=lambda item: item.start_frame):
            if clip.start_frame > cursor:
                issues.append(
                    {
                        "error_code": "timeline_base_track_gap",
                        "detail": f"gap at {cursor}",
                        "scene_id": clip.scene_id,
                    }
                )
            if clip.start_frame < cursor:
                issues.append(
                    {
                        "error_code": "timeline_base_track_overlap",
                        "detail": f"overlap at {clip.clip_id}",
                        "scene_id": clip.scene_id,
                    }
                )
            cursor = clip.end_frame
        if cursor < timeline.frame_count:
            issues.append(
                {
                    "error_code": "timeline_base_track_gap",
                    "detail": f"base ends at {cursor}/{timeline.frame_count}",
                }
            )

    instance_ids = {item.effect_instance_id for item in timeline.effect_instances}
    for track in timeline.visual_tracks:
        for clip in track.clips:
            if clip.effect_instance_id not in instance_ids:
                issues.append(
                    {
                        "error_code": "adapter_coverage_missing",
                        "detail": f"missing effect instance {clip.effect_instance_id}",
                        "scene_id": clip.scene_id,
                    }
                )

    for cue in timeline.subtitle_track:
        if "\n" in cue.text or "\r" in cue.text or not cue.single_line:
            issues.append(
                {
                    "error_code": "subtitle_single_line_overflow",
                    "detail": cue.cue_id,
                    "scene_id": cue.scene_id,
                }
            )

    for issue in issues:
        if issue["error_code"] not in STAGE6_ERROR_CODES:
            raise ValueError(f"unknown validation code: {issue['error_code']}")

    return {
        "schema_version": 1,
        "ok": not issues,
        "issues": issues,
        "input_hashes": {
            "speech_timing_lock_sha256": timeline.speech_timing_lock_sha256,
            "anchored_timing_plan_sha256": timeline.anchored_timing_plan_sha256,
            "resolved_asset_plan_sha256": timeline.resolved_asset_plan_sha256,
            "motion_audio_plan_sha256": timeline.motion_audio_plan_sha256,
        },
    }


def raise_if_invalid(report: dict[str, Any]) -> None:
    if report.get("ok"):
        return
    first = report["issues"][0]
    raise Stage6Error(
        first["error_code"],
        first.get("detail", "validation failed"),
        scene_id=first.get("scene_id"),
        details={"issues": report["issues"]},
    )

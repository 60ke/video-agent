from __future__ import annotations

from video_agent.compiler.render_plan import MOTION_ALLOWLIST, TEMPLATE_ALLOWLIST, TEXT_DENSE_MOTION_ALLOWLIST, TEXT_DENSE_TEMPLATES
from video_agent.compiler.subtitles import fullwidth_units
from video_agent.contracts import CheckResult, RenderPlan
from video_agent.platform import PixelRect, get_profile


def validate_render_plan(plan: RenderPlan) -> list[CheckResult]:
    checks: list[CheckResult] = []
    profile = get_profile(plan.platform_profile)
    subtitle_errors = [cue.cue_id for cue in plan.subtitles if "\n" in cue.text or "\r" in cue.text or fullwidth_units(cue.text) > 10]
    checks.append(
        CheckResult(
            check_id="subtitle_single_line_10_units",
            status="failed" if subtitle_errors else "passed",
            message=", ".join(subtitle_errors),
        )
    )
    slot_errors = []
    for cue in plan.subtitles:
        slot = profile.subtitle_top if cue.slot == "subtitle_top" else profile.subtitle_lower
        if any(slot.intersects(region) for region in profile.avoid_regions):
            slot_errors.append(cue.cue_id)
    checks.append(CheckResult(check_id="subtitle_platform_safe", status="failed" if slot_errors else "passed", message=", ".join(slot_errors)))
    motion_errors = [shot.shot_id for shot in plan.shots if shot.motion not in MOTION_ALLOWLIST]
    checks.append(CheckResult(check_id="motion_allowlist", status="failed" if motion_errors else "passed", message=", ".join(motion_errors)))
    template_errors = [shot.shot_id for shot in plan.shots if shot.template not in TEMPLATE_ALLOWLIST]
    checks.append(CheckResult(check_id="template_implemented", status="failed" if template_errors else "passed", message=", ".join(template_errors)))
    overlay_errors: list[str] = []
    for shot in plan.shots:
        if shot.track != "overlay" or not shot.overlay_layout:
            continue
        layout = shot.overlay_layout
        stage = profile.content_safe
        box = PixelRect(
            stage.x + round(float(layout["x"]) * stage.w),
            stage.y + round(float(layout["y"]) * stage.h),
            round(float(layout["w"]) * stage.w),
            round(float(layout["h"]) * stage.h),
        )
        if any(box.intersects(region) for region in (*profile.avoid_regions, profile.subtitle_top, profile.subtitle_lower)):
            overlay_errors.append(shot.shot_id)
    checks.append(CheckResult(check_id="overlay_platform_safe", status="failed" if overlay_errors else "passed", message=", ".join(overlay_errors)))
    text_distortion_errors = [
        shot.shot_id
        for shot in plan.shots
        if shot.template in TEXT_DENSE_TEMPLATES and shot.motion not in TEXT_DENSE_MOTION_ALLOWLIST
    ]
    checks.append(
        CheckResult(
            check_id="text_dense_motion_safe",
            status="failed" if text_distortion_errors else "passed",
            message=", ".join(text_distortion_errors),
        )
    )
    cues_by_anchor: dict[str, list[object]] = {}
    for shot in plan.shots:
        for cue in shot.cues:
            cues_by_anchor.setdefault(cue.anchor_id, []).append(cue)
    audio_anchor_errors = []
    for track in plan.audio_tracks:
        if track.kind != "sfx":
            continue
        cues = cues_by_anchor.get(track.anchor_id or "", [])
        cue = next((candidate for candidate in cues if candidate.hit_frame == track.sync_frame), None)
        actual_peak_frame = track.start_frame + round(track.effective_sync_offset_ms * plan.fps / 1000)
        if cue is None or track.sync_frame is None or abs(cue.hit_frame - actual_peak_frame) > 1:
            audio_anchor_errors.append(track.anchor_id or track.path)
    checks.append(
        CheckResult(
            check_id="sfx_visual_shared_anchor",
            status="failed" if audio_anchor_errors else "passed",
            message=", ".join(audio_anchor_errors),
        )
    )
    sfx_tracks = sorted((track for track in plan.audio_tracks if track.kind == "sfx"), key=lambda item: item.start_frame)
    density = plan.style.get("sfx_density", {})
    min_gap_ms = int(density.get("min_gap_ms", 280))
    window_ms = int(density.get("window_ms", 3000))
    max_events = int(density.get("max_events_per_window", 3))
    repeat_cooldown_ms = int(density.get("repeat_cooldown_ms", 900))
    sfx_density_errors: list[str] = []
    for index, track in enumerate(sfx_tracks):
        track_ms = track.start_frame * 1000 / plan.fps
        if index and track_ms - sfx_tracks[index - 1].start_frame * 1000 / plan.fps < min_gap_ms:
            sfx_density_errors.append(f"gap:{sfx_tracks[index - 1].anchor_id}/{track.anchor_id}")
        same_semantic = next(
            (
                previous
                for previous in reversed(sfx_tracks[:index])
                if previous.semantic_id and previous.semantic_id == track.semantic_id
            ),
            None,
        )
        if same_semantic and track_ms - same_semantic.start_frame * 1000 / plan.fps < repeat_cooldown_ms:
            sfx_density_errors.append(f"repeat:{track.semantic_id}")
        in_window = sum(
            1
            for candidate in sfx_tracks
            if 0 <= track_ms - candidate.start_frame * 1000 / plan.fps < window_ms
        )
        if in_window > max_events:
            sfx_density_errors.append(f"window:{track.anchor_id}")
    checks.append(
        CheckResult(
            check_id="semantic_sfx_density",
            status="failed" if sfx_density_errors else "passed",
            message=", ".join(sfx_density_errors),
        )
    )
    density_errors = []
    for shot in plan.shots:
        events = [shot.start_frame] + sorted(cue.hit_frame for cue in shot.cues) + [shot.end_frame]
        max_gap = max((right - left for left, right in zip(events, events[1:])), default=0)
        if max_gap > int(round(plan.fps * 2.2)) and not shot.long_hold_reason:
            density_errors.append(f"{shot.shot_id}:{max_gap}")
        if shot.end_frame - shot.start_frame > plan.fps * 4 and not shot.long_hold_reason:
            density_errors.append(f"{shot.shot_id}:over_4s")
    checks.append(CheckResult(check_id="semantic_visual_density", status="failed" if density_errors else "passed", message=", ".join(density_errors)))
    readability_errors: list[str] = []
    minimum_seconds = {
        "ui_params_focus": 2.2,
        "result_showcase": 1.2,
        "reference_to_result": 1.5,
        "brand_ip_cutaway": 1.2,
    }
    for shot in plan.shots:
        if shot.track != "base":
            continue
        required = minimum_seconds.get(shot.template, 1.5 if shot.template == "ui_feature_entry" else 0.0)
        actual = (shot.end_frame - shot.start_frame) / plan.fps
        if actual + 1e-6 < required:
            readability_errors.append(f"{shot.shot_id}:{actual:.3f}s<{required:.3f}s")
    checks.append(
        CheckResult(
            check_id="template_readability_duration",
            status="failed" if readability_errors else "passed",
            message=", ".join(readability_errors),
        )
    )
    sequence_errors = []
    for shot in plan.shots:
        sequence = shot.parameter_sequence
        if sequence is None:
            continue
        if sequence.hit_frame > shot.end_frame - sequence.minimum_hold_frames:
            sequence_errors.append(f"hold:{shot.shot_id}")
        if sequence.start_frame < shot.start_frame or sequence.hit_frame > shot.end_frame:
            sequence_errors.append(f"range:{shot.shot_id}")
        if not sequence.start_frame < sequence.stage_frame < sequence.hit_frame:
            sequence_errors.append(f"order:{shot.shot_id}")
    checks.append(
        CheckResult(
            check_id="parameter_sequence_timing",
            status="failed" if sequence_errors else "passed",
            message=", ".join(sequence_errors),
        )
    )
    timeline_errors = []
    ordered = sorted((shot for shot in plan.shots if shot.track == "base"), key=lambda shot: shot.start_frame)
    if not ordered:
        timeline_errors.append("missing_base_track")
    elif ordered[0].start_frame != 0:
        timeline_errors.append(f"starts_at:{ordered[0].start_frame}")
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_frame < previous.end_frame:
            timeline_errors.append(f"overlap:{previous.shot_id}/{current.shot_id}")
        elif current.start_frame > previous.end_frame:
            timeline_errors.append(f"gap:{previous.shot_id}/{current.shot_id}")
    if ordered and ordered[-1].end_frame != plan.frame_count:
        timeline_errors.append(f"ends_at:{ordered[-1].end_frame}/{plan.frame_count}")
    checks.append(CheckResult(check_id="shot_timeline", status="failed" if timeline_errors else "passed", message=", ".join(timeline_errors)))
    subtitle_beat_errors = []
    for cue in plan.subtitles:
        matching = sorted(
            (shot for shot in plan.shots if shot.track == "base" and cue.beat_id in shot.beat_ids),
            key=lambda shot: shot.start_frame,
        )
        covered_until = cue.start_frame
        for shot in matching:
            if shot.start_frame <= covered_until < shot.end_frame:
                covered_until = max(covered_until, shot.end_frame)
            if covered_until >= cue.end_frame:
                break
        if cue.beat_id and covered_until < cue.end_frame:
            subtitle_beat_errors.append(cue.cue_id)
    checks.append(
        CheckResult(
            check_id="subtitle_beat_alignment",
            status="failed" if subtitle_beat_errors else "passed",
            message=", ".join(subtitle_beat_errors),
        )
    )
    return checks

from __future__ import annotations

from video_agent.compiler.render_plan import EFFECT_ALLOWLIST, TEXT_DENSE_EFFECT_ALLOWLIST, TEXT_DENSE_TEMPLATES
from video_agent.compiler.subtitles import fullwidth_units
from video_agent.contracts import CheckResult, RenderPlan
from video_agent.platform import get_profile


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
    effect_errors = [shot.shot_id for shot in plan.shots if shot.effect not in EFFECT_ALLOWLIST]
    checks.append(CheckResult(check_id="effect_allowlist", status="failed" if effect_errors else "passed", message=", ".join(effect_errors)))
    text_distortion_errors = [
        shot.shot_id
        for shot in plan.shots
        if shot.template in TEXT_DENSE_TEMPLATES and shot.effect not in TEXT_DENSE_EFFECT_ALLOWLIST
    ]
    checks.append(
        CheckResult(
            check_id="text_dense_motion_safe",
            status="failed" if text_distortion_errors else "passed",
            message=", ".join(text_distortion_errors),
        )
    )
    cue_by_anchor = {cue.anchor_id: cue for shot in plan.shots for cue in shot.cues}
    audio_anchor_errors = []
    for track in plan.audio_tracks:
        if track.kind != "sfx":
            continue
        cue = cue_by_anchor.get(track.anchor_id or "")
        if cue is None or cue.hit_frame != track.start_frame:
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
    timeline_errors = []
    ordered = sorted(plan.shots, key=lambda shot: shot.start_frame)
    if ordered[0].start_frame != 0:
        timeline_errors.append(f"starts_at:{ordered[0].start_frame}")
    for previous, current in zip(ordered, ordered[1:]):
        if current.start_frame < previous.end_frame:
            timeline_errors.append(f"overlap:{previous.shot_id}/{current.shot_id}")
        elif current.start_frame > previous.end_frame:
            timeline_errors.append(f"gap:{previous.shot_id}/{current.shot_id}")
    if ordered[-1].end_frame != plan.frame_count:
        timeline_errors.append(f"ends_at:{ordered[-1].end_frame}/{plan.frame_count}")
    checks.append(CheckResult(check_id="shot_timeline", status="failed" if timeline_errors else "passed", message=", ".join(timeline_errors)))
    shot_by_beat = {shot.beat_id: shot for shot in plan.shots}
    subtitle_beat_errors = []
    for cue in plan.subtitles:
        shot = shot_by_beat.get(cue.beat_id or "")
        if cue.beat_id and (shot is None or cue.start_frame < shot.start_frame or cue.end_frame > shot.end_frame):
            subtitle_beat_errors.append(cue.cue_id)
    checks.append(
        CheckResult(
            check_id="subtitle_beat_alignment",
            status="failed" if subtitle_beat_errors else "passed",
            message=", ".join(subtitle_beat_errors),
        )
    )
    return checks

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from video_agent.contracts import PhraseAnchor


NORMAL_DURATION_FRAMES = 10
MINIMUM_DURATION_FRAMES = 6
MAXIMUM_DURATION_FRAMES = 14
DEFAULT_DELAY_FRAMES = 5
MINIMUM_HOLD_FRAMES = 10
CROSSFADE_FRAMES = 3


@dataclass(frozen=True)
class ParameterSequenceTiming:
    start_frame: int
    stage_frame: int
    hit_frame: int
    minimum_hold_frames: int
    crossfade_frames: int
    timing_source: str
    matched_keywords: list[dict[str, int | str]]
    timing_adjustment_reason: str | None = None


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\s*＊，。！？、,.!?:：;；\-]+", "", value)


def _keyword_matches(labels: list[str], anchors: list[PhraseAnchor], start_frame: int, end_frame: int) -> list[dict[str, int | str]]:
    matches: list[dict[str, int | str]] = []
    for label in labels:
        normalized = _normalize(label)
        if not normalized:
            continue
        candidates = [
            anchor
            for anchor in anchors
            if start_frame <= anchor.hit_frame < end_frame and normalized in _normalize(anchor.text)
        ]
        if candidates:
            anchor = candidates[-1]
            matches.append({"label": label, "anchor_id": anchor.anchor_id, "hit_frame": anchor.hit_frame})
    return matches


def compile_parameter_sequence_timing(
    *,
    required_field_labels: list[str],
    anchors: list[PhraseAnchor],
    shot_start_frame: int,
    shot_end_frame: int,
) -> ParameterSequenceTiming:
    """Lock a complete flower-text frame to the last spoken field label in this shot."""

    available = shot_end_frame - shot_start_frame
    required = MINIMUM_DURATION_FRAMES + MINIMUM_HOLD_FRAMES
    if available < required:
        raise ValueError(
            f"parameter sequence needs at least {required} frames, but shot has {available}; replan the visual timeline"
        )

    matched = _keyword_matches(required_field_labels, anchors, shot_start_frame, shot_end_frame)
    latest_hit = shot_end_frame - MINIMUM_HOLD_FRAMES
    adjustment: str | None = None
    if matched:
        desired_hit = max(int(item["hit_frame"]) for item in matched)
        hit = min(desired_hit, latest_hit)
        timing_source = "keyword_end"
        if hit != desired_hit:
            adjustment = "minimum_hold_guard"
    else:
        hit = min(shot_start_frame + DEFAULT_DELAY_FRAMES + NORMAL_DURATION_FRAMES, latest_hit)
        timing_source = "default_sequence"

    duration = min(NORMAL_DURATION_FRAMES, MAXIMUM_DURATION_FRAMES, hit - shot_start_frame)
    if duration < MINIMUM_DURATION_FRAMES:
        hit = shot_start_frame + MINIMUM_DURATION_FRAMES
        duration = MINIMUM_DURATION_FRAMES
        adjustment = adjustment or "short_shot_guard"
    start = hit - duration
    stage = start + max(1, round(duration * 0.5))
    if stage >= hit:
        stage = hit - 1
    return ParameterSequenceTiming(
        start_frame=start,
        stage_frame=stage,
        hit_frame=hit,
        minimum_hold_frames=MINIMUM_HOLD_FRAMES,
        crossfade_frames=min(CROSSFADE_FRAMES, max(1, stage - start), max(1, hit - stage)),
        timing_source=timing_source,
        matched_keywords=matched,
        timing_adjustment_reason=adjustment,
    )

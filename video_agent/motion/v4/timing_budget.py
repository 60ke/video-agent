"""Exact scene budget from AnchoredTimingPlan (no proportional fallback)."""

from __future__ import annotations

from video_agent.contracts.v4 import AnchoredTimingPlan
from video_agent.contracts.v4.stage6_errors import Stage6Error


def scene_span_frames(anchored: AnchoredTimingPlan, scene_id: str) -> int:
    for span in anchored.scene_spans:
        if span.scene_id == scene_id:
            return span.end_frame - span.start_frame
    raise Stage6Error(
        "scene_span_gap",
        f"AnchoredTimingPlan missing scene span for {scene_id}",
        scene_id=scene_id,
    )


def scene_budget_ms(anchored: AnchoredTimingPlan, scene_id: str) -> int:
    """Return narration milliseconds for an exact AnchoredSceneSpan."""
    frames = scene_span_frames(anchored, scene_id)
    return frames_to_ms(frames, anchored.fps)


def frames_to_ms(frames: int, fps: int) -> int:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return int(round(frames * 1000 / fps))

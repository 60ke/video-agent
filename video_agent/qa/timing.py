from __future__ import annotations

from video_agent.compiler.subtitles import fullwidth_units
from video_agent.contracts import CheckResult, Narration, TimingLock


def validate_timing_lock(narration: Narration, timing: TimingLock) -> list[CheckResult]:
    checks: list[CheckResult] = []
    expected_pauses = sum(len(beat.pause_intents) for beat in narration.beats)
    checks.append(
        CheckResult(
            check_id="pause_event_coverage",
            status="passed" if len(timing.pause_events) == expected_pauses else "failed",
            details={"expected": expected_pauses, "actual": len(timing.pause_events)},
        )
    )
    overlong = [event.pause_id for event in timing.pause_events if event.measured_frames > round(timing.fps * 0.75)]
    checks.append(
        CheckResult(
            check_id="pause_event_natural_range",
            status="failed" if overlong else "passed",
            message=", ".join(overlong),
            details={
                "events": [
                    {
                        "pause_id": event.pause_id,
                        "requested_ms": event.requested_ms,
                        "measured_frames": event.measured_frames,
                    }
                    for event in timing.pause_events
                ]
            },
        )
    )
    rate = fullwidth_units(narration.spoken_text) / (timing.duration_ms / 1000)
    if rate < 3.5 or rate > 6.2:
        status = "failed"
    elif rate < 4.2 or rate > 5.8:
        status = "warning"
    else:
        status = "passed"
    checks.append(CheckResult(check_id="effective_speech_rate", status=status, details={"units_per_second": round(rate, 3)}))
    return checks

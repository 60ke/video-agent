"""Shared millisecond↔frame timebase for V4 Stage 6."""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP


def ms_to_hit_frame(milliseconds: int, fps: int) -> int:
    """ROUND_HALF_UP for semantic hit / onset frames."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    value = Decimal(milliseconds) * Decimal(fps) / Decimal(1000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ms_to_interval_start(milliseconds: int, fps: int) -> int:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return int(math.floor(milliseconds * fps / 1000))


def ms_to_interval_end(milliseconds: int, fps: int) -> int:
    """Exclusive end frame via ceil."""
    if fps <= 0:
        raise ValueError("fps must be positive")
    return int(math.ceil(milliseconds * fps / 1000))


def duration_frames(duration_ms: int, fps: int) -> int:
    return max(ms_to_interval_end(duration_ms, fps), 0)


# Backward-compatible alias used by older Stage5 call sites during Unit 3 cutover.
ms_to_frame = ms_to_hit_frame

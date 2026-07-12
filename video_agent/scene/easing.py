from __future__ import annotations


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def ease_out_cubic(value: float) -> float:
    value = clamp01(value)
    return 1.0 - (1.0 - value) ** 3


def smoothstep(value: float) -> float:
    value = clamp01(value)
    return value * value * (3.0 - 2.0 * value)

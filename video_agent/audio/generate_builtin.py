from __future__ import annotations

import argparse
import math
import random
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 48_000


def _envelope(index: int, count: int, attack_ms: float, release_ms: float) -> float:
    attack = max(1, int(SAMPLE_RATE * attack_ms / 1000))
    release = max(1, int(SAMPLE_RATE * release_ms / 1000))
    return min(1.0, index / attack, (count - index - 1) / release)


def _tone(duration_ms: int, start_hz: float, end_hz: float, *, gain: float, attack_ms: float = 4, release_ms: float = 70) -> list[float]:
    count = int(SAMPLE_RATE * duration_ms / 1000)
    phase = 0.0
    samples: list[float] = []
    for index in range(count):
        progress = index / max(1, count - 1)
        frequency = start_hz + (end_hz - start_hz) * progress
        phase += 2 * math.pi * frequency / SAMPLE_RATE
        value = math.sin(phase) + 0.18 * math.sin(phase * 2)
        samples.append(value * gain * _envelope(index, count, attack_ms, release_ms))
    return samples


def _noise(duration_ms: int, *, gain: float, seed: int, rise: bool = False) -> list[float]:
    rng = random.Random(seed)
    count = int(SAMPLE_RATE * duration_ms / 1000)
    previous = 0.0
    samples: list[float] = []
    for index in range(count):
        progress = index / max(1, count - 1)
        raw = rng.uniform(-1.0, 1.0)
        smoothing = 0.82 - 0.42 * progress if rise else 0.5 + 0.38 * progress
        previous = previous * smoothing + raw * (1.0 - smoothing)
        shape = math.sin(math.pi * progress) * (0.35 + 0.65 * progress if rise else 1.0)
        samples.append(previous * gain * shape)
    return samples


def _mix(*layers: tuple[list[float], int]) -> list[float]:
    length = max((len(samples) + int(SAMPLE_RATE * delay_ms / 1000) for samples, delay_ms in layers), default=0)
    output = [0.0] * length
    for samples, delay_ms in layers:
        offset = int(SAMPLE_RATE * delay_ms / 1000)
        for index, sample in enumerate(samples):
            output[index + offset] += sample
    peak = max((abs(sample) for sample in output), default=1.0)
    scale = min(1.0, 0.68 / max(peak, 1e-9))
    return [sample * scale for sample in output]


def _write(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, sample)) * 32767)) for sample in samples)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(payload)


def generate(output_dir: Path) -> list[Path]:
    sounds = {
        "menu_hover.wav": _tone(140, 720, 900, gain=0.22, release_ms=55),
        "ui_click.wav": _mix(
            (_tone(95, 1180, 760, gain=0.34, release_ms=42), 0),
            (_tone(65, 2100, 1400, gain=0.12, release_ms=34), 8),
        ),
        "field_focus.wav": _mix(
            (_tone(150, 760, 980, gain=0.22, release_ms=70), 0),
            (_tone(100, 1220, 1420, gain=0.12, release_ms=50), 35),
        ),
        "upload.wav": _mix(
            (_noise(270, gain=0.22, seed=11, rise=True), 0),
            (_tone(240, 420, 1080, gain=0.24, attack_ms=25, release_ms=80), 20),
        ),
        "result_reveal.wav": _mix(
            (_noise(260, gain=0.11, seed=29, rise=True), 0),
            (_tone(360, 620, 760, gain=0.25, attack_ms=8, release_ms=150), 25),
            (_tone(300, 930, 1140, gain=0.18, attack_ms=5, release_ms=170), 90),
        ),
        "page_flip.wav": _mix(
            (_noise(250, gain=0.33, seed=47), 0),
            (_tone(180, 540, 300, gain=0.08, release_ms=90), 35),
        ),
        "success.wav": _mix(
            (_tone(260, 660, 660, gain=0.23, release_ms=150), 0),
            (_tone(340, 990, 990, gain=0.23, release_ms=190), 115),
        ),
    }
    paths = []
    for name, samples in sounds.items():
        path = output_dir / name
        _write(path, samples)
        paths.append(path)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic built-in semantic UI sound effects.")
    parser.add_argument("--output", type=Path, default=Path("assets/audio/sfx"))
    args = parser.parse_args()
    for path in generate(args.output):
        print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

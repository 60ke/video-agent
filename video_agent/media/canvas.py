"""Canonical Douyin canvas helpers (no V3 contracts)."""

from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image


CANVAS_SIZE = (1080, 1920)


def fit_canvas(content: bytes) -> Image.Image:
    with Image.open(BytesIO(content)) as source:
        image = source.convert("RGB")
    scale = max(CANVAS_SIZE[0] / image.width, CANVAS_SIZE[1] / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    left = max(0, (resized.width - CANVAS_SIZE[0]) // 2)
    top = max(0, (resized.height - CANVAS_SIZE[1]) // 2)
    return resized.crop((left, top, left + CANVAS_SIZE[0], top + CANVAS_SIZE[1]))


def stage_frame(base: Image.Image, final: Image.Image, mask: np.ndarray, strength: float = 0.55) -> Image.Image:
    base_rgb = np.array(base.convert("RGB"), dtype=np.float32)
    final_rgb = np.array(final.convert("RGB"), dtype=np.float32)
    alpha = (mask.astype(np.float32)[..., None] / 255.0) * strength
    staged = (base_rgb * (1 - alpha) + final_rgb * alpha).clip(0, 255).astype(np.uint8)
    return Image.fromarray(staged)

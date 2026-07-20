"""Subtitle font resolution and pixel-width measuring for Stage6."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from video_agent.contracts.v4.stage6_errors import Stage6Error


# Must match Remotion SubtitleTrack default when profile does not override.
DEFAULT_SUBTITLE_FONT_PX = 56

_FONT_CANDIDATES = (
    Path(os.environ["VIDEO_AGENT_FONT"]) if os.environ.get("VIDEO_AGENT_FONT") else None,
    Path("C:/Windows/Fonts/msyhbd.ttc"),
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
)


@lru_cache(maxsize=8)
def resolve_subtitle_font_path() -> Path:
    for candidate in _FONT_CANDIDATES:
        if candidate is None:
            continue
        if candidate.is_file():
            return candidate
    raise Stage6Error(
        "subtitle_single_line_overflow",
        "no supported Chinese subtitle font found; set VIDEO_AGENT_FONT",
    )


@lru_cache(maxsize=16)
def load_subtitle_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = resolve_subtitle_font_path()
    try:
        return ImageFont.truetype(str(path), size=size_px)
    except OSError as exc:
        raise Stage6Error(
            "subtitle_single_line_overflow",
            f"failed to load subtitle font: {path}",
        ) from exc


def measure_text_width_px(text: str, *, font_px: int = DEFAULT_SUBTITLE_FONT_PX) -> float:
    """Measure rendered text width in pixels at the Remotion subtitle font size."""
    if not text:
        return 0.0
    font = load_subtitle_font(font_px)
    image = Image.new("RGB", (8, 8))
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    return float(bbox[2] - bbox[0])


def subtitle_font_fingerprint() -> str:
    from video_agent.io import sha256_file

    return sha256_file(resolve_subtitle_font_path())

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PixelRect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersects(self, other: "PixelRect") -> bool:
        return self.x < other.right and self.right > other.x and self.y < other.bottom and self.bottom > other.y

    def contains(self, other: "PixelRect") -> bool:
        return self.x <= other.x and self.y <= other.y and self.right >= other.right and self.bottom >= other.bottom

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class PlatformProfile:
    profile_id: str
    canvas: PixelRect
    frame_safe: PixelRect
    content_safe: PixelRect
    critical_safe: PixelRect
    avoid_right_rail: PixelRect
    avoid_bottom_meta: PixelRect
    subtitle_top: PixelRect
    subtitle_lower: PixelRect

    @property
    def avoid_regions(self) -> tuple[PixelRect, PixelRect]:
        return self.avoid_right_rail, self.avoid_bottom_meta


DOUYIN_PORTRAIT_V1 = PlatformProfile(
    profile_id="douyin_portrait_v1",
    canvas=PixelRect(0, 0, 1080, 1920),
    frame_safe=PixelRect(48, 96, 964, 1724),
    content_safe=PixelRect(100, 186, 856, 1536),
    critical_safe=PixelRect(100, 186, 760, 1314),
    avoid_right_rail=PixelRect(870, 560, 210, 1040),
    avoid_bottom_meta=PixelRect(0, 1540, 930, 380),
    subtitle_top=PixelRect(90, 138, 820, 116),
    subtitle_lower=PixelRect(90, 1320, 760, 116),
)


PROFILES = {DOUYIN_PORTRAIT_V1.profile_id: DOUYIN_PORTRAIT_V1}


def get_profile(profile_id: str) -> PlatformProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"unknown platform profile: {profile_id}") from exc

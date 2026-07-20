"""V4 Stage6 layout helpers from frozen platform profile."""

from __future__ import annotations

from video_agent.contracts.v4 import CompiledLayout
from video_agent.platform.profiles import PlatformProfile, get_profile


LAYOUT_PROFILE_TO_PLATFORM = {
    "douyin_safe": "douyin_portrait_v1",
    "douyin_gallery_safe": "douyin_portrait_v1",
    "douyin_sequence_safe": "douyin_portrait_v1",
    "douyin_comparison_safe": "douyin_portrait_v1",
    "douyin_transition_safe": "douyin_portrait_v1",
}


def resolve_platform(layout_profile_id: str) -> PlatformProfile:
    platform_id = LAYOUT_PROFILE_TO_PLATFORM.get(layout_profile_id, "douyin_portrait_v1")
    return get_profile(platform_id)


def content_layout(
    layout_profile_id: str,
    *,
    fit: str = "contain",
    border_radius: int = 24,
    opacity: float = 1.0,
    background_style_id: str = "dark_grid",
) -> CompiledLayout:
    profile = resolve_platform(layout_profile_id)
    rect = profile.content_safe
    return CompiledLayout(
        x=rect.x,
        y=rect.y,
        width=rect.w,
        height=rect.h,
        fit=fit,  # type: ignore[arg-type]
        border_radius=border_radius,
        opacity=opacity,
        background_style_id=background_style_id,
        safe_area_profile_id=layout_profile_id,
    )

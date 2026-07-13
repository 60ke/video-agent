from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_agent.contracts import CaseConfig, VideoFormat


def test_video_format_is_fixed_to_douyin_portrait_canvas() -> None:
    assert VideoFormat().model_dump() == {"width": 1080, "height": 1920, "fps": 30}

    with pytest.raises(ValidationError):
        VideoFormat(width=720, height=1280, fps=30)
    with pytest.raises(ValidationError):
        VideoFormat(width=1080, height=1920, fps=25)


def test_case_platform_profile_is_fixed() -> None:
    with pytest.raises(ValidationError):
        CaseConfig(case_id="demo", goal="demo", platform_profile="generic_portrait")


def test_active_materialization_runs_after_timing_lock_and_before_visual_plan() -> None:
    from video_agent.runtime import STAGES

    assert STAGES == (
        "catalog",
        "narration",
        "speech",
        "visual_demand",
        "materialize",
        "asset_review",
        "visual",
        "compile",
        "render",
        "qa",
    )

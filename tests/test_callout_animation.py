from __future__ import annotations

from pathlib import Path

from PIL import Image

from video_agent.contracts import RenderAsset, RenderPlan, RenderShot
from video_agent.io import sha256_file
from video_agent.scene import FrameRenderer


def test_params_template_uses_most_of_critical_safe_width(tmp_path: Path) -> None:
    path = tmp_path / "params.png"
    Image.new("RGB", (1024, 1792), (20, 24, 30)).save(path)
    asset = RenderAsset(asset_id="asset_params", path=path.as_posix(), sha256=sha256_file(path), width=1024, height=1792)
    shot = RenderShot(
        shot_id="shot_params",
        beat_ids=["beat_1"],
        template="ui_params_focus",
        asset_bindings={"primary": asset.asset_id},
        start_frame=0,
        end_frame=30,
    )
    plan = RenderPlan(case_id="demo", run_id="run", frame_count=30, assets=[asset], shots=[shot], subtitles=[], audio_tracks=[])
    renderer = FrameRenderer(plan)
    try:
        card = renderer._card_for_asset(shot, 0, asset.asset_id)
    finally:
        renderer.close()
    assert 700 <= card.width <= 760
    assert card.height <= 1260

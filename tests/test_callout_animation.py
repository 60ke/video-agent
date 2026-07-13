from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from video_agent.assets.site_entry_batch import _build_callout_layers
from video_agent.contracts import CompiledCalloutAnimation, RenderAsset, RenderPlan, RenderShot
from video_agent.io import sha256_file
from video_agent.scene import FrameRenderer


def _prepared_feature_entry(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    source = tmp_path / "柯幻熊猫_文生图_会议美陈_功能入口关键帧.png"
    image = Image.new("RGB", (540, 960), (8, 14, 20))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((125, 100, 500, 850), radius=20, fill=(31, 32, 36))
    draw.rectangle((12, 20, 105, 62), fill=(220, 62, 32))
    draw.ellipse((285, 250, 470, 350), outline=(255, 35, 35), width=14)
    image.save(source)
    return source, _build_callout_layers(source)


def test_callout_layer_excludes_red_logo_and_preserves_it_in_base(tmp_path: Path) -> None:
    source, layers = _prepared_feature_entry(tmp_path)
    original = np.asarray(Image.open(source).convert("RGBA"))
    base = np.asarray(Image.open(layers["callout_base_path"]).convert("RGBA"))
    layer = np.asarray(Image.open(layers["callout_layer_path"]).convert("RGBA"))

    assert np.array_equal(base[35, 40, :3], original[35, 40, :3])
    assert layer[35, 40, 3] == 0
    assert layer[300, 285:470, 3].max() == 255


def test_renderer_reveals_prepared_callout_only_at_locked_frames(tmp_path: Path) -> None:
    source, layers = _prepared_feature_entry(tmp_path)
    asset = RenderAsset(
        asset_id="asset_feature_entry",
        path=source.as_posix(),
        sha256=sha256_file(source),
        width=540,
        height=960,
        callout_base_path=layers["callout_base_path"],
        callout_base_sha256=layers["callout_base_sha256"],
        callout_layer_path=layers["callout_layer_path"],
        callout_layer_sha256=layers["callout_layer_sha256"],
    )
    shot = RenderShot(
        shot_id="shot_1",
        beat_ids=["beat_1"],
        template="ui_feature_entry",
        asset_bindings={"primary": asset.asset_id},
        start_frame=0,
        end_frame=30,
        motion="none",
        callout_animation=CompiledCalloutAnimation(
            kind="handdrawn_circle_reveal",
            start_frame=8,
            hit_frame=20,
        ),
    )
    plan = RenderPlan(case_id="demo", run_id="run", frame_count=30, assets=[asset], shots=[shot], subtitles=[], audio_tracks=[])
    renderer = FrameRenderer(plan)
    try:
        before = np.asarray(renderer.render(7))
        after = np.asarray(renderer.render(20))
    finally:
        renderer.close()

    logo_region_before = before[300:430, 0:260]
    logo_region_after = after[300:430, 0:260]
    assert np.array_equal(logo_region_before, logo_region_after)
    assert ((after[:, :, 0] > 190) & (after[:, :, 0] > after[:, :, 1] * 1.5)).sum() > (
        (before[:, :, 0] > 190) & (before[:, :, 0] > before[:, :, 1] * 1.5)
    ).sum()


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

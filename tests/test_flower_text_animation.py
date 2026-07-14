from __future__ import annotations

import numpy as np
from PIL import Image

from video_agent.assets.flower_text import build_flower_text_assets
from video_agent.contracts import CompiledCalloutAnimation, RenderAsset, RenderPlan, RenderShot
from video_agent.io import sha256_file
from video_agent.scene import FrameRenderer


def test_flower_text_assets_preserve_base_and_create_two_stage_previews(tmp_path) -> None:
    source = tmp_path / "参数面板截图.png"
    output = tmp_path / "参数面板关键帧.png"
    Image.new("RGB", (640, 1120), (22, 26, 34)).save(source)

    meta = build_flower_text_assets(source, output, "品牌名称+行业")

    assert output.is_file()
    assert Image.open(meta["callout_base_path"]).size == (640, 1120)
    assert Image.open(meta["callout_layer_path"]).mode == "RGBA"
    original = np.asarray(Image.open(source).convert("RGB"))
    base = np.asarray(Image.open(meta["callout_base_path"]).convert("RGB"))
    stage1 = np.asarray(Image.open(meta["flower_text_stage1_path"]).convert("RGB"))
    stage2 = np.asarray(Image.open(meta["flower_text_stage2_path"]).convert("RGB"))
    assert np.array_equal(base, original)
    assert np.abs(stage1.astype(int) - original.astype(int)).sum() > 0
    assert np.abs(stage2.astype(int) - original.astype(int)).sum() > np.abs(stage1.astype(int) - original.astype(int)).sum()


def test_renderer_fades_flower_text_in_two_stages_at_locked_frames(tmp_path) -> None:
    source = tmp_path / "参数面板截图.png"
    output = tmp_path / "参数面板关键帧.png"
    Image.new("RGB", (640, 1120), (22, 26, 34)).save(source)
    meta = build_flower_text_assets(source, output, "行业")
    asset = RenderAsset(
        asset_id="asset_params",
        path=output.as_posix(),
        sha256=sha256_file(output),
        width=640,
        height=1120,
        callout_base_path=meta["callout_base_path"],
        callout_base_sha256=meta["callout_base_sha256"],
        callout_layer_path=meta["callout_layer_path"],
        callout_layer_sha256=meta["callout_layer_sha256"],
    )
    shot = RenderShot(
        shot_id="shot_params",
        beat_ids=["beat_1"],
        template="ui_params_focus",
        asset_bindings={"primary": asset.asset_id},
        start_frame=0,
        end_frame=40,
        motion="none",
        callout_animation=CompiledCalloutAnimation(
            kind="flower_text_fade_sequence",
            start_frame=8,
            hit_frame=26,
            finish_pulse_scale=1.0,
        ),
    )
    plan = RenderPlan(case_id="demo", run_id="run", frame_count=40, assets=[asset], shots=[shot], subtitles=[], audio_tracks=[])
    renderer = FrameRenderer(plan)
    try:
        before = np.asarray(renderer.render(7)).astype(int)
        stage1 = np.asarray(renderer.render(16)).astype(int)
        final = np.asarray(renderer.render(26)).astype(int)
    finally:
        renderer.close()
    assert np.abs(stage1 - before).sum() > 0
    assert np.abs(final - before).sum() > np.abs(stage1 - before).sum()

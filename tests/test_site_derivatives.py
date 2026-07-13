from __future__ import annotations

from pathlib import Path

from PIL import Image

from video_agent.assets.site_derivatives import generate_feature_entry_keyframe, generate_parameter_keyframe


def test_feature_entry_derivative_is_deterministic_1080x1920_with_layers(tmp_path: Path) -> None:
    source = tmp_path / "entry.png"
    output = tmp_path / "derived" / "功能入口关键帧.png"
    Image.new("RGB", (1920, 1080), (235, 235, 235)).save(source)

    metadata = generate_feature_entry_keyframe(
        source,
        output,
        {"x": 0.10, "y": 0.20, "w": 0.10, "h": 0.05},
        {"x": 0.05, "y": 0.15, "w": 0.30, "h": 0.50},
    )

    assert Image.open(output).size == (1080, 1920)
    assert Path(metadata["callout_base_path"]).is_file()
    assert Path(metadata["callout_layer_path"]).is_file()


def test_parameter_derivative_uses_cdp_boxes_without_redrawing_ui(tmp_path: Path) -> None:
    source = tmp_path / "params.png"
    output = tmp_path / "derived" / "参数面板关键帧.png"
    Image.new("RGB", (1920, 1080), (235, 235, 235)).save(source)

    metadata = generate_parameter_keyframe(
        source,
        output,
        [{"x": 0.10, "y": 0.40, "w": 0.20, "h": 0.05}],
        "填写必填项",
    )

    assert Image.open(output).size == (1080, 1920)
    assert Path(metadata["callout_layer_path"]).is_file()
    assert metadata["callout_layer_method"].startswith("site_callout_renderer")

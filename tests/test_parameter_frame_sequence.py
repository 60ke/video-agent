from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from video_agent.ai.gpt_image import ImageEditResult
from video_agent.assets import build_catalog
from video_agent.assets.site_params_batch import RequiredFieldsAnnotation
from video_agent.assets.site_params_sequence import approve_parameter_frame_sequences, generate_parameter_frame_sequences
from video_agent.contracts import PhraseAnchor, RenderAsset, RenderPlan, RenderShot
from video_agent.io import load_json, sha256_file
from video_agent.planning.parameter_sequence import compile_parameter_sequence_timing
from video_agent.scene import FrameRenderer


def _png_bytes(*, flower: bool = False) -> bytes:
    image = Image.new("RGB", (1080, 1920), (18, 22, 28))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 280, 1010, 1520), radius=30, fill=(30, 35, 44))
    if flower:
        draw.rounded_rectangle((620, 980, 940, 1120), radius=22, fill=(255, 220, 35))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_parameter_sequence_materializes_human_reviewable_complete_frames(tmp_path: Path, monkeypatch) -> None:
    source_dir = tmp_path / "assets" / "sites"
    source = source_dir / "柯幻熊猫_文生图_文化墙_参数面板截图.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(_png_bytes())
    (source_dir / "_callouts.json").write_text('{"items": {}}', encoding="utf-8")
    annotation = RequiredFieldsAnnotation(("行业", "主标题"), "行业+主标题", "frontend.vue", "a" * 64, (), ())
    monkeypatch.setattr("video_agent.assets.site_params_sequence._required_fields_annotation", lambda *_: annotation)
    responses = iter((_png_bytes(), _png_bytes(flower=True)))
    monkeypatch.setattr(
        "video_agent.assets.site_params_sequence.edit_image",
        lambda *_: ImageEditResult(content=next(responses), provider="test", model="gpt-image-test", response_id="img_test"),
    )

    output = tmp_path / "assets" / "derived" / "sites" / "柯幻熊猫" / "文生图" / "参数面板序列"
    result = generate_parameter_frame_sequences(tmp_path, source_dir, output, workers=1)
    manifest = load_json(Path(result["manifest"]))
    sequence = manifest["sequences"][0]
    assert sequence["quality_status"] == "unreviewed"
    assert set(sequence["frames"]) == {"base", "stage", "final"}
    assert all(Path(frame["path"]).is_file() for frame in sequence["frames"].values())
    assert sequence["registration"]["status"] == "passed"

    assert approve_parameter_frame_sequences(Path(result["manifest"])) == {"approved": 1}
    (tmp_path / "assets" / "results").mkdir()
    (tmp_path / "assets" / "outro").mkdir()
    catalog = build_catalog(tmp_path / "assets")
    sequence_assets = [asset for asset in catalog.assets if asset.metadata.get("sequence_id") == "params_文化墙"]
    assert {asset.metadata["sequence_role"] for asset in sequence_assets} == {"base", "stage", "final"}
    assert all(asset.quality.status == "human_approved" and asset.production_eligible for asset in sequence_assets)


def test_parameter_keyword_completion_and_minimum_hold_are_locked_to_frames() -> None:
    anchors = [
        PhraseAnchor(anchor_id="a1", text="先选择行业", token_ids=["t1"], hit_frame=40, beat_id="beat_1"),
        PhraseAnchor(anchor_id="a2", text="再填写主标题", token_ids=["t2"], hit_frame=70, beat_id="beat_1"),
    ]
    timing = compile_parameter_sequence_timing(
        required_field_labels=["行业", "主标题"], anchors=anchors, shot_start_frame=10, shot_end_frame=100
    )
    assert timing.hit_frame == 70
    assert timing.start_frame < timing.stage_frame < timing.hit_frame
    assert timing.hit_frame <= 100 - timing.minimum_hold_frames


def test_renderer_blends_complete_parameter_frames_without_runtime_layers(tmp_path: Path) -> None:
    paths = {}
    for state, color in (("base", (20, 20, 20)), ("stage", (120, 120, 20)), ("final", (220, 180, 30))):
        path = tmp_path / f"{state}.png"
        Image.new("RGB", (1080, 1920), color).save(path)
        paths[state] = path
    assets = [RenderAsset(asset_id=state, path=path.as_posix(), sha256=sha256_file(path), width=1080, height=1920) for state, path in paths.items()]
    shot = RenderShot(
        shot_id="params", beat_ids=["beat"], template="ui_params_focus", asset_bindings={state: state for state in paths},
        start_frame=0, end_frame=60,
        parameter_sequence={
            "sequence_id": "params", "base_asset_id": "base", "stage_asset_id": "stage", "final_asset_id": "final",
            "start_frame": 10, "stage_frame": 20, "hit_frame": 30, "minimum_hold_frames": 10,
            "crossfade_frames": 3, "timing_source": "default_sequence",
        },
    )
    renderer = FrameRenderer(RenderPlan(case_id="demo", run_id="run", frame_count=60, assets=assets, shots=[shot], subtitles=[], audio_tracks=[]))
    try:
        assert renderer._parameter_sequence_image(shot, 5).getpixel((0, 0))[:3] == (20, 20, 20)
        assert renderer._parameter_sequence_image(shot, 20).getpixel((0, 0))[:3] == (120, 120, 20)
        assert renderer._parameter_sequence_image(shot, 30).getpixel((0, 0))[:3] == (220, 180, 30)
    finally:
        renderer.close()

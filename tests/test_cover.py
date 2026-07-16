from __future__ import annotations

import io
import subprocess
from pathlib import Path

from PIL import Image

from video_agent.ai.gpt_image import ImageEditResult
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    EvidenceClass,
    Provenance,
    RenderAsset,
    RenderPlan,
    ShotPlan,
    TimeRef,
    VisualPlan,
)
from video_agent.cover import CoverSpec, _prompt, default_cover_spec, postprocess_cover
from video_agent.contracts import CaseConfig, Narration, NarrationBeat
from video_agent.io import sha256_file, write_json_atomic


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1024, 1792), color).save(buffer, "PNG")
    return buffer.getvalue()


def _body_video(path: Path) -> None:
    result = subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:r=30:d=0.333333",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.333333", "-frames:v", "10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_cover_prompt_keeps_v2_title_and_safe_zone_constraints() -> None:
    prompt = _prompt(CoverSpec(title="AI文化墙怎么做", subtitle_hint="一键生成多套方案"), 2, "什么网站，可以帮你一键生成文化墙")
    assert '"AI文化墙怎么做"' in prompt
    assert "x=0..1080, y=240..1680" in prompt
    assert "Website UI may only be a small supporting element" in prompt
    assert "什么网站，可以帮你一键生成文化墙" in prompt
    assert "Do not render the narration as subtitles" in prompt


def test_cover_prompt_without_subtitle_forbids_subtitle_text() -> None:
    prompt = _prompt(CoverSpec(title="VI设计 一句话生成"), 1, "不需要提示词，只需要简单输入你的品牌名称")
    assert "If the optional subtitle is empty, render no subtitle." in prompt


def test_default_cover_spec_uses_case_goal_and_full_narration() -> None:
    case = CaseConfig(case_id="demo", goal="制作一个文化墙功能介绍视频")
    narration = Narration(
        case_id="demo",
        beats=[NarrationBeat(beat_id="beat_001", spoken_text="上传参考图，就能生成文化墙效果。")],
    )
    spec = default_cover_spec(case, narration)
    assert spec.title == "文化墙功能介绍"
    assert spec.narration_text == "上传参考图，就能生成文化墙效果。"


def test_cover_postprocess_adds_exactly_one_frame_without_accumulating(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path
    case = repo / "cases" / "demo"
    run = case / "runs" / "run_1"
    (repo / "assets" / "results").mkdir(parents=True)
    (case / "input").mkdir(parents=True)
    (run / "final").mkdir(parents=True)
    result_path = repo / "assets" / "results" / "result.png"
    result_path.write_bytes(_png_bytes((230, 80, 60)))
    _body_video(run / "final" / "video.mp4")

    asset = Asset(
        asset_id="asset_result",
        path="assets/results/result.png",
        sha256=sha256_file(result_path),
        filename=result_path.name,
        width=1024,
        height=1792,
        semantic_path=["文生图", "文化墙"],
        role="result_image",
        evidence_class=EvidenceClass.SOURCE,
        quality=AssetQuality(status="human_approved"),
        provenance=Provenance(origin="curated_result_library"),
    )
    write_json_atomic(run / "asset_catalog.json", AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[asset]))
    visual = VisualPlan(
        case_id="demo",
        shots=[
            ShotPlan(
                shot_id="shot_1",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="timeline_start"),
                end=TimeRef(anchor_id="timeline_end"),
                template="result_showcase",
                asset_bindings={"primary": asset.asset_id},
            )
        ],
    )
    write_json_atomic(run / "visual_plan.json", visual)
    render = RenderPlan(
        case_id="demo",
        run_id="run_1",
        frame_count=10,
        assets=[RenderAsset(asset_id=asset.asset_id, path=result_path.as_posix(), sha256=asset.sha256, width=1024, height=1792)],
        shots=[
            {
                "shot_id": "shot_1",
                "beat_ids": ["beat_1"],
                "template": "result_showcase",
                "asset_bindings": {"primary": asset.asset_id},
                "start_frame": 0,
                "end_frame": 10,
            }
        ],
        subtitles=[],
        audio_tracks=[],
    )
    write_json_atomic(run / "render_plan.json", render)
    spec = case / "input" / "cover.json"
    write_json_atomic(spec, CoverSpec(title="AI文化墙怎么做"))

    monkeypatch.setattr(
        "video_agent.cover.edit_image",
        lambda *_args, **_kwargs: ImageEditResult(content=_png_bytes((245, 190, 30)), provider="test", model="test", response_id="cover_1"),
    )
    first = postprocess_cover(repo, case, run, spec)
    second = postprocess_cover(repo, case, run, spec)

    assert first["body_frame_count"] == 10
    assert first["output_frame_count"] == 11
    assert second["body_frame_count"] == 10
    assert second["output_frame_count"] == 11
    assert Path(first["cover"]).is_file()
    assert Path(first["crop_preview"]).is_file()

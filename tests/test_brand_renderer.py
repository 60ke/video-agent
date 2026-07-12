from __future__ import annotations

from pathlib import Path

from PIL import Image

from video_agent.contracts import AudioTrack, RenderAsset, RenderPlan, RenderShot
from video_agent.scene import FrameRenderer


def test_renderer_plays_animated_brand_gif(tmp_path: Path) -> None:
    path = tmp_path / "panda.gif"
    frames = [Image.new("RGBA", (80, 80), color) for color in ((255, 20, 20, 255), (20, 255, 20, 255))]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=500, loop=0, disposal=2)
    plan = RenderPlan(
        case_id="brand_demo",
        run_id="run",
        frame_count=30,
        assets=[
            RenderAsset(
                asset_id="asset_brand_gif",
                path=path.as_posix(),
                sha256="a" * 64,
                width=80,
                height=80,
                media_type="video",
                fps=2,
                frame_count=2,
                duration_ms=1000,
            )
        ],
        shots=[
            RenderShot(
                shot_id="shot_1",
                beat_ids=["beat_1"],
                template="brand_ip_cutaway",
                asset_bindings={"primary": "asset_brand_gif"},
                start_frame=0,
                end_frame=30,
            )
        ],
        subtitles=[],
        audio_tracks=[AudioTrack(kind="voice", path="voice.wav")],
    )
    renderer = FrameRenderer(plan)
    try:
        first = renderer.render(0).getpixel((540, 920))
        second = renderer.render(15).getpixel((540, 920))
    finally:
        renderer.close()
    assert first[0] > first[1]
    assert second[1] > second[0]

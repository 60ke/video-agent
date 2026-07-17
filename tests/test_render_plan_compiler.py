from __future__ import annotations

from pathlib import Path

from PIL import Image

from video_agent.compiler.render_plan import compile_render_plan
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    AudioConfig,
    BeatSpan,
    CueBinding,
    DurationPolicy,
    EvidenceClass,
    Narration,
    NarrationBeat,
    Provenance,
    ShotPlan,
    TimeRef,
    TimingLock,
    TokenTiming,
    VisualPlan,
)


def test_timeline_start_is_a_valid_visual_enter_cue(tmp_path: Path) -> None:
    image_path = tmp_path / "home.png"
    Image.new("RGB", (1920, 1080), "navy").save(image_path)
    asset = Asset(
        asset_id="asset_home",
        path=image_path.as_posix(),
        sha256="a" * 64,
        filename=image_path.name,
        width=1920,
        height=1080,
        semantic_path=["网站主页"],
        role="site_home",
        evidence_class=EvidenceClass.SOURCE,
        quality=AssetQuality(status="human_approved"),
        provenance=Provenance(origin="test"),
    )
    token = TokenTiming(
        token_id="tok_0001",
        text="开",
        start_ms=0,
        end_ms=100,
        start_frame=0,
        end_frame=3,
        beat_id="beat_001",
    )
    timing = TimingLock(
        case_id="timeline_boundary",
        audio_path=(tmp_path / "voice.mp3").as_posix(),
        audio_sha256="b" * 64,
        fps=30,
        duration_ms=100,
        duration_frames=3,
        tokens=[token],
        beat_spans=[BeatSpan(beat_id="beat_001", token_ids=[token.token_id], start_frame=0, end_frame=3)],
    )
    narration = Narration(
        case_id="timeline_boundary",
        beats=[NarrationBeat(beat_id="beat_001", spoken_text="开")],
    )
    visual = VisualPlan(
        case_id="timeline_boundary",
        shots=[
            ShotPlan(
                shot_id="shot_001",
                beat_ids=["beat_001"],
                start=TimeRef(anchor_id="timeline_start"),
                end=TimeRef(anchor_id="timeline_end"),
                template="ui_feature_entry",
                asset_bindings={"primary": asset.asset_id},
                cue_bindings=[CueBinding(action="visual.enter", anchor_id="timeline_start")],
            )
        ],
    )
    catalog = AssetCatalog(
        catalog_id="catalog_timeline_boundary",
        generated_at="2026-07-17T00:00:00Z",
        source_root=tmp_path.as_posix(),
        assets=[asset],
    )

    plan = compile_render_plan(
        case_id="timeline_boundary",
        run_id="run_001",
        narration=narration,
        timing=timing,
        visual=visual,
        catalog=catalog,
        repo_root=Path(__file__).resolve().parents[1],
        platform_profile="douyin_portrait_v1",
        width=1080,
        height=1920,
        case_dir=tmp_path,
        audio=AudioConfig(sfx_profile=None),
        duration_policy=DurationPolicy(),
    )

    assert plan.shots[0].cues[0].anchor_id == "timeline_start"
    assert plan.shots[0].cues[0].hit_frame == 0

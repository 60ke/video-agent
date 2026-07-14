from __future__ import annotations

from pathlib import Path

from PIL import Image

from video_agent.assets import materialize_assets, review_materialized_assets
from video_agent.compiler import resolves_to_supporting_asset, validate_claim_bindings
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    BeatSpan,
    Claim,
    ClaimCue,
    EvidenceClass,
    MaterializationPlan,
    Narration,
    NarrationBeat,
    PhraseAnchor,
    Provenance,
    ShotPlan,
    TimeRef,
    TimingLock,
    TokenTiming,
    VisualPlan,
)
from video_agent.io import sha256_file
from video_agent.planning import build_visual_demand_plan


def _source_asset(tmp_path: Path) -> Asset:
    path = tmp_path / "assets" / "results" / "source.png"
    path.parent.mkdir(parents=True)
    Image.new("RGB", (640, 480), (120, 50, 20)).save(path)
    return Asset(
        asset_id="asset_result_source",
        path="assets/results/source.png",
        sha256=sha256_file(path),
        filename=path.name,
        width=640,
        height=480,
        semantic_path=["文生图", "VI"],
        role="result_image",
        evidence_class=EvidenceClass.SOURCE,
        claims=["真实结果"],
        tags=["VI"],
        quality=AssetQuality(status="machine_checked"),
        provenance=Provenance(origin="curated_result_library"),
    )


def _narration(asset_id: str) -> Narration:
    return Narration(
        case_id="demo",
        claims=[Claim(claim_id="claim_result", text="真实结果", supporting_asset_ids=[asset_id])],
        beats=[
            NarrationBeat(
                beat_id="beat_1",
                spoken_text="这里展示真实结果和VI效果",
                claim_cues=[ClaimCue(claim_id="claim_result", phrase="真实结果")],
                asset_slots=["VI"],
            )
        ],
    )


def _timing() -> TimingLock:
    return TimingLock(
        case_id="demo",
        audio_path="voice.wav",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=5000,
        duration_frames=150,
        tokens=[
            TokenTiming(
                token_id="tok_1",
                text="真实结果",
                start_ms=0,
                end_ms=5000,
                start_frame=0,
                end_frame=150,
                beat_id="beat_1",
            )
        ],
        phrase_anchors=[
            PhraseAnchor(
                anchor_id="claim_anchor",
                text="真实结果",
                token_ids=["tok_1"],
                hit_frame=30,
                beat_id="beat_1",
                claim_ids=["claim_result"],
            )
        ],
        beat_spans=[BeatSpan(beat_id="beat_1", token_ids=["tok_1"], start_frame=0, end_frame=150)],
    )


def test_visual_demand_materializes_faithful_states_after_timing_lock(tmp_path: Path) -> None:
    source = _source_asset(tmp_path)
    catalog = AssetCatalog(catalog_id="source", generated_at="now", source_root="assets", assets=[source])
    narration = _narration(source.asset_id)
    timing = _timing()

    demand = build_visual_demand_plan("demo", narration, timing, catalog)

    assert demand.timing_lock_sha256
    assert demand.demands[0].required_visual_states == 3
    assert len(demand.requests) == 2
    assert all(request.beat_id == "beat_1" for request in demand.requests)

    pending = materialize_assets(
        tmp_path,
        catalog,
        MaterializationPlan(case_id="demo", requests=demand.requests),
        tmp_path / "run" / "derived_assets",
    )
    reviewed, report = review_materialized_assets(tmp_path, pending)

    assert report["counts"]["passed"] == 2
    for derived in reviewed.assets[1:]:
        assert derived.evidence_class == EvidenceClass.FAITHFUL
        assert derived.quality.status == "machine_checked"
        assert derived.claims == source.claims
        assert (derived.width, derived.height) == (1080, 1920)
        assert derived.provenance.parent_asset_ids == [source.asset_id]


def test_claim_binding_accepts_verified_e1_descendant(tmp_path: Path) -> None:
    source = _source_asset(tmp_path)
    catalog = AssetCatalog(catalog_id="source", generated_at="now", source_root="assets", assets=[source])
    narration = _narration(source.asset_id)
    demand = build_visual_demand_plan("demo", narration, _timing(), catalog)
    reviewed, _ = review_materialized_assets(
        tmp_path,
        materialize_assets(
            tmp_path,
            catalog,
            MaterializationPlan(case_id="demo", requests=demand.requests[:1]),
            tmp_path / "run" / "derived_assets",
        ),
    )
    derived = reviewed.assets[-1]
    by_id = {asset.asset_id: asset for asset in reviewed.assets}

    assert resolves_to_supporting_asset(derived.asset_id, {source.asset_id}, by_id)

    visual = VisualPlan(
        case_id="demo",
        shots=[
            ShotPlan(
                shot_id="faithful_support",
                beat_ids=["beat_1"],
                start=TimeRef(anchor_id="timeline_start"),
                end=TimeRef(anchor_id="timeline_end"),
                template="result_showcase",
                asset_bindings={"primary": derived.asset_id},
                claim_ids=["claim_result"],
            )
        ],
    )
    validate_claim_bindings(narration, visual, by_id)

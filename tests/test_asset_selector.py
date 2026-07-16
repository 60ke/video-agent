from __future__ import annotations

from pathlib import Path

from video_agent.ai.asset_selector import select_asset_candidates
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    CaseConfig,
    EvidenceClass,
    Narration,
    NarrationBeat,
    Provenance,
)


def _asset(asset_id: str, feature: str) -> Asset:
    return Asset(
        asset_id=asset_id,
        path=f"assets/results/{feature}.png",
        sha256="a" * 64,
        filename=f"{feature}.png",
        width=1920,
        height=1080,
        semantic_path=["文生图", feature],
        role="result_image",
        evidence_class=EvidenceClass.SOURCE,
        quality=AssetQuality(status="human_approved"),
        provenance=Provenance(origin="test"),
    )


def test_flash_contract_failure_falls_back_to_full_catalog_for_pro(tmp_path: Path, monkeypatch) -> None:
    culture_wall = _asset("asset_result_culture", "文化墙")
    logo = _asset("asset_result_logo", "LOGO")
    catalog = AssetCatalog(
        catalog_id="catalog_test",
        generated_at="2026-07-16T00:00:00Z",
        source_root="assets",
        assets=[culture_wall, logo],
        source_catalog_sha256="b" * 64,
    )
    narration = Narration(
        case_id="fallback_demo",
        beats=[NarrationBeat(beat_id="beat_001", spoken_text="主题公园")],
    )
    invalid = {
        "beat_candidates": {"beat_001": [culture_wall.asset_id]},
        "phrase_candidates": {"beat_001": {"主题公园": [culture_wall.asset_id]}},
        "phrase_candidate_modes": {"beat_001": {"主题公园": "result_item"}},
        "relationship_needs": {"beat_001": []},
    }
    monkeypatch.setattr(
        "video_agent.ai.asset_selector.OpenAICompatibleTextClient.complete_json",
        lambda *args, **kwargs: invalid,
    )

    candidates, report, _ = select_asset_candidates(
        Path(__file__).resolve().parents[1],
        CaseConfig(case_id="fallback_demo", goal="测试", feature_path=["文生图"]),
        narration,
        catalog,
        {"relationships": []},
        tmp_path / "selection.json",
    )

    assert report["mode"] == "deepseek_v4_pro_full_catalog_fallback"
    assert report["flash_result"] is None
    assert report["flash_failure"]["fallback"] == "full_catalog_to_pro"
    assert {asset.asset_id for asset in candidates.assets} == {culture_wall.asset_id, logo.asset_id}

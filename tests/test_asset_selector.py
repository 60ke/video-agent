from __future__ import annotations

import json
from pathlib import Path

from video_agent.ai.asset_index import AIAssetIndex, resolve_ai_asset_refs
from video_agent.ai.asset_selector import _repair_exact_phrase_candidates, select_asset_candidates
from video_agent.io import load_json
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
        "beat_candidates": {"beat_001": ["A9999"]},
        "phrase_candidates": {"beat_001": {"主题公园": []}},
        "phrase_candidate_modes": {"beat_001": {"主题公园": "result_item"}},
        "relationship_needs": {"beat_001": []},
    }
    monkeypatch.setattr(
        "video_agent.ai.asset_selector.OpenAICompatibleTextClient.complete_json",
        lambda *args, **kwargs: invalid,
    )

    candidates, report, _, returned_index = select_asset_candidates(
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
    assert returned_index.manifest() == load_json(tmp_path / "ai_asset_index.json")


def test_ai_asset_index_uses_stable_refs_and_resolves_planner_output() -> None:
    culture_wall = _asset("asset_result_culture", "文化墙")
    logo = _asset("asset_result_logo", "LOGO")
    index = AIAssetIndex.build([culture_wall, logo])

    table = index.compact_table([culture_wall, logo])
    culture_ref = index.ref_for_asset(culture_wall)
    assert table["fields"][0] == "asset_ref"
    assert culture_ref.startswith("A")
    assert culture_ref in {row[0] for row in table["rows"]}
    assert culture_wall.filename in {row[1] for row in table["rows"]}
    assert culture_wall.asset_id not in str(table)

    resolved = resolve_ai_asset_refs(
        {
            "scenes": [
                {
                    "asset_bindings": {"primary": culture_ref},
                    "gallery_items": [{"asset_id": culture_ref, "phrase": "文化墙"}],
                }
            ],
            "derivation_requests": [
                {
                    "source_asset_id": culture_ref,
                    "related_asset_ids": [index.ref_for_asset(logo)],
                }
            ],
        },
        index,
    )
    assert resolved["scenes"][0]["asset_bindings"]["primary"] == culture_wall.asset_id
    assert resolved["scenes"][0]["gallery_items"][0]["asset_id"] == culture_wall.asset_id
    assert resolved["derivation_requests"][0]["source_asset_id"] == culture_wall.asset_id
    assert resolved["derivation_requests"][0]["related_asset_ids"] == [logo.asset_id]


def test_flash_selection_uses_asset_refs_and_reuses_cache(tmp_path: Path, monkeypatch) -> None:
    culture_wall = _asset("asset_result_culture", "文化墙")
    catalog = AssetCatalog(
        catalog_id="catalog_test",
        generated_at="2026-07-16T00:00:00Z",
        source_root="assets",
        assets=[culture_wall],
        source_catalog_sha256="b" * 64,
    )
    narration = Narration(
        case_id="ref_demo",
        beats=[NarrationBeat(beat_id="beat_001", spoken_text="文化墙")],
    )
    calls: list[dict] = []

    def complete_json(self, system: str, user: str, purpose: str, **kwargs):
        payload = json.loads(user)
        calls.append(payload)
        asset_ref = payload["assets"]["rows"][0][0]
        assert asset_ref.startswith("A")
        assert culture_wall.asset_id not in user
        return {
            "beat_candidates": {"beat_001": [asset_ref]},
            "phrase_candidates": {"beat_001": {"文化墙": [asset_ref]}},
            "phrase_candidate_modes": {"beat_001": {"文化墙": "result_item"}},
            "relationship_needs": {"beat_001": []},
        }

    monkeypatch.setattr(
        "video_agent.ai.asset_selector.OpenAICompatibleTextClient.complete_json",
        complete_json,
    )
    arguments = (
        Path(__file__).resolve().parents[1],
        CaseConfig(case_id="ref_demo", goal="测试", feature_path=["文生图"]),
        narration,
        catalog,
        {"relationships": []},
        tmp_path / "selection.json",
    )
    candidates, report, _, _ = select_asset_candidates(*arguments)
    cached_candidates, cached_report, _, _ = select_asset_candidates(*arguments)

    assert len(calls) == 1
    assert report == cached_report
    assert candidates.assets == cached_candidates.assets == [culture_wall]


def test_exact_phrase_candidates_are_repaired_from_catalog_evidence() -> None:
    sculpture = _asset("asset_result_sculpture", "雕塑小品")
    landscape = _asset("asset_result_landscape", "景观小品")
    index = AIAssetIndex.build([sculpture, landscape])
    result = {
        "beat_candidates": {"beat_001": [index.ref_for_asset(landscape)]},
        "phrase_candidates": {"beat_001": {"雕塑小品": [index.ref_for_asset(landscape)]}},
        "phrase_candidate_modes": {"beat_001": {"雕塑小品": "result_item"}},
    }

    repaired = _repair_exact_phrase_candidates(
        result,
        Narration(case_id="repair", beats=[NarrationBeat(beat_id="beat_001", spoken_text="雕塑小品")]),
        index,
    )

    expected = index.ref_for_asset(sculpture)
    assert repaired["phrase_candidates"]["beat_001"]["雕塑小品"] == [expected]
    assert expected in repaired["beat_candidates"]["beat_001"]


def test_phrase_candidates_are_moved_to_the_verbatim_beat() -> None:
    office = _asset("asset_result_office", "企业办公和真实场景融合")
    index = AIAssetIndex.build([office])
    result = {
        "beat_candidates": {"beat_001": [], "beat_002": []},
        "phrase_candidates": {
            "beat_001": {},
            "beat_002": {"企业办公和真实场景融合": []},
        },
        "phrase_candidate_modes": {
            "beat_001": {},
            "beat_002": {"企业办公和真实场景融合": "result_item"},
        },
    }
    narration = Narration(
        case_id="repair_beat",
        beats=[
            NarrationBeat(beat_id="beat_001", spoken_text="还是我们企业办公和真实场景融合。"),
            NarrationBeat(beat_id="beat_002", spoken_text="都不在话下。"),
        ],
    )

    repaired = _repair_exact_phrase_candidates(result, narration, index)

    expected = index.ref_for_asset(office)
    assert repaired["phrase_candidates"]["beat_002"] == {}
    assert repaired["phrase_candidate_modes"]["beat_002"] == {}
    assert repaired["phrase_candidates"]["beat_001"]["企业办公和真实场景融合"] == [expected]
    assert repaired["phrase_candidate_modes"]["beat_001"]["企业办公和真实场景融合"] == "result_item"

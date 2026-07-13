from __future__ import annotations

import pytest

from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    CaseConfig,
    Claim,
    ClaimCue,
    EvidenceClass,
    Narration,
    NarrationBeat,
    NormalizedRect,
    Provenance,
    VisualAnchor,
)
from video_agent.planning.auto_visual import _assets_for_beat, _fit_visual_candidates
from video_agent.ai.visual_planner import _candidate_assets


def _asset() -> Asset:
    return Asset(
        asset_id="asset_site_abc123",
        path="assets/sites/demo.png",
        sha256="a" * 64,
        filename="demo.png",
        width=1080,
        height=1920,
        semantic_path=["文生图", "VI"],
        role="feature_form_params",
        evidence_class=EvidenceClass.SOURCE,
        claims=["real_website_screenshot"],
        visual_anchors=[
            VisualAnchor(
                anchor_id="anchor_brand",
                label="品牌名称",
                role="field",
                rect=NormalizedRect(x=0.1, y=0.2, w=0.5, h=0.1),
            )
        ],
        quality=AssetQuality(status="machine_checked"),
        provenance=Provenance(origin="site_screenshot_library"),
    )


def test_catalog_contract_fixture_is_valid() -> None:
    catalog = AssetCatalog(catalog_id="fixture", generated_at="now", source_root="assets", assets=[_asset()])
    narration = Narration(case_id="demo", beats=[NarrationBeat(beat_id="b1", spoken_text="填写品牌名称")])
    assert catalog.assets[0].semantic_path[-1] == "VI"
    assert narration.spoken_text == "填写品牌名称"


def test_result_selection_prefers_matching_industry_tag() -> None:
    community = _asset().model_copy(
        update={"asset_id": "asset_result_community", "role": "result_image", "filename": "文化墙_社区服务.png", "tags": ["社区服务"]}
    )
    medical = _asset().model_copy(
        update={"asset_id": "asset_result_medical", "role": "result_image", "filename": "文化墙_医疗文化.png", "tags": ["医疗文化"]}
    )
    candidates = _assets_for_beat(
        "医疗空间，重点更加集中。",
        ["真实结果", "医疗文化"],
        {"result_image": [community, medical], "feature_form_params": [], "feature_entry": [], "site_home": []},
        set(),
    )
    assert candidates[0][0].asset_id == medical.asset_id
    assert candidates[0][1] == "result_showcase"


def test_feature_entry_never_falls_back_to_result_or_source_screenshot() -> None:
    result = _asset().model_copy(update={"asset_id": "asset_result_only", "role": "result_image"})
    with pytest.raises(ValueError, match="production feature-entry keyframe is required"):
        _assets_for_beat(
            "进入功能入口",
            ["功能入口"],
            {"result_image": [result], "feature_form_params": [], "feature_entry": [], "site_home": []},
            set(),
        )


def test_feature_entry_selection_follows_named_features() -> None:
    culture = _asset().model_copy(
        update={"asset_id": "asset_entry_culture", "role": "feature_entry", "semantic_path": ["文生图", "文化墙"], "filename": "文化墙_功能入口关键帧.png"}
    )
    logo = culture.model_copy(
        update={"asset_id": "asset_entry_logo", "semantic_path": ["文生图", "LOGO"], "filename": "LOGO_功能入口关键帧.png"}
    )
    candidates = _assets_for_beat(
        "点击进入文化墙和LOGO功能。",
        ["操作路径", "文化墙", "LOGO"],
        {"result_image": [], "feature_form_params": [], "feature_entry": [culture, logo], "site_home": []},
        set(),
    )

    assert [asset.asset_id for asset, _ in candidates] == [culture.asset_id, logo.asset_id]


def test_capability_listing_prefers_named_feature_entry_over_matching_results() -> None:
    entry = _asset().model_copy(
        update={"asset_id": "asset_entry_culture", "role": "feature_entry", "semantic_path": ["文生图", "文化墙"]}
    )
    result = entry.model_copy(
        update={
            "asset_id": "asset_result_culture",
            "role": "result_image",
            "filename": "文化墙_医院文化_结果图.png",
            "provenance": Provenance(origin="curated_result_library"),
        }
    )

    candidates = _assets_for_beat(
        "文化墙、美陈等设计方案。",
        ["功能入口", "文化墙", "美陈"],
        {"result_image": [result], "feature_form_params": [], "feature_entry": [entry], "site_home": [], "feature_list": []},
        set(),
    )

    assert [(asset.asset_id, template) for asset, template in candidates] == [("asset_entry_culture", "ui_feature_entry")]


def test_enumerated_results_keep_one_asset_per_spoken_feature() -> None:
    culture = _asset().model_copy(
        update={"asset_id": "result_culture", "role": "result_image", "semantic_path": ["文生图", "文化墙"]}
    )
    logo = _asset().model_copy(
        update={"asset_id": "result_logo", "role": "result_image", "semantic_path": ["文生图", "LOGO"]}
    )
    candidates = _assets_for_beat(
        "文化墙、LOGO。",
        ["文化墙", "LOGO"],
        {"result_image": [culture, logo]},
        set(),
        visual_strategy="enumerated_results",
        hit_phrases=["文化墙", "LOGO"],
    )

    assert [(asset.asset_id, template) for asset, template in candidates] == [
        ("result_culture", "result_showcase"),
        ("result_logo", "result_showcase"),
    ]


def test_enumerated_results_fail_instead_of_using_filename_false_positive() -> None:
    vi_named_ecommerce = _asset().model_copy(
        update={
            "asset_id": "result_vi",
            "role": "result_image",
            "semantic_path": ["文生图", "VI"],
            "filename": "某品牌电商VI结果图.png",
        }
    )

    with pytest.raises(ValueError, match="电商"):
        _assets_for_beat(
            "电商。",
            ["电商"],
            {"result_image": [vi_named_ecommerce]},
            set(),
            visual_strategy="enumerated_results",
            hit_phrases=["电商"],
        )


def test_readability_budget_selects_representative_visuals() -> None:
    entry = _asset().model_copy(update={"role": "feature_entry"})
    four_entries = [
        (entry.model_copy(update={"asset_id": f"asset_entry_{index}", "filename": f"入口_{index}.png"}), "ui_feature_entry")
        for index in range(4)
    ]
    six_entries = [
        (entry.model_copy(update={"asset_id": f"asset_more_{index}", "filename": f"更多_{index}.png"}), "ui_feature_entry")
        for index in range(6)
    ]
    results = [
        (_asset().model_copy(update={"asset_id": f"asset_result_{index}", "role": "result_image"}), "result_showcase")
        for index in range(3)
    ]

    selected_four = _fit_visual_candidates(four_entries, 83, 30, all_required=False, beat_id="four")
    selected_six = _fit_visual_candidates(six_entries, 116, 30, all_required=False, beat_id="six")
    selected_results = _fit_visual_candidates(results, 72, 30, all_required=False, beat_id="results")

    assert [item[0].asset_id for item in selected_four] == ["asset_entry_0", "asset_entry_3"]
    assert [item[0].asset_id for item in selected_six] == ["asset_more_0", "asset_more_2", "asset_more_5"]
    assert [item[0].asset_id for item in selected_results] == ["asset_result_0", "asset_result_2"]


def test_cta_prefers_waving_brand_video() -> None:
    waving = _asset().model_copy(
        update={
            "asset_id": "asset_brand_wave",
            "role": "brand_ip_video",
            "media_type": "video",
            "filename": "柯幻熊猫_挥手.mp4",
            "tags": ["柯幻熊猫", "挥手"],
        }
    )
    running = waving.model_copy(
        update={"asset_id": "asset_brand_run", "filename": "柯幻熊猫_跑步.mp4", "tags": ["柯幻熊猫", "跑步"]}
    )
    candidates = _assets_for_beat(
        "想看哪种空间，评论区告诉我。",
        [],
        {
            "brand_ip_video": [running, waving],
            "brand_ip_animation": [],
            "brand_ip_static": [],
            "result_image": [],
            "feature_form_params": [],
            "feature_entry": [],
            "site_home": [],
        },
        set(),
    )
    assert candidates[0][0].asset_id == waving.asset_id
    assert candidates[0][1] == "brand_ip_cutaway"


def test_multimodal_packet_excludes_unreviewed_assets() -> None:
    approved = _asset().model_copy(update={"role": "result_image"})
    unreviewed = approved.model_copy(update={"asset_id": "asset_unreviewed", "quality": AssetQuality(status="unreviewed")})
    catalog = AssetCatalog(catalog_id="fixture", generated_at="now", source_root="assets", assets=[approved, unreviewed])
    narration = Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="测试")])
    selected = _candidate_assets(CaseConfig(case_id="demo", goal="测试", feature_path=["文生图", "VI"]), narration, catalog)
    assert [asset.asset_id for asset in selected] == [approved.asset_id]


def test_multimodal_packet_never_drops_claim_evidence_at_limit() -> None:
    evidence = [
        _asset().model_copy(update={"asset_id": f"claim_asset_{index:02d}", "role": "result_image"})
        for index in range(10)
    ]
    extras = [_asset().model_copy(update={"asset_id": f"extra_{index:02d}", "role": "site_home"}) for index in range(8)]
    catalog = AssetCatalog(catalog_id="fixture", generated_at="now", source_root="assets", assets=evidence + extras)
    narration = Narration(
        case_id="demo",
        claims=[Claim(claim_id="claim_all", text="十张结果", supporting_asset_ids=[asset.asset_id for asset in evidence])],
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="展示十张结果", claim_cues=[ClaimCue(claim_id="claim_all", phrase="十张结果")])],
    )
    selected = _candidate_assets(CaseConfig(case_id="demo", goal="测试", feature_path=["文生图", "VI"]), narration, catalog)
    assert {asset.asset_id for asset in evidence} <= {asset.asset_id for asset in selected}
    assert len(selected) == 12


def test_multimodal_packet_fails_when_claim_evidence_exceeds_limit() -> None:
    evidence = [_asset().model_copy(update={"asset_id": f"claim_asset_{index:02d}", "role": "result_image"}) for index in range(13)]
    narration = Narration(
        case_id="demo",
        claims=[Claim(claim_id="claim_all", text="证据", supporting_asset_ids=[asset.asset_id for asset in evidence])],
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="展示证据", claim_cues=[ClaimCue(claim_id="claim_all", phrase="证据")])],
    )
    catalog = AssetCatalog(catalog_id="fixture", generated_at="now", source_root="assets", assets=evidence)
    import pytest

    with pytest.raises(ValueError, match="exceeds multimodal image limit"):
        _candidate_assets(CaseConfig(case_id="demo", goal="测试", feature_path=["文生图", "VI"]), narration, catalog)

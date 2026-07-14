from __future__ import annotations

import pytest

from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    BeatSpan,
    CaseConfig,
    Claim,
    ClaimCue,
    EvidenceClass,
    Narration,
    NarrationBeat,
    PhraseAnchor,
    NormalizedRect,
    Provenance,
    TimingLock,
    TokenTiming,
    VisualAnchor,
)
from video_agent.planning.auto_visual import _assets_for_beat, _fit_visual_candidates, _reference_to_result_pair, build_auto_visual_plan
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


def test_reference_pair_requires_explicit_comparison_copy() -> None:
    result = _asset().model_copy(
        update={"asset_id": "asset_result_culture", "role": "result_image", "semantic_path": ["文生图", "文化墙"], "tags": ["医院文化"]}
    )
    reference = result.model_copy(
        update={"asset_id": "asset_reference_culture", "role": "reference_image", "tags": ["实景图", "医院文化"]}
    )
    roles = {"result_image": [result], "reference_image": [reference]}

    assert _reference_to_result_pair("展示文化墙效果。", ["文化墙"], roles, set()) is None
    pair = _reference_to_result_pair("先看实景图，再看文化墙生成效果。", ["文化墙", "实景图"], roles, set())
    assert pair == (reference, result)


def test_reference_pair_never_crosses_feature_paths() -> None:
    result = _asset().model_copy(update={"asset_id": "asset_result_culture", "role": "result_image", "semantic_path": ["文生图", "文化墙"]})
    reference = result.model_copy(
        update={"asset_id": "asset_reference_logo", "role": "reference_image", "semantic_path": ["文生图", "LOGO"]}
    )

    assert _reference_to_result_pair("实景图和生成效果对比。", ["文化墙", "实景图"], {"result_image": [result], "reference_image": [reference]}, set()) is None


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


def test_auto_planner_splits_spoken_feature_enumeration_into_anchor_locked_result_shots() -> None:
    feature_names = ["文化墙", "门店招牌", "景观小品", "美陈", "LOGO"]
    spoken_names = ["文化墙", "门店招牌", "景观小品", "商业美陈", "品牌logo"]
    assets = [
        _asset().model_copy(
            update={
                "asset_id": f"result_{index}",
                "role": "result_image",
                "semantic_path": ["文生图", feature],
                "filename": f"{feature}_结果图.png",
                "provenance": Provenance(origin="curated_result_library"),
            }
        )
        for index, feature in enumerate(feature_names)
    ]
    narration = Narration(
        case_id="demo",
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="文化墙、门店招牌、景观小品、商业美陈、品牌logo。", asset_slots=spoken_names)],
    )
    anchors = [
        PhraseAnchor(anchor_id=f"anchor_{index}", text=phrase, token_ids=["tok_1"], hit_frame=10 + index * 45, beat_id="beat_1")
        for index, phrase in enumerate(spoken_names)
    ]
    timing = TimingLock(
        case_id="demo",
        audio_path="voice.wav",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=8000,
        duration_frames=240,
        tokens=[TokenTiming(token_id="tok_1", text=narration.spoken_text, start_ms=0, end_ms=8000, start_frame=0, end_frame=240, beat_id="beat_1")],
        phrase_anchors=anchors,
        beat_spans=[BeatSpan(beat_id="beat_1", token_ids=["tok_1"], start_frame=0, end_frame=240)],
    )

    visual = build_auto_visual_plan("demo", narration, timing, AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=assets))

    assert [shot.asset_bindings["primary"] for shot in visual.shots] == [f"result_{index}" for index in range(5)]
    assert [shot.transition_in.kind for shot in visual.shots] == ["cut", "slide_left", "slide_left", "slide_left", "slide_left"]
    for shot, anchor in zip(visual.shots, anchors, strict=True):
        start = shot.start.offset_frames or 0
        end = shot.end.offset_frames or timing.duration_frames
        assert start <= anchor.hit_frame < end


def test_auto_planner_keeps_navigation_enumeration_on_feature_entry_flow() -> None:
    entry = _asset().model_copy(update={"asset_id": "entry_culture", "role": "feature_entry", "semantic_path": ["文生图", "文化墙"]})
    result = entry.model_copy(update={"asset_id": "result_culture", "role": "result_image", "provenance": Provenance(origin="curated_result_library")})
    narration = Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="点击进入文化墙、LOGO功能。", asset_slots=["文化墙", "LOGO"])])
    timing = TimingLock(
        case_id="demo", audio_path="voice.wav", audio_sha256="a" * 64, fps=30, duration_ms=3000, duration_frames=90,
        tokens=[TokenTiming(token_id="tok_1", text=narration.spoken_text, start_ms=0, end_ms=3000, start_frame=0, end_frame=90, beat_id="beat_1")],
        phrase_anchors=[PhraseAnchor(anchor_id="culture", text="文化墙", token_ids=["tok_1"], hit_frame=12, beat_id="beat_1")],
        beat_spans=[BeatSpan(beat_id="beat_1", token_ids=["tok_1"], start_frame=0, end_frame=90)],
    )

    visual = build_auto_visual_plan("demo", narration, timing, AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[entry, result]))

    assert visual.shots[0].template == "ui_feature_entry"
    assert visual.shots[0].asset_bindings["primary"] == entry.asset_id


def test_auto_planner_uses_site_home_for_ambiguous_opening_and_results_for_ambiguous_tail() -> None:
    home = _asset().model_copy(update={"asset_id": "site_home", "role": "site_home", "semantic_path": ["柯幻熊猫"]})
    result = _asset().model_copy(update={"asset_id": "result", "role": "result_image", "provenance": Provenance(origin="curated_result_library")})
    narration = Narration(
        case_id="demo",
        beats=[
            NarrationBeat(beat_id="beat_1", spoken_text="这件事其实很简单。"),
            NarrationBeat(beat_id="beat_2", spoken_text="现在就试试看。"),
        ],
    )
    timing = TimingLock(
        case_id="demo", audio_path="voice.wav", audio_sha256="a" * 64, fps=30, duration_ms=6000, duration_frames=180,
        tokens=[
            TokenTiming(token_id="tok_1", text="这件事其实很简单。", start_ms=0, end_ms=3000, start_frame=0, end_frame=90, beat_id="beat_1"),
            TokenTiming(token_id="tok_2", text="现在就试试看。", start_ms=3000, end_ms=6000, start_frame=90, end_frame=180, beat_id="beat_2"),
        ],
        beat_spans=[
            BeatSpan(beat_id="beat_1", token_ids=["tok_1"], start_frame=0, end_frame=90),
            BeatSpan(beat_id="beat_2", token_ids=["tok_2"], start_frame=90, end_frame=180),
        ],
    )

    visual = build_auto_visual_plan("demo", narration, timing, AssetCatalog(catalog_id="demo", generated_at="now", source_root="assets", assets=[home, result]))

    assert visual.shots[0].asset_bindings["primary"] == home.asset_id
    assert visual.shots[0].motion == "page_turn_3d"
    assert visual.shots[-1].asset_bindings["primary"] == result.asset_id


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


def test_multimodal_packet_includes_reference_only_for_explicit_comparison_copy() -> None:
    result = _asset().model_copy(update={"asset_id": "asset_result", "role": "result_image"})
    reference = result.model_copy(update={"asset_id": "asset_reference", "role": "reference_image"})
    catalog = AssetCatalog(catalog_id="fixture", generated_at="now", source_root="assets", assets=[result, reference])
    case = CaseConfig(case_id="demo", goal="测试", feature_path=["文生图", "VI"])

    normal = Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="展示效果")])
    comparison = Narration(case_id="demo", beats=[NarrationBeat(beat_id="beat_1", spoken_text="实景图和生成效果对比")])

    assert [asset.asset_id for asset in _candidate_assets(case, normal, catalog)] == [result.asset_id]
    assert {asset.asset_id for asset in _candidate_assets(case, comparison, catalog)} == {result.asset_id, reference.asset_id}


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

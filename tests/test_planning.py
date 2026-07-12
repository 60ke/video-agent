from __future__ import annotations

from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    CaseConfig,
    EvidenceClass,
    Narration,
    NarrationBeat,
    NormalizedRect,
    Provenance,
    VisualAnchor,
)
from video_agent.planning.auto_visual import _anchor_for_phrase, _assets_for_beat
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


def test_anchor_selection_never_falls_back_to_unrelated_field() -> None:
    asset = _asset()
    assert _anchor_for_phrase(asset, "填写品牌名称") == "anchor_brand"
    assert _anchor_for_phrase(asset, "选择行业") is None


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
    selected = _candidate_assets(CaseConfig(case_id="demo", goal="测试", feature_path=["文生图", "VI"]), catalog)
    assert [asset.asset_id for asset in selected] == [approved.asset_id]

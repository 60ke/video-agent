from __future__ import annotations

from video_agent.ai.action_scene_planner import (
    _normalize_empty_result_gallery_items,
    _normalize_gallery_boundaries,
    _normalize_invalid_asset_gap_decisions,
    _normalize_multi_gap_derivation_scenes,
    _normalize_scene_visual_purposes,
    _validate_asset_gap_decisions,
)
import pytest

from video_agent.ai.asset_index import AIAssetIndex
from video_agent.contracts import (
    ActionScene,
    Asset,
    EvidenceClass,
    Narration,
    NarrationBeat,
    Provenance,
    TimeRef,
)


def test_gallery_items_are_split_at_intervening_scene_boundaries() -> None:
    narration = Narration(
        case_id="gallery_split",
        beats=[
            NarrationBeat(beat_id="beat_001", spoken_text="网站来了"),
            NarrationBeat(
                beat_id="beat_002",
                spoken_text="文化墙、门头招牌、美陈、雕塑小品、主题公园、IP形象、电商、海报",
            ),
        ],
    )
    result = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "scene_kind": "site_home",
                "beat_ids": ["beat_001"],
                "start_phrase": None,
            },
            {
                "scene_id": "scene_002",
                "scene_kind": "result_gallery",
                "narrative_role": "body",
                "visual_purpose": "multi_result_evidence",
                "beat_ids": ["beat_002"],
                "start_phrase": "文化墙",
                "semantic_phrase": "文化墙到海报",
                "feature_path": ["文生图"],
                "asset_bindings": {},
                "gallery_items": [
                    {"asset_id": "A0001", "phrase": "文化墙"},
                    {"asset_id": "A0002", "phrase": "门头招牌"},
                    {"asset_id": "A0003", "phrase": "美陈"},
                    {"asset_id": "A0006", "phrase": "IP形象"},
                    {"asset_id": "A0007", "phrase": "电商"},
                    {"asset_id": "A0008", "phrase": "海报"},
                ],
            },
            {
                "scene_id": "scene_003",
                "scene_kind": "result_detail",
                "beat_ids": ["beat_002"],
                "start_phrase": "雕塑小品",
            },
            {
                "scene_id": "scene_004",
                "scene_kind": "result_detail",
                "beat_ids": ["beat_002"],
                "start_phrase": "主题公园",
            },
        ]
    }

    normalized = _normalize_gallery_boundaries(result, narration)

    assert [item["phrase"] for item in normalized["scenes"][1]["gallery_items"]] == [
        "文化墙",
        "门头招牌",
        "美陈",
    ]
    split = normalized["scenes"][-1]
    assert split["scene_id"] == "scene_auto_split_001"
    assert split["start_phrase"] == "IP形象"
    assert [item["phrase"] for item in split["gallery_items"]] == ["IP形象", "电商", "海报"]


def test_direct_asset_cannot_resolve_an_empty_result_candidate() -> None:
    result = {
        "scenes": [
            {
                "scene_id": "scene_result",
                "scene_kind": "result_detail",
                "beat_ids": ["beat_001"],
                "start_phrase": "效果图",
                "semantic_phrase": "即刻出效果图",
                "asset_bindings": {"primary": "A0001"},
            }
        ],
        "derivation_requests": [],
        "asset_gap_decisions": [
            {
                "beat_id": "beat_001",
                "phrase": "效果图",
                "decision": "light_sweep",
                "reason": "stale decision",
            }
        ],
    }
    selection_report = {
        "flash_result": {
            "phrase_candidates": {"beat_001": {"效果图": []}},
            "phrase_candidate_modes": {"beat_001": {"效果图": "result_item"}},
        }
    }

    with pytest.raises(ValueError, match="requires a matching fallback scene"):
        _validate_asset_gap_decisions(result, selection_report)


def test_empty_exact_candidates_are_removed_from_gallery() -> None:
    result = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "scene_kind": "result_gallery",
                "visual_purpose": "multi_result_evidence",
                "beat_ids": ["beat_001"],
                "start_phrase": "餐饮美食",
                "semantic_phrase": "餐饮美食、品牌LOGO",
                "asset_bindings": {"item_001": "A0001", "item_002": "A0002"},
                "gallery_items": [
                    {"asset_id": "A0001", "phrase": "餐饮美食"},
                    {"asset_id": "A0002", "phrase": "品牌LOGO"},
                ],
            }
        ]
    }
    selection_report = {
        "flash_result": {
            "phrase_candidates": {
                "beat_001": {"餐饮美食": [], "品牌LOGO": ["A0002"]},
            },
            "phrase_candidate_modes": {
                "beat_001": {"餐饮美食": "result_item", "品牌LOGO": "result_item"},
            },
        }
    }

    normalized = _normalize_empty_result_gallery_items(result, selection_report)

    scene = normalized["scenes"][0]
    assert scene["scene_kind"] == "result_detail"
    assert scene["start_phrase"] == "品牌LOGO"
    assert scene["asset_bindings"] == {"primary": "A0002"}
    assert scene["gallery_items"] == []


def test_derived_empty_gallery_items_become_individual_scenes() -> None:
    result = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "scene_kind": "result_gallery",
                "narrative_role": "body",
                "visual_purpose": "multi_result_evidence",
                "beat_ids": ["beat_001"],
                "start_phrase": "产品主KV",
                "semantic_phrase": "产品主KV、规格信息",
                "asset_bindings": {},
                "gallery_items": [
                    {"asset_id": "placeholder_1", "phrase": "产品主KV"},
                    {"asset_id": "placeholder_2", "phrase": "规格信息"},
                ],
                "derivation_request_ids": ["derive_kv", "derive_spec"],
            }
        ],
        "derivation_requests": [
            {"request_id": "derive_kv", "scene_id": "scene_001", "beat_id": "beat_001"},
            {"request_id": "derive_spec", "scene_id": "scene_001", "beat_id": "beat_001"},
        ],
        "asset_gap_decisions": [
            {"beat_id": "beat_001", "phrase": "产品主KV", "decision": "derive", "request_id": "derive_kv"},
            {"beat_id": "beat_001", "phrase": "规格信息", "decision": "derive", "request_id": "derive_spec"},
        ],
    }
    selection_report = {
        "flash_result": {
            "phrase_candidates": {"beat_001": {"产品主KV": [], "规格信息": []}},
            "phrase_candidate_modes": {
                "beat_001": {"产品主KV": "result_item", "规格信息": "result_item"}
            },
        }
    }

    normalized = _normalize_empty_result_gallery_items(result, selection_report)

    assert [scene["start_phrase"] for scene in normalized["scenes"]] == ["产品主KV", "规格信息"]
    assert all(scene["scene_kind"] == "result_detail" for scene in normalized["scenes"])
    assert normalized["scenes"][0]["derivation_request_ids"] == ["derive_kv"]
    assert normalized["scenes"][1]["derivation_request_ids"] == ["derive_spec"]
    assert normalized["derivation_requests"][0]["scene_id"] == normalized["scenes"][0]["scene_id"]
    assert normalized["derivation_requests"][1]["scene_id"] == normalized["scenes"][1]["scene_id"]


def test_invalid_exact_gap_is_derived_from_same_beat_result() -> None:
    source = Asset(
        asset_id="asset_result",
        path="assets/results/ecommerce.png",
        filename="ecommerce.png",
        sha256="a" * 64,
        role="result_image",
        semantic_path=["文生图", "电商"],
        width=1600,
        height=900,
        evidence_class=EvidenceClass.SOURCE,
        provenance=Provenance(origin="test"),
    )
    reference = Asset(
        asset_id="asset_reference",
        path="assets/references/spec.png",
        filename="spec.png",
        sha256="b" * 64,
        role="reference_image",
        semantic_path=["文生图", "电商"],
        width=900,
        height=1600,
        evidence_class=EvidenceClass.SOURCE,
        provenance=Provenance(origin="test"),
    )
    index = AIAssetIndex.build([source, reference])
    source_ref = index.ref_for_asset(source)
    reference_ref = index.ref_for_asset(reference)
    result = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "scene_kind": "result_detail",
                "visual_purpose": "single_result_evidence",
                "beat_ids": ["beat_001"],
                "semantic_phrase": "规格信息",
                "start_phrase": "规格信息",
                "feature_path": ["文生图", "电商"],
                "asset_bindings": {"primary": reference_ref},
                "gallery_items": [],
                "derivation_request_ids": [],
            }
        ],
        "derivation_requests": [],
        "asset_gap_decisions": [
            {
                "beat_id": "beat_001",
                "phrase": "规格信息",
                "decision": "exact",
                "reason": "nearby reference",
            }
        ],
    }
    selection_report = {
        "flash_result": {
            "beat_candidates": {"beat_001": [source_ref, reference_ref]},
            "phrase_candidates": {"beat_001": {"规格信息": []}},
            "phrase_candidate_modes": {"beat_001": {"规格信息": "result_item"}},
        }
    }
    narration = Narration(
        case_id="gap_repair",
        beats=[NarrationBeat(beat_id="beat_001", spoken_text="包含规格信息")],
    )

    normalized = _normalize_invalid_asset_gap_decisions(
        result, selection_report, narration, index
    )

    decision = normalized["asset_gap_decisions"][0]
    request = normalized["derivation_requests"][0]
    scene = normalized["scenes"][0]
    assert decision["decision"] == "derive"
    assert request["source_asset_id"] == source_ref
    assert request["semantic_phrase"] == "规格信息"
    assert request["target_orientation"] == "landscape"
    assert scene["asset_bindings"] == {}
    assert scene["derivation_request_ids"] == [request["request_id"]]


def test_light_sweep_scene_does_not_require_an_image_asset() -> None:
    scene = ActionScene(
        scene_id="scene_fallback",
        scene_kind="light_sweep_fallback",
        narrative_role="body",
        visual_purpose="abstract_bridge",
        beat_ids=["beat_001"],
        semantic_phrase="无素材过渡",
        start=TimeRef(anchor_id="timeline_start"),
        end=TimeRef(anchor_id="timeline_end"),
        fallback_policy="light_sweep",
    )

    assert scene.asset_bindings == {}


def test_shared_result_derivations_are_split_at_their_spoken_phrases() -> None:
    narration = Narration(
        case_id="split_derivations",
        beats=[NarrationBeat(beat_id="beat_001", spoken_text="包含产品主KV、规格信息和应用场景")],
    )
    result = {
        "scenes": [
            {
                "scene_id": "scene_001",
                "scene_kind": "result_gallery",
                "narrative_role": "closing",
                "visual_purpose": "multi_result_evidence",
                "beat_ids": ["beat_001"],
                "semantic_phrase": "产品主KV、规格信息和应用场景",
                "start_phrase": "产品主KV",
                "feature_path": ["文生图", "电商"],
                "asset_bindings": {},
                "gallery_items": [],
                "derivation_request_ids": ["derive_kv", "derive_spec", "derive_scene"],
            }
        ],
        "derivation_requests": [
            {
                "request_id": "derive_scene",
                "derive_kind": "contextual_result_fill",
                "semantic_phrase": "应用场景",
                "semantic_path": ["文生图", "电商"],
            },
            {
                "request_id": "derive_kv",
                "derive_kind": "contextual_result_fill",
                "semantic_phrase": "产品主KV",
                "semantic_path": ["文生图", "电商"],
            },
            {
                "request_id": "derive_spec",
                "derive_kind": "contextual_result_fill",
                "semantic_phrase": "规格信息",
                "semantic_path": ["文生图", "电商"],
            },
        ],
    }

    normalized = _normalize_multi_gap_derivation_scenes(result, narration)

    assert [scene["start_phrase"] for scene in normalized["scenes"]] == [
        "产品主KV",
        "规格信息",
        "应用场景",
    ]
    assert normalized["scenes"][-1]["narrative_role"] == "closing"
    assert all(scene["scene_kind"] == "result_detail" for scene in normalized["scenes"])
    requests = {request["request_id"]: request for request in normalized["derivation_requests"]}
    assert requests["derive_spec"]["scene_id"] == "scene_001_derive_02"
    assert requests["derive_spec"]["semantic_path"][-1] == "规格信息"


def test_scene_kind_repairs_deterministic_visual_purpose() -> None:
    normalized = _normalize_scene_visual_purposes(
        {
            "scenes": [
                {
                    "scene_id": "scene_reference",
                    "scene_kind": "reference_input",
                    "narrative_role": "body",
                    "visual_purpose": "parameter_operation",
                },
                {
                    "scene_id": "scene_close",
                    "scene_kind": "light_sweep_fallback",
                    "narrative_role": "closing",
                    "visual_purpose": "abstract_bridge",
                },
            ]
        }
    )

    assert normalized["scenes"][0]["visual_purpose"] == "causal_evidence"
    assert normalized["scenes"][1]["visual_purpose"] == "brand_close"

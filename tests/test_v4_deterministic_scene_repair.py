from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_agent.contracts.v4 import DomainValidationError, SceneSemanticPlan
from video_agent.contracts.v4.common import normalize_frozen_text
from video_agent.registries import CapabilityRegistrySnapshot
from video_agent.semantic.deterministic_scene_repair import repair_scene_plan_payload
from video_agent.semantic.validation import validate_scene_semantic_plan


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "v4" / "stage0"
FROZEN_NARRATION = (
    "想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。"
    "文化墙、门头招牌、美陈，都能一键出图。"
    "以文化墙为例，进入功能页，填上行业和风格，点击生成，一整面文化墙方案直接出来了。"
    "细节不满意？选中它继续编辑，改完直接用。"
    "还能上传实景参考图，按你的现场出效果，连施工平面图都能一并导出。"
    "设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。"
)


def test_deterministic_repair_splits_result_and_rewrites_causal_and_editor() -> None:
    registry = CapabilityRegistrySnapshot.model_validate(
        json.loads((FIXTURE_DIR / "registry_snapshot.json").read_text(encoding="utf-8"))
    )
    # Shape mirrors the failed Stage7 live rebuild draft.
    payload = {
        "scenes": [
            {
                "scene_id": "sc1",
                "order": 1,
                "text": "想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "s1",
                        "anchor_phrase": "打开柯幻熊猫",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "网站/主页",
                        "asset_role": "site_home",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "sc2",
                "order": 2,
                "text": "文化墙、门头招牌、美陈，都能一键出图。",
                "visual_structure": "gallery",
                "slots": [
                    {
                        "slot_id": "g1",
                        "anchor_phrase": "文化墙",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "keyword",
                    },
                    {
                        "slot_id": "g2",
                        "anchor_phrase": "门头招牌",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/门头招牌",
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "keyword",
                    },
                    {
                        "slot_id": "g3",
                        "anchor_phrase": "美陈",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/美陈",
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "keyword",
                    },
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "sc3",
                "order": 3,
                "text": "以文化墙为例，进入功能页，填上行业和风格，点击生成，一整面文化墙方案直接出来了。",
                "visual_structure": "sequence",
                "slots": [
                    {
                        "slot_id": "base",
                        "anchor_phrase": "填上行业和风格",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "parameter_panel",
                        "source": {
                            "kind": "asset_group_query",
                            "group_alias": "wall_params",
                            "group_type": "process",
                            "pattern_id": "parameter_callout_sequence",
                            "member_key": "base",
                        },
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "stage",
                        "anchor_phrase": "点击生成",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "parameter_panel",
                        "source": {
                            "kind": "group_member",
                            "group_alias": "wall_params",
                            "group_type": "process",
                            "pattern_id": "parameter_callout_sequence",
                            "member_key": "stage",
                        },
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "final",
                        "anchor_phrase": "一整面文化墙方案直接出来了",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/文化墙",
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    },
                ],
                "events": [],
                "inputs": [],
                "outputs": [{"output_name": "wall_result", "bound_slot": "final", "asset_role": "result_image"}],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "sc4",
                "order": 4,
                "text": "细节不满意？选中它继续编辑，改完直接用。",
                "visual_structure": "sequence",
                "slots": [
                    {
                        "slot_id": "s1",
                        "anchor_phrase": "选中它",
                        "entry_policy": "scene_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "result_image",
                        "source": {"kind": "scene_input", "input_name": "previous_result"},
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "editor_page",
                        "anchor_phrase": "继续编辑",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "editor_page",
                        "source": {
                            "kind": "relation_from_input",
                            "input_name": "previous_result",
                            "group_alias": "wall_edit",
                            "group_type": "process",
                            "pattern_id": "editor_sequence",
                            "member_key": "editor_page",
                        },
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "edited_result",
                        "anchor_phrase": "改完直接用",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/文化墙",
                        "asset_role": "edited_result",
                        "source": {
                            "kind": "group_member",
                            "group_alias": "wall_edit",
                            "group_type": "process",
                            "pattern_id": "editor_sequence",
                            "member_key": "edited_result",
                        },
                        "subtitle_emphasis": "none",
                    },
                ],
                "events": [],
                "inputs": [
                    {
                        "input_name": "previous_result",
                        "from_scene": "sc3",
                        "from_output": "wall_result",
                        "required": True,
                    }
                ],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "sc5",
                "order": 5,
                "text": "还能上传实景参考图，按你的现场出效果，连施工平面图都能一并导出。",
                "visual_structure": "sequence",
                "slots": [
                    {
                        "slot_id": "ref",
                        "anchor_phrase": "实景参考图",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "reference_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "res",
                        "anchor_phrase": "按你的现场出效果",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "result_image",
                        "source": {
                            "kind": "asset_group_query",
                            "group_alias": "ref_plan",
                            "group_type": "causal",
                            "pattern_id": "reference_result_plan",
                            "member_key": "result_image",
                        },
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "plan",
                        "anchor_phrase": "施工平面图",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/文化墙",
                        "asset_role": "flat_plan",
                        "source": {
                            "kind": "group_member",
                            "group_alias": "ref_plan",
                            "group_type": "causal",
                            "pattern_id": "reference_result_plan",
                            "member_key": "flat_plan",
                        },
                        "subtitle_emphasis": "none",
                    },
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "sc6",
                "order": 6,
                "text": "设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "outro",
                        "anchor_phrase": "搜索柯幻熊猫",
                        "entry_policy": "scene_start",
                        "hold_policy": "scene_end",
                        "category_id": None,
                        "asset_role": "outro",
                        "source": {"kind": "configured_asset", "config_key": "default_outro"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
        ]
    }
    repaired = repair_scene_plan_payload(payload)
    plan = SceneSemanticPlan.model_validate(repaired)
    validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    structures = [scene.visual_structure for scene in plan.scenes]
    assert "comparison" in structures
    assert any(scene.outputs for scene in plan.scenes if scene.visual_structure == "single")
    editor = next(scene for scene in plan.scenes if "继续编辑" in scene.text)
    assert all(slot.source.kind == "relation_from_input" for slot in editor.slots)


def test_deterministic_repair_covers_multiline_frozen_and_claim_phrases() -> None:
    registry = CapabilityRegistrySnapshot.model_validate(
        json.loads((FIXTURE_DIR / "registry_snapshot.json").read_text(encoding="utf-8"))
    )
    frozen = (
        "专为广告人量身定制的 AI 设计网站来了！\n"
        "从文化墙、门头招牌到海报等文生图设计功能\n"
        "这就是专为广告从业者研发的AI智能体！"
    )
    payload = {
        "scenes": [
            {
                "scene_id": "a",
                "order": 1,
                "text": "专为广告人量身定制的 AI 设计网站来了！",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "home",
                        "anchor_phrase": "AI 设计网站",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": None,
                        "asset_role": "site_home",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [
                    {
                        "claim_id": "real_website_screenshot",
                        "phrase": "real_website_screenshot",
                        "quantifier": "any",
                        "supporting_slots": ["home"],
                        "evidence_window": "anchor",
                    }
                ],
                "no_asset": False,
            },
            {
                "scene_id": "b",
                "order": 2,
                "text": "从文化墙、门头招牌到海报等文生图设计功能",
                "visual_structure": "gallery",
                "slots": [
                    {
                        "slot_id": "g1",
                        "anchor_phrase": "文化墙",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": None,
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "keyword",
                    },
                    {
                        "slot_id": "g2",
                        "anchor_phrase": "门头招牌",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": None,
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "keyword",
                    },
                    {
                        "slot_id": "g3",
                        "anchor_phrase": "海报",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": None,
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "keyword",
                    },
                ],
                "events": [],
                "inputs": [],
                "outputs": [{"output_name": "bad", "bound_slot": "missing", "asset_role": "result_image"}],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "c",
                "order": 3,
                "text": "这就是专为广告从业者研发的AI智能体！",
                "visual_structure": "no_asset_transition",
                "slots": [],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": True,
            },
        ]
    }
    repaired = repair_scene_plan_payload(
        payload,
        frozen_narration=frozen,
        category_ids=["文生图/文化墙", "文生图/门头招牌", "文生图/海报"],
        primary_category_id="文生图/文化墙",
    )
    plan = SceneSemanticPlan.model_validate(repaired)
    validate_scene_semantic_plan(plan, frozen_narration=frozen, registry=registry)
    assert "".join(scene.text for scene in sorted(plan.scenes, key=lambda item: item.order)) == normalize_frozen_text(
        frozen
    )
    assert plan.scenes[0].claims[0].phrase == "AI 设计网站"
    assert plan.scenes[1].outputs == []
    assert all(slot.category_id == "文生图/文化墙" for slot in plan.scenes[1].slots)
    last = plan.scenes[-1]
    assert last.no_asset is False
    assert last.slots[0].asset_role == "site_home"
    assert last.slots[0].source.kind == "asset_query"


def test_deterministic_repair_fills_empty_brand_close_with_site_home() -> None:
    registry = CapabilityRegistrySnapshot.model_validate(
        json.loads((FIXTURE_DIR / "registry_snapshot.json").read_text(encoding="utf-8"))
    )
    frozen = "打开网站，二十多项编辑小工具随手可用。这就是专为广告从业者研发的AI智能体！"
    payload = {
        "scenes": [
            {
                "scene_id": "a",
                "order": 1,
                "text": "打开网站，二十多项编辑小工具随手可用。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "home",
                        "anchor_phrase": "打开网站",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": None,
                        "asset_role": "site_home",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "b",
                "order": 2,
                "text": "这就是专为广告从业者研发的AI智能体！",
                "visual_structure": "no_asset_transition",
                "slots": [],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": True,
            },
        ]
    }
    repaired = repair_scene_plan_payload(payload, frozen_narration=frozen)
    plan = SceneSemanticPlan.model_validate(repaired)
    validate_scene_semantic_plan(plan, frozen_narration=frozen, registry=registry)
    assert plan.scenes[0].slots[0].asset_role == "site_home"
    last = plan.scenes[-1]
    assert last.slots[0].asset_role == "site_home"
    assert last.slots[0].source.kind == "asset_query"
    assert last.no_asset is False


def test_deterministic_repair_hold_extends_soft_empty_from_prior_result() -> None:
    registry = CapabilityRegistrySnapshot.model_validate(
        json.loads((FIXTURE_DIR / "registry_snapshot.json").read_text(encoding="utf-8"))
    )
    frozen = "一分钟即可出一套完整详情页。简单好上手！"
    payload = {
        "scenes": [
            {
                "scene_id": "a",
                "order": 1,
                "text": "一分钟即可出一套完整详情页。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "r1",
                        "anchor_phrase": "完整详情页",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/电商",
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "b",
                "order": 2,
                "text": "简单好上手！",
                "visual_structure": "no_asset_transition",
                "slots": [],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": True,
            },
        ]
    }
    repaired = repair_scene_plan_payload(
        payload,
        frozen_narration=frozen,
        primary_category_id="文生图/电商",
    )
    plan = SceneSemanticPlan.model_validate(repaired)
    validate_scene_semantic_plan(plan, frozen_narration=frozen, registry=registry)
    assert plan.scenes[0].outputs
    last = plan.scenes[-1]
    assert last.slots[0].slot_id == "hold_extend"
    assert last.slots[0].source.kind == "scene_input"
    assert last.inputs[0].from_scene == plan.scenes[0].scene_id
    assert last.no_asset is False


def test_deterministic_repair_fills_empty_mid_scene_not_only_terminal() -> None:
    registry = CapabilityRegistrySnapshot.model_validate(
        json.loads((FIXTURE_DIR / "registry_snapshot.json").read_text(encoding="utf-8"))
    )
    frozen = "设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。"
    payload = {
        "scenes": [
            {
                "scene_id": "a",
                "order": 1,
                "text": "设计这件事，从没这么省心。",
                "visual_structure": "no_asset_transition",
                "slots": [],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": True,
            },
            {
                "scene_id": "b",
                "order": 2,
                "text": "搜索柯幻熊猫，今天就试试。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "outro",
                        "anchor_phrase": "搜索柯幻熊猫",
                        "entry_policy": "scene_start",
                        "hold_policy": "scene_end",
                        "category_id": None,
                        "asset_role": "outro",
                        "source": {"kind": "configured_asset", "config_key": "default_outro"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
        ]
    }
    repaired = repair_scene_plan_payload(payload, frozen_narration=frozen)
    plan = SceneSemanticPlan.model_validate(repaired)
    validate_scene_semantic_plan(plan, frozen_narration=frozen, registry=registry)
    assert plan.scenes[0].no_asset is False
    assert plan.scenes[0].slots[0].asset_role == "site_home"
    assert plan.scenes[-1].slots[0].asset_role == "outro"
    assert plan.scenes[-1].slots[0].source.config_key == "default_outro"


def test_unstocked_reference_result_keeps_derivable_causal_flow() -> None:
    """Missing stock must remain a causal flow so Stage4 can derive its members."""
    registry = CapabilityRegistrySnapshot.model_validate(
        json.loads((FIXTURE_DIR / "registry_snapshot.json").read_text(encoding="utf-8"))
    )
    frozen = "上传商品图、填写名称和品类，一分钟即可出一套完整详情页。搜索柯幻熊猫，今天就试试。"
    payload = {
        "scenes": [
            {
                "scene_id": "s001",
                "order": 1,
                "text": "上传商品图、填写名称和品类，一分钟即可出一套完整详情页。",
                "visual_structure": "sequence",
                "slots": [
                    {
                        "slot_id": "upload_ref",
                        "anchor_phrase": "上传商品图",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/电商",
                        "asset_role": "reference_image",
                        "source": {
                            "kind": "asset_group_query",
                            "group_alias": "detail_flow",
                            "group_type": "causal",
                            "pattern_id": "reference_result_plan",
                            "member_key": "reference_image",
                        },
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "result_page",
                        "anchor_phrase": "完整详情页",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/电商",
                        "asset_role": "result_image",
                        "source": {
                            "kind": "group_member",
                            "group_alias": "detail_flow",
                            "group_type": "causal",
                            "pattern_id": "reference_result_plan",
                            "member_key": "result_image",
                        },
                        "subtitle_emphasis": "none",
                    },
                ],
                "events": [
                    {
                        "event_id": "ev_upload",
                        "phrase": "上传商品图",
                        "intent": "upload",
                        "target_slot": "upload_ref",
                    },
                    {
                        "event_id": "ev_generate",
                        "phrase": "一分钟即可出一套完整详情页",
                        "intent": "generate",
                        "target_slot": "result_page",
                    },
                ],
                "inputs": [],
                "outputs": [{"output_name": "final_result", "bound_slot": "result_page", "asset_role": "result_image"}],
                "claims": [],
                "no_asset": False,
            },
            {
                "scene_id": "s002",
                "order": 2,
                "text": "搜索柯幻熊猫，今天就试试。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "outro",
                        "anchor_phrase": "搜索柯幻熊猫",
                        "entry_policy": "scene_start",
                        "hold_policy": "scene_end",
                        "category_id": None,
                        "asset_role": "outro",
                        "source": {"kind": "configured_asset", "config_key": "default_outro"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
        ]
    }
    repaired = repair_scene_plan_payload(payload, frozen_narration=frozen)
    plan = SceneSemanticPlan.model_validate(repaired)
    validate_scene_semantic_plan(plan, frozen_narration=frozen, registry=registry)
    causal = plan.scenes[0]
    assert [slot.slot_id for slot in causal.slots] == ["upload_ref", "result_page"]
    assert causal.slots[0].source.kind == "asset_group_query"
    assert causal.slots[1].source.kind == "group_member"
    assert {event.target_slot for event in causal.events} == {"upload_ref", "result_page"}


def test_repair_rewrites_nfkc_equivalent_claim_phrase_to_verbatim_scene_span() -> None:
    payload = {
        "scenes": [
            {
                "scene_id": "s002",
                "order": 1,
                "text": "用柯幻熊猫,一个人一分钟就可以搞定 ",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "home",
                        "anchor_phrase": "柯幻熊猫",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "网站/主页",
                        "asset_role": "site_home",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [
                    {
                        "claim_id": "real_website_screenshot",
                        "phrase": "用柯幻熊猫，一个人一分钟就可以搞定",
                        "supporting_slots": ["home"],
                        "evidence_window": "anchor",
                        "quantifier": "exists",
                    }
                ],
                "no_asset": False,
            },
            {
                "scene_id": "s007",
                "order": 2,
                "text": "简单好上手！",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "outro_slot",
                        "anchor_phrase": "简单好上手",
                        "entry_policy": "scene_start",
                        "hold_policy": "scene_end",
                        "category_id": None,
                        "asset_role": "outro",
                        "source": {"kind": "configured_asset", "config_key": "default_outro"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            },
        ]
    }
    repaired = repair_scene_plan_payload(payload)
    claim = repaired["scenes"][0]["claims"][0]
    scene_text = repaired["scenes"][0]["text"]
    assert claim["phrase"] in scene_text
    assert "，" not in claim["phrase"]
    assert "," in claim["phrase"]


def test_repair_binds_standalone_editor_queries_to_prior_result() -> None:
    payload = {
        "scenes": [
            {
                "scene_id": "result",
                "order": 1,
                "text": "生成文化墙效果图。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "result",
                        "anchor_phrase": "文化墙效果图",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/文化墙",
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [
                    {"output_name": "primary_result", "bound_slot": "result", "asset_role": "result_image"}
                ],
                "claims": [],
            },
            {
                "scene_id": "edit",
                "order": 2,
                "text": "进入编辑页面继续修改。",
                "visual_structure": "sequence",
                "slots": [
                    {
                        "slot_id": "editor",
                        "anchor_phrase": "编辑页面",
                        "entry_policy": "phrase_start",
                        "hold_policy": "until_next_slot",
                        "category_id": "文生图/文化墙",
                        "asset_role": "editor_page",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    },
                    {
                        "slot_id": "edited",
                        "anchor_phrase": "继续修改",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/文化墙",
                        "asset_role": "edited_result",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    },
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
            },
        ]
    }
    plan = SceneSemanticPlan.model_validate(
        repair_scene_plan_payload(payload, frozen_narration="生成文化墙效果图。进入编辑页面继续修改。")
    )
    editor = plan.scenes[1]
    assert editor.inputs[0].from_scene == plan.scenes[0].scene_id
    assert editor.inputs[0].from_output == "primary_result"
    assert {slot.source.kind for slot in editor.slots} == {"relation_from_input"}
    assert {slot.source.pattern_id for slot in editor.slots} == {"editor_sequence"}


def test_repair_binds_standalone_flat_plan_to_prior_result() -> None:
    payload = {
        "scenes": [
            {
                "scene_id": "result",
                "order": 1,
                "text": "生成景观小品效果图。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "result",
                        "anchor_phrase": "景观小品效果图",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/景观小品",
                        "asset_role": "result_image",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [
                    {"output_name": "primary_result", "bound_slot": "result", "asset_role": "result_image"}
                ],
                "claims": [],
            },
            {
                "scene_id": "plan",
                "order": 2,
                "text": "还能导出施工平面图。",
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "plan",
                        "anchor_phrase": "施工平面图",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/景观小品",
                        "asset_role": "flat_plan",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
            },
        ]
    }
    plan = SceneSemanticPlan.model_validate(
        repair_scene_plan_payload(payload, frozen_narration="生成景观小品效果图。还能导出施工平面图。")
    )
    flat_plan = plan.scenes[1]
    assert flat_plan.inputs[0].from_scene == plan.scenes[0].scene_id
    assert flat_plan.slots[0].source.kind == "relation_from_input"
    assert flat_plan.slots[0].source.pattern_id == "reference_result_plan"
    assert flat_plan.slots[0].source.member_key == "flat_plan"


def test_dependent_query_without_prior_result_fails_with_explicit_dependency_error() -> None:
    registry = CapabilityRegistrySnapshot.model_validate(
        json.loads((FIXTURE_DIR / "registry_snapshot.json").read_text(encoding="utf-8"))
    )
    narration = "直接进入编辑页面。"
    payload = {
        "scenes": [
            {
                "scene_id": "edit",
                "order": 1,
                "text": narration,
                "visual_structure": "single",
                "slots": [
                    {
                        "slot_id": "editor",
                        "anchor_phrase": "编辑页面",
                        "entry_policy": "phrase_start",
                        "hold_policy": "scene_end",
                        "category_id": "文生图/文化墙",
                        "asset_role": "editor_page",
                        "source": {"kind": "asset_query"},
                        "subtitle_emphasis": "none",
                    }
                ],
                "events": [],
                "inputs": [],
                "outputs": [],
                "claims": [],
                "no_asset": False,
            }
        ]
    }
    plan = SceneSemanticPlan.model_validate(repair_scene_plan_payload(payload, frozen_narration=narration))
    with pytest.raises(DomainValidationError) as exc:
        validate_scene_semantic_plan(plan, frozen_narration=narration, registry=registry)
    assert {issue.code for issue in exc.value.issues} == {"scene_dependency_source_missing"}

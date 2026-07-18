from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from video_agent.contracts.v4 import DomainValidationError, SceneSemanticPlan, VideoScope
from video_agent.registries import CapabilityRegistrySnapshot
from video_agent.semantic import validate_scene_semantic_plan, validate_video_scope


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "v4" / "stage0"
FROZEN_NARRATION = (
    "想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。"
    "文化墙、门头招牌、美陈，都能一键出图。"
    "以文化墙为例，进入功能页，填上行业和风格，点击生成，一整面文化墙方案直接出来了。"
    "细节不满意？选中它继续编辑，改完直接用。"
    "还能上传实景参考图，按你的现场出效果，连施工平面图都能一并导出。"
    "设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。"
)


def _json(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def registry() -> CapabilityRegistrySnapshot:
    return CapabilityRegistrySnapshot.model_validate(_json("registry_snapshot.json"))


def test_stage0_golden_scope_passes(registry: CapabilityRegistrySnapshot) -> None:
    scope = VideoScope.model_validate(_json("video_scope.payload.json"))
    validate_video_scope(
        scope,
        frozen_narration=FROZEN_NARRATION,
        registry=registry,
        primary_required=True,
    )


def test_stage0_golden_scene_plan_passes(registry: CapabilityRegistrySnapshot) -> None:
    plan = SceneSemanticPlan.model_validate(_json("scene_semantic_plan.payload.json"))
    result = validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    assert len(result.scene_spans) == 10
    assert result.scene_spans[0].start == 0
    assert result.scene_spans[-1].end > result.scene_spans[-1].start


def test_scope_rejects_unregistered_category(registry: CapabilityRegistrySnapshot) -> None:
    payload = _json("video_scope.payload.json")
    payload["categories"][0]["category_id"] = "文生图/不存在"
    scope = VideoScope.model_validate(payload)
    with pytest.raises(DomainValidationError, match="enabled scope category"):
        validate_video_scope(scope, frozen_narration=FROZEN_NARRATION, registry=registry)


def test_scene_plan_rejects_narration_rewrite(registry: CapabilityRegistrySnapshot) -> None:
    payload = _json("scene_semantic_plan.payload.json")
    payload["scenes"][0]["text"] = payload["scenes"][0]["text"].replace("柯幻熊猫", "别的网站")
    plan = SceneSemanticPlan.model_validate(payload)
    with pytest.raises(DomainValidationError) as error:
        validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    assert any(issue.code == "narration_coverage" for issue in error.value.issues)


def test_gallery_rejects_missing_enumerated_slot(registry: CapabilityRegistrySnapshot) -> None:
    payload = _json("scene_semantic_plan.payload.json")
    scene = payload["scenes"][1]
    scene["slots"] = [slot for slot in scene["slots"] if slot["slot_id"] != "g2"]
    plan = SceneSemanticPlan.model_validate(payload)
    with pytest.raises(DomainValidationError) as error:
        validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    assert any(issue.code in {"unknown_slot", "gallery_anchor_order"} for issue in error.value.issues)


def test_sequence_rejects_unrelated_asset_queries(registry: CapabilityRegistrySnapshot) -> None:
    payload = _json("scene_semantic_plan.payload.json")
    scene = payload["scenes"][3]
    for slot in scene["slots"]:
        slot["source"] = {"kind": "asset_query"}
    plan = SceneSemanticPlan.model_validate(payload)
    with pytest.raises(DomainValidationError) as error:
        validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    assert any(issue.code == "unrelated_structured_slots" for issue in error.value.issues)


def test_scene_dependency_must_point_backward(registry: CapabilityRegistrySnapshot) -> None:
    payload = copy.deepcopy(_json("scene_semantic_plan.payload.json"))
    payload["scenes"][5]["inputs"][0]["from_scene"] = "s007"
    plan = SceneSemanticPlan.model_validate(payload)
    with pytest.raises(DomainValidationError) as error:
        validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    assert any(issue.code == "invalid_scene_dependency" for issue in error.value.issues)


def test_relation_pattern_rejects_wrong_member_role(registry: CapabilityRegistrySnapshot) -> None:
    payload = copy.deepcopy(_json("scene_semantic_plan.payload.json"))
    payload["scenes"][5]["slots"][1]["source"]["member_key"] = "edited_result"
    plan = SceneSemanticPlan.model_validate(payload)
    with pytest.raises(DomainValidationError) as error:
        validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    assert any(issue.code == "pattern_member_role_mismatch" for issue in error.value.issues)


def test_cross_scene_group_alias_keeps_same_upstream_output(registry: CapabilityRegistrySnapshot) -> None:
    payload = copy.deepcopy(_json("scene_semantic_plan.payload.json"))
    payload["scenes"][7]["inputs"][0]["from_scene"] = "s006"
    payload["scenes"][7]["inputs"][0]["from_output"] = "edited_result"
    plan = SceneSemanticPlan.model_validate(payload)
    with pytest.raises(DomainValidationError) as error:
        validate_scene_semantic_plan(plan, frozen_narration=FROZEN_NARRATION, registry=registry)
    assert any(issue.code == "group_binding_mismatch" for issue in error.value.issues)

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_agent.assets.v4_validation import validate_asset_against_registry, validate_group_against_assets
from video_agent.contracts.v4 import AssetGroup, AssetRecord, DomainValidationError
from video_agent.registries import CapabilityRegistryHub


REGISTRY_ROOT = Path(__file__).parents[1] / "config" / "registries" / "v4"
SHA = "a" * 64


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(REGISTRY_ROOT)


def _asset_payload(
    asset_ref: str = "asset://A0001",
    *,
    asset_role: str = "result_image",
    filename: str = "结果图_01.png",
    category: bool = True,
) -> dict:
    payload = {
        "asset_ref": asset_ref,
        "filename": filename,
        "object_key": f"results/文生图/文化墙/{filename}",
        "content_sha256": SHA,
        "media_type": "image/png",
        "module": "文生图" if category else None,
        "category_id": "文生图/文化墙" if category else None,
        "category_path": ["文化墙"] if category else [],
        "asset_role": asset_role,
        "case_label": "社区服务",
        "industry": None,
        "description": "社区服务文化墙效果图",
        "width": 1920,
        "height": 1080,
        "orientation": "landscape",
        "animated": False,
        "source_kind": "original",
        "origin_type": "imported",
        "evidence_class": "E0_source_evidence",
        "claims": ["feature_can_generate_result"],
        "status": "active",
        "superseded_by": None,
        "lineage": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return payload


def _asset(payload: dict) -> AssetRecord:
    return AssetRecord.model_validate_json(json.dumps(payload, ensure_ascii=False))


def _derived_payload(asset_ref: str = "asset://A0002") -> dict:
    payload = _asset_payload(asset_ref, filename="派生结果图_01.png")
    payload.update(
        {
            "source_kind": "derived",
            "origin_type": "gpt_image",
            "evidence_class": "E2_semantic_derivative",
            "claims": [],
            "lineage": {
                "parent_asset_refs": ["asset://A0001"],
                "derivation_type": "result_to_reference_mock",
                "executor_id": "gpt_image",
                "provider": "configured-provider",
                "model": "configured-model",
                "prompt_template_version": "test-v1",
                "prompt_sha256": "b" * 64,
                "parameters_sha256": "c" * 64,
                "derivation_signature": "d" * 64,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
    return payload


def test_original_and_derived_asset_contracts_pass(hub: CapabilityRegistryHub) -> None:
    original = _asset(_asset_payload())
    derived = _asset(_derived_payload())

    validate_asset_against_registry(original, hub)
    validate_asset_against_registry(derived, hub)
    assert derived.lineage is not None
    assert derived.lineage.parent_asset_refs == [original.asset_ref]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("object_key", "C:/private/result.png", "relative POSIX"),
        ("object_key", "results/../result.png", "relative POSIX"),
        ("object_key", "results\\result.png", "normalized POSIX"),
        ("orientation", "portrait", "orientation must match dimensions"),
    ],
)
def test_asset_rejects_invalid_location_and_media_shape(field: str, value: str, message: str) -> None:
    payload = _asset_payload()
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        _asset(payload)


def test_asset_rejects_filename_category_and_review_fields() -> None:
    payload = _asset_payload()
    payload["filename"] = "different.png"
    with pytest.raises(ValidationError, match="filename must equal"):
        _asset(payload)

    payload = _asset_payload()
    payload["category_id"] = "文生图/门头招牌"
    with pytest.raises(ValidationError, match="category_id does not match"):
        _asset(payload)

    payload = _asset_payload()
    payload["review_status"] = "human_approved"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _asset(payload)


def test_lineage_evidence_and_lifecycle_invariants() -> None:
    payload = _asset_payload()
    payload["source_kind"] = "derived"
    with pytest.raises(ValidationError, match="derived assets require lineage"):
        _asset(payload)

    payload = _derived_payload()
    payload["claims"] = ["feature_can_generate_result"]
    with pytest.raises(ValidationError, match="E2/E3 assets cannot support"):
        _asset(payload)

    payload = _asset_payload()
    payload["status"] = "superseded"
    with pytest.raises(ValidationError, match="superseded assets require"):
        _asset(payload)

    payload = _asset_payload()
    payload["lineage"] = _derived_payload()["lineage"]
    with pytest.raises(ValidationError, match="original assets cannot have lineage"):
        _asset(payload)


def test_dynamic_role_is_structurally_valid_but_registry_rejected(hub: CapabilityRegistryHub) -> None:
    payload = _asset_payload(asset_role="future_role")
    asset = _asset(payload)

    with pytest.raises(DomainValidationError) as error:
        validate_asset_against_registry(asset, hub)
    assert any(issue.code == "unknown_asset_role" for issue in error.value.issues)


def test_role_category_and_claim_policy_is_enforced(hub: CapabilityRegistryHub) -> None:
    result_without_category = _asset(_asset_payload(category=False))
    with pytest.raises(DomainValidationError) as error:
        validate_asset_against_registry(result_without_category, hub)
    assert any(issue.code == "category_required" for issue in error.value.issues)

    logo_payload = _asset_payload(asset_role="brand_logo", filename="柯幻熊猫_LOGO.png", category=False)
    logo_payload["object_key"] = "brand/kehuanxiongmao/logo/柯幻熊猫_LOGO.png"
    logo_payload["claims"] = []
    validate_asset_against_registry(_asset(logo_payload), hub)


def test_causal_and_ordered_process_groups_validate(hub: CapabilityRegistryHub) -> None:
    reference_payload = _asset_payload("asset://A0001", asset_role="reference_image", filename="参考图.png")
    reference_payload["object_key"] = "references/文生图/文化墙/参考图.png"
    reference_payload["claims"] = []
    result_payload = _asset_payload("asset://A0002")
    result_payload["claims"] = []
    flat_payload = _asset_payload("asset://A0003", asset_role="flat_plan", filename="平面图.png")
    flat_payload["object_key"] = "flat_plans/文生图/文化墙/平面图.png"
    flat_payload["claims"] = []
    reference = _asset(reference_payload)
    result = _asset(result_payload)
    flat = _asset(flat_payload)
    assets = {reference.asset_ref: reference, result.asset_ref: result, flat.asset_ref: flat}

    causal_payload = {
        "group_ref": "group://G0001",
        "group_type": "causal",
        "pattern_id": "reference_result_plan",
        "category_id": "文生图/文化墙",
        "members": [
            {"member_key": "reference_image", "asset_role": "reference_image", "asset_ref": reference.asset_ref, "order": 1},
            {"member_key": "result_image", "asset_role": "result_image", "asset_ref": result.asset_ref, "order": 2},
            {"member_key": "flat_plan", "asset_role": "flat_plan", "asset_ref": flat.asset_ref, "order": 3},
        ],
        "status": "active",
        "superseded_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    causal = AssetGroup.model_validate_json(json.dumps(causal_payload, ensure_ascii=False))
    validate_group_against_assets(causal, assets, hub)

    process_payload = copy.deepcopy(causal_payload)
    process_payload["group_ref"] = "group://G0002"
    process_payload["group_type"] = "process"
    process_payload["pattern_id"] = "editor_sequence"
    process_payload["members"] = [
        {"member_key": "result", "asset_role": "result_image", "asset_ref": result.asset_ref, "order": 2}
    ]
    process = AssetGroup.model_validate_json(json.dumps(process_payload, ensure_ascii=False))
    with pytest.raises(DomainValidationError) as error:
        validate_group_against_assets(process, assets, hub)
    assert any(issue.code == "non_contiguous_order" for issue in error.value.issues)


def test_group_rejects_missing_mismatched_and_disallowed_members(hub: CapabilityRegistryHub) -> None:
    asset = _asset(_asset_payload())
    payload = {
        "group_ref": "group://G0003",
        "group_type": "causal",
        "pattern_id": "reference_result_plan",
        "category_id": "文生图/文化墙",
        "members": [
            {"member_key": "missing", "asset_role": "result_image", "asset_ref": "asset://A9999", "order": 1},
            {"member_key": "wrong", "asset_role": "reference_image", "asset_ref": asset.asset_ref, "order": 2},
        ],
        "status": "active",
        "superseded_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    group = AssetGroup.model_validate_json(json.dumps(payload, ensure_ascii=False))
    with pytest.raises(DomainValidationError) as error:
        validate_group_against_assets(group, {asset.asset_ref: asset}, hub)
    codes = {issue.code for issue in error.value.issues}
    assert {"missing_asset", "member_role_mismatch"} <= codes

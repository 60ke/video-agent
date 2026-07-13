from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from video_agent.assets import materialize_assets, review_materialized_assets
from video_agent.assets.site_params_batch import RequiredFieldsAnnotation, generate_site_params_keyframes
from video_agent.compiler import validate_claim_bindings
from video_agent.compiler.evidence import resolves_to_supporting_asset
from video_agent.compiler import render_plan
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    DeriveKind,
    DerivedAssetRequest,
    EvidenceClass,
    MaterializationPlan,
    Provenance,
)
from video_agent.io import sha256_file


def _png(path: Path, size: tuple[int, int] = (64, 64)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (20, 30, 40)).save(path)


def _asset(
    asset_id: str,
    path: Path,
    *,
    evidence: EvidenceClass,
    origin: str,
    parent_ids: list[str] | None = None,
    derive_kind: DeriveKind | None = None,
    width: int = 64,
    height: int = 64,
    digest: str | None = None,
) -> Asset:
    metadata = {"derive_kind": derive_kind.value} if derive_kind else {}
    return Asset(
        asset_id=asset_id,
        path=path.as_posix(),
        sha256=digest or sha256_file(path),
        filename=path.name,
        width=width,
        height=height,
        role="result_image",
        evidence_class=evidence,
        quality=AssetQuality(status="machine_checked"),
        provenance=Provenance(origin=origin, parent_asset_ids=parent_ids or []),
        metadata=metadata,
    )


def test_render_plan_uses_provenance_validator_without_monkey_patch() -> None:
    assert render_plan.validate_claim_bindings is validate_claim_bindings
    assert not hasattr(render_plan, "_validate_claim_bindings")


def test_provenance_resolution_rejects_cycles_missing_parents_and_e2(tmp_path: Path) -> None:
    path = tmp_path / "asset.png"
    _png(path)
    cycle_a = _asset(
        "asset_cycle_a",
        path,
        evidence=EvidenceClass.FAITHFUL,
        origin="deterministic_faithful_derivative",
        parent_ids=["asset_cycle_b"],
        derive_kind=DeriveKind.RESULT_DETAIL_CROP,
    )
    cycle_b = _asset(
        "asset_cycle_b",
        path,
        evidence=EvidenceClass.FAITHFUL,
        origin="deterministic_faithful_derivative",
        parent_ids=["asset_cycle_a"],
        derive_kind=DeriveKind.RESULT_VERTICAL_LAYOUT,
    )
    missing = _asset(
        "asset_missing_parent",
        path,
        evidence=EvidenceClass.FAITHFUL,
        origin="deterministic_faithful_derivative",
        parent_ids=["asset_not_present"],
        derive_kind=DeriveKind.RESULT_DETAIL_CROP,
    )
    semantic = _asset(
        "asset_semantic",
        path,
        evidence=EvidenceClass.SEMANTIC,
        origin="gpt_image_semantic_derivative",
        parent_ids=["asset_source"],
    )
    by_id = {asset.asset_id: asset for asset in (cycle_a, cycle_b, missing, semantic)}

    assert not resolves_to_supporting_asset(cycle_a.asset_id, {"asset_source"}, by_id)
    assert not resolves_to_supporting_asset(missing.asset_id, {"asset_source"}, by_id)
    assert not resolves_to_supporting_asset(semantic.asset_id, {"asset_source"}, by_id)


def test_asset_review_rejects_hash_and_dimension_mismatches(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    bad_hash_path = tmp_path / "bad_hash.png"
    bad_size_path = tmp_path / "bad_size.png"
    for path in (source_path, bad_hash_path, bad_size_path):
        _png(path)

    source = _asset(
        "asset_source",
        source_path,
        evidence=EvidenceClass.SOURCE,
        origin="curated_result_library",
    )
    bad_hash = _asset(
        "asset_bad_hash",
        bad_hash_path,
        evidence=EvidenceClass.FAITHFUL,
        origin="deterministic_faithful_derivative",
        parent_ids=[source.asset_id],
        derive_kind=DeriveKind.RESULT_DETAIL_CROP,
        digest="b" * 64,
    )
    bad_size = _asset(
        "asset_bad_size",
        bad_size_path,
        evidence=EvidenceClass.FAITHFUL,
        origin="deterministic_faithful_derivative",
        parent_ids=[source.asset_id],
        derive_kind=DeriveKind.RESULT_VERTICAL_LAYOUT,
        width=32,
        height=32,
    )
    reviewed, report = review_materialized_assets(
        tmp_path,
        AssetCatalog(catalog_id="review", generated_at="now", source_root=".", assets=[source, bad_hash, bad_size]),
    )

    assert report["counts"]["rejected"] == 2
    statuses = {asset.asset_id: asset.quality.status for asset in reviewed.assets}
    assert statuses[bad_hash.asset_id] == "rejected"
    assert statuses[bad_size.asset_id] == "rejected"


def test_materializer_rejects_site_keyframe_requests(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    _png(source_path)
    source = _asset(
        "asset_source",
        source_path,
        evidence=EvidenceClass.SOURCE,
        origin="site_screenshot_library",
    )
    catalog = AssetCatalog(catalog_id="source", generated_at="now", source_root=".", assets=[source])
    plan = MaterializationPlan(
        case_id="demo",
        requests=[
            DerivedAssetRequest(
                request_id="site_params",
                source_asset_id=source.asset_id,
                derive_kind=DeriveKind.SITE_PARAMS_KEYFRAME,
            )
        ],
    )

    with pytest.raises(ValueError, match="deterministic site batch tools"):
        materialize_assets(tmp_path, catalog, plan, tmp_path / "derived")


def test_corrupt_untracked_parameter_keyframe_is_regenerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir = tmp_path / "assets" / "sites"
    output_dir = tmp_path / "assets" / "derived"
    filename = "柯幻熊猫_文生图_美陈_参数面板截图.png"
    source = source_dir / filename
    output = output_dir / filename.replace("参数面板截图", "参数面板关键帧")
    _png(source, (320, 180))
    source_dir.joinpath("_callouts.json").write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"corrupt-image")

    annotation = RequiredFieldsAnnotation(
        labels=("行业",),
        callout_text="行业",
        frontend_source_path="frontend.vue",
        frontend_source_sha256="a" * 64,
        cdp_labels=("行业",),
        cdp_unmatched_labels=(),
    )
    monkeypatch.setattr("video_agent.assets.site_params_batch._required_fields_annotation", lambda *_: annotation)
    monkeypatch.setattr(
        "video_agent.assets.site_params_batch._field_boxes",
        lambda *_: [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}],
    )

    def fake_generate(_source: Path, target: Path, _boxes: list[dict[str, float]], _text: str) -> dict[str, str]:
        _png(target, (1080, 1920))
        return {}

    monkeypatch.setattr("video_agent.assets.site_params_batch.generate_parameter_keyframe", fake_generate)
    result = generate_site_params_keyframes(tmp_path, source_dir, output_dir, include=filename)

    assert result["generated"] == 1
    assert result["recovered"] == 0
    with Image.open(output) as image:
        assert image.size == (1080, 1920)
        image.verify()

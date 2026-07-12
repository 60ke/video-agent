from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from video_agent.assets import build_catalog, catalog_snapshot
from video_agent.assets.materializer import materialize_assets
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


def _png(path: Path, size: tuple[int, int] = (320, 180)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (20, 30, 40)).save(path)


def test_catalog_preserves_chinese_semantic_path_and_callout(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    filename = "柯幻熊猫_文生图_图文广告_车贴_参数面板截图.png"
    _png(assets / "sites" / filename)
    (assets / "sites" / "_callouts.json").write_text(
        json.dumps(
            {
                "items": {
                    filename: {
                        "callouts": [
                            {
                                "target_label": "品牌名称",
                                "target_role": "field",
                                "box": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1},
                            }
                        ]
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (assets / "results").mkdir(parents=True)
    (assets / "outro").mkdir(parents=True)

    catalog = build_catalog(assets)

    assert len(catalog.assets) == 1
    asset = catalog.assets[0]
    assert asset.semantic_path == ["文生图", "图文广告", "车贴"]
    assert asset.role == "feature_form_params"
    assert [anchor.label for anchor in asset.visual_anchors] == ["品牌名称"]
    snapshot = catalog_snapshot(catalog, ["文生图", "图文广告", "车贴"], [])
    assert [item.asset_id for item in snapshot.assets] == [asset.asset_id]


def test_catalog_restores_slash_feature_from_filesystem_safe_name(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    filename = "柯幻熊猫_文生图_图文广告_易拉宝_展架_参数面板截图.png"
    _png(assets / "sites" / filename)
    (assets / "sites" / "_callouts.json").write_text('{"items": {}}', encoding="utf-8")
    (assets / "results").mkdir(parents=True)
    (assets / "outro").mkdir(parents=True)
    catalog = build_catalog(assets)
    assert catalog.assets[0].semantic_path == ["文生图", "图文广告", "易拉宝/展架"]


def test_catalog_registers_brand_media_and_deduplicates_by_hash(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    (assets / "sites").mkdir(parents=True)
    (assets / "results").mkdir()
    (assets / "outro").mkdir()
    logo = assets / "brand" / "kehuanxiongmao" / "logo" / "柯幻熊猫_LOGO.jpg"
    static_a = assets / "brand" / "kehuanxiongmao" / "ip" / "static" / "熊猫定-01.png"
    static_b = assets / "brand" / "kehuanxiongmao" / "ip" / "static" / "熊猫定-重复.png"
    animation = assets / "brand" / "kehuanxiongmao" / "ip" / "animated" / "柯幻熊猫_跑步_透明.gif"
    _png(logo)
    _png(static_a)
    static_b.parent.mkdir(parents=True, exist_ok=True)
    static_b.write_bytes(static_a.read_bytes())
    animation.parent.mkdir(parents=True, exist_ok=True)
    frames = [Image.new("RGBA", (64, 64), color) for color in ((255, 0, 0, 0), (0, 255, 0, 255))]
    frames[0].save(animation, save_all=True, append_images=frames[1:], duration=100, loop=0, disposal=2)

    catalog = build_catalog(assets)
    roles = [asset.role for asset in catalog.assets]

    assert roles.count("brand_logo") == 1
    assert roles.count("brand_ip_static") == 1
    assert roles.count("brand_ip_animation") == 1
    assert any("duplicate brand asset skipped" in warning for warning in catalog.warnings)
    animated = next(asset for asset in catalog.assets if asset.role == "brand_ip_animation")
    assert animated.media_type == "video"
    assert animated.metadata["frame_count"] == 2
    snapshot = catalog_snapshot(catalog, ["文生图", "文化墙"], [])
    assert {asset.role for asset in snapshot.assets} == {"brand_logo", "brand_ip_static", "brand_ip_animation"}


def test_semantic_derivative_cannot_support_fact_claim() -> None:
    with pytest.raises(ValidationError, match="cannot support factual claims"):
        Asset(
            asset_id="asset_derived_abc123",
            path="derived.png",
            sha256="a" * 64,
            filename="derived.png",
            width=100,
            height=100,
            role="decorative",
            evidence_class=EvidenceClass.SEMANTIC,
            claims=["真实产品结果"],
            quality=AssetQuality(),
            provenance=Provenance(origin="gpt_image"),
        )


def _source_asset(path: str, digest: str, origin: str = "curated_result_library") -> Asset:
    return Asset(
        asset_id="asset_result_source",
        path=path,
        sha256=digest,
        filename=Path(path).name,
        width=320,
        height=180,
        semantic_path=["文生图", "VI"],
        role="result_image",
        evidence_class=EvidenceClass.SOURCE,
        claims=["真实结果"],
        quality=AssetQuality(status="machine_checked"),
        provenance=Provenance(origin=origin),
    )


def test_deterministic_derivative_preserves_claims_and_provenance(tmp_path: Path) -> None:
    source_path = tmp_path / "assets" / "results" / "源结果.png"
    _png(source_path)
    from video_agent.io import sha256_file

    source = _source_asset("assets/results/源结果.png", sha256_file(source_path))
    catalog = AssetCatalog(catalog_id="source", generated_at="now", source_root="assets", assets=[source])
    plan = MaterializationPlan(
        case_id="demo",
        requests=[
            DerivedAssetRequest(
                request_id="reframe_01",
                source_asset_id=source.asset_id,
                derive_kind=DeriveKind.CROP_AND_REFRAME,
                output_role="result_image",
            )
        ],
    )

    result = materialize_assets(tmp_path, catalog, plan, tmp_path / "run" / "derived")

    derived = result.assets[-1]
    assert derived.evidence_class == EvidenceClass.FAITHFUL
    assert derived.claims == source.claims
    assert derived.quality.status == "machine_checked"
    assert derived.provenance.parent_asset_ids == [source.asset_id]
    assert Path(derived.path).is_file()


def test_gpt_image_cannot_redraw_website_evidence(tmp_path: Path) -> None:
    source_path = tmp_path / "assets" / "sites" / "网站截图.png"
    _png(source_path)
    from video_agent.io import sha256_file

    source = _source_asset("assets/sites/网站截图.png", sha256_file(source_path), origin="site_screenshot_library")
    catalog = AssetCatalog(catalog_id="source", generated_at="now", source_root="assets", assets=[source])
    plan = MaterializationPlan(
        case_id="demo",
        requests=[
            DerivedAssetRequest(
                request_id="forbidden_01",
                source_asset_id=source.asset_id,
                derive_kind=DeriveKind.CANVAS_EXTEND,
            )
        ],
    )
    with pytest.raises(ValueError, match="cannot be redrawn"):
        materialize_assets(tmp_path, catalog, plan, tmp_path / "run" / "derived")

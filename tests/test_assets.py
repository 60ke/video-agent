from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from video_agent.assets import build_catalog, catalog_snapshot
from video_agent.ai.gpt_image import ImageEditResult
from video_agent.assets.materializer import materialize_assets
from video_agent.assets.site_params_batch import (
    RequiredFieldsAnnotation,
    _callout_text,
    _instruction,
    parse_site_params_filename,
)
from video_agent.assets.site_params_sequence import generate_parameter_frame_sequences
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


def test_site_params_filename_and_deterministic_required_field_callout() -> None:
    source = parse_site_params_filename(Path("柯幻熊猫_文生图_美陈_参数面板截图.png"))

    assert source.site == "柯幻熊猫"
    assert source.module == "文生图"
    assert source.feature_path == ("美陈",)
    assert _callout_text(("行业", "主题", "场景")) == "行业+主题+场景"
    assert _callout_text(("行业", "主题", "场景", "风格")) == "填写必填项"


def test_parameter_callout_preserves_original_stars_and_hides_validation_copy() -> None:
    source = parse_site_params_filename(Path("柯幻熊猫_文生图_美陈_参数面板截图.png"))
    annotation = RequiredFieldsAnnotation(
        labels=("行业", "主题"),
        callout_text="行业+主题",
        frontend_source_path="frontend.vue",
        frontend_source_sha256="a" * 64,
        cdp_labels=("行业", "主题"),
        cdp_unmatched_labels=(),
    )

    instruction = _instruction(source, annotation)

    assert "新增花字只能逐字写为“行业+主题”" in instruction
    assert "页面原有 UI 中已经存在的红色 * 或 ＊ 是界面内容，必须逐个原样保留" in instruction
    assert "已由 CDP DOM" not in instruction
    assert "绝不可把提示词、校验过程或来源说明渲染进图片" in instruction
    assert "优先落在面板右侧或右下区域" in instruction
    assert "花字可以覆盖普通表单内容或页面背景" in instruction
    assert "唯一禁止遮挡的是原始页面标题或分区标题" in instruction
    assert "两侧外边距各不超过 3%" in instruction
    assert "绝不可在右侧留下空白条、黑色空区或独立侧栏" in instruction


def test_parameter_batch_include_preserves_unselected_manifest_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir = tmp_path / "assets" / "sites"
    output_dir = tmp_path / "assets" / "derived"
    source_filename = "柯幻熊猫_文生图_美陈_参数面板截图.png"
    _png(source_dir / source_filename)
    (source_dir / "_callouts.json").write_text('{"items": {}}', encoding="utf-8")
    output_dir.mkdir(parents=True)
    old_output = output_dir / "未选中_参数面板关键帧.png"
    _png(old_output)
    _png(output_dir / "柯幻熊猫_文生图_美陈_参数面板关键帧.png")
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {"sequences": [{"source_path": (source_dir / "未选中_参数面板截图.png").resolve().as_posix(), "sequence_id": "old"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    annotation = RequiredFieldsAnnotation(
        labels=("行业",),
        callout_text="行业",
        frontend_source_path="frontend.vue",
        frontend_source_sha256="a" * 64,
        cdp_labels=(),
        cdp_unmatched_labels=(),
    )
    from video_agent.assets.site_params_sequence import generate_parameter_frame_sequences

    monkeypatch.setattr("video_agent.assets.site_params_sequence._required_fields_annotation", lambda *_: annotation)
    response = BytesIO()
    Image.new("RGB", (1080, 1920), (30, 40, 50)).save(response, format="PNG")
    final_response = BytesIO()
    final_image = Image.new("RGB", (1080, 1920), (30, 40, 50))
    final_image.paste((255, 220, 40), (700, 900, 940, 1040))
    final_image.save(final_response, format="PNG")
    responses = iter((response.getvalue(), final_response.getvalue()))
    monkeypatch.setattr(
        "video_agent.assets.site_params_sequence.edit_image",
        lambda *_: ImageEditResult(content=next(responses), provider="test", model="gpt-image-test", response_id="img_test"),
    )
    generate_parameter_frame_sequences(tmp_path, source_dir, output_dir, include=source_filename)

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert {Path(item["source_path"]).name for item in manifest["sequences"]} == {"未选中_参数面板截图.png", source_filename}


def test_parameter_batch_exclude_skips_locked_source(tmp_path: Path) -> None:
    source_dir = tmp_path / "assets" / "sites"
    source_filename = "柯幻熊猫_文生图_美陈_参数面板截图.png"
    _png(source_dir / source_filename)
    (source_dir / "_callouts.json").write_text('{"items": {}}', encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="no parameter-panel screenshots"):
        generate_parameter_frame_sequences(
            tmp_path,
            source_dir,
            tmp_path / "assets" / "derived",
            exclude=[source_filename],
        )


def test_parameter_sequence_manifest_approval_checks_hash_and_marks_review(tmp_path: Path) -> None:
    outputs = {state: tmp_path / f"参数面板{state}.png" for state in ("base", "stage", "final")}
    for output in outputs.values():
        _png(output)
    from video_agent.io import sha256_file

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "sequences": [{"sequence_id": "params", "frames": {state: {"path": path.as_posix(), "sha256": sha256_file(path)} for state, path in outputs.items()}}],
                "errors": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    from video_agent.assets.site_params_sequence import approve_parameter_frame_sequences

    result = approve_parameter_frame_sequences(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result == {"approved": 1}
    assert manifest["sequences"][0]["quality_status"] == "human_approved"
    assert manifest["sequences"][0]["frames"]["base"]["quality_status"] == "human_approved"


def test_approved_parameter_keyframe_replaces_raw_screenshot_in_production_pool(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    source = assets / "sites" / "柯幻熊猫_文生图_文化墙_参数面板截图.png"
    derived_dir = assets / "derived" / "sites" / "柯幻熊猫" / "文生图" / "参数面板序列" / "frames"
    _png(source)
    derived = {state: derived_dir / f"柯幻熊猫_文生图_文化墙_参数面板{label}.png" for state, label in {"base": "无花字图", "stage": "花字阶段图", "final": "花字完成图"}.items()}
    for path in derived.values():
        _png(path, (1080, 1920))
    (assets / "sites" / "_callouts.json").write_text('{"items": {}}', encoding="utf-8")
    (assets / "results").mkdir(parents=True)
    (assets / "outro").mkdir()
    from video_agent.io import sha256_file

    manifest = {
        "workflow": "site_params_flower_text_frame_sequence",
        "sequences": [
            {
                "sequence_id": "params_文化墙",
                "source_path": source.resolve().as_posix(),
                "source_sha256": sha256_file(source),
                "module": "文生图",
                "feature_path": ["文化墙"],
                "feature": "文化墙",
                "required_field_labels": ["行业"],
                "callout_text": "行业",
                "quality_status": "human_approved",
                "frames": {
                    state: {"path": path.resolve().as_posix(), "sha256": sha256_file(path), "quality_status": "human_approved", "origin": "gpt_image_edit"}
                    for state, path in derived.items()
                },
            }
        ],
    }
    (derived_dir.parent / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    catalog = build_catalog(assets)
    params = [asset for asset in catalog.assets if asset.role == "feature_form_params"]

    assert len(params) == 4
    assert next(asset for asset in params if asset.provenance.origin == "site_screenshot_library").production_eligible is False
    prepared = next(asset for asset in params if asset.metadata.get("sequence_role") == "base")
    assert prepared.production_eligible is True
    assert prepared.quality.status == "human_approved"


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


def test_catalog_registers_feature_list_screenshot(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    filename = "柯幻熊猫_AI工具_功能列表截图.png"
    _png(assets / "sites" / filename)
    (assets / "sites" / "_callouts.json").write_text('{"items": {}}', encoding="utf-8")
    (assets / "results").mkdir(parents=True)
    (assets / "outro").mkdir()

    catalog = build_catalog(assets)

    assert catalog.assets[0].semantic_path == ["AI工具"]
    assert catalog.assets[0].role == "feature_list"


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


def test_catalog_registers_external_reference_material(tmp_path: Path) -> None:
    assets = tmp_path / "assets"
    _png(assets / "references" / "柯幻熊猫_文生图_文化墙_实景图_参考图_01.png")
    (assets / "references" / "_外部导入_index.json").write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "asset_filename": "柯幻熊猫_文生图_文化墙_实景图_参考图_01.png",
                        "feature_path": ["文生图", "文化墙"],
                        "reference_label": "实景图",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (assets / "sites").mkdir()
    (assets / "results").mkdir()
    (assets / "outro").mkdir()

    catalog = build_catalog(assets)

    reference = next(asset for asset in catalog.assets if asset.role == "reference_image")
    assert reference.semantic_path == ["文生图", "文化墙"]
    assert reference.tags == ["实景图", "参考图"]


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

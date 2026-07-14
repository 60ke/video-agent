from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from video_agent.ai.gpt_image import ImageEditResult
from video_agent.assets import materialize_assets, review_materialized_assets
from video_agent.contracts import (
    Asset,
    AssetCatalog,
    AssetQuality,
    BeatSpan,
    DeriveKind,
    DerivedAssetRequest,
    EvidenceClass,
    MaterializationPlan,
    Narration,
    NarrationBeat,
    Provenance,
    TimingLock,
    TokenTiming,
)
from video_agent.io import sha256_file
from video_agent.planning import build_auto_visual_plan


def _png(path: Path, size: tuple[int, int] = (640, 480)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (80, 90, 100)).save(path)


def _asset(
    asset_id: str,
    path: Path,
    *,
    origin: str,
    evidence: EvidenceClass,
    parent_ids: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    status: str = "machine_checked",
    role: str = "result_image",
) -> Asset:
    return Asset(
        asset_id=asset_id,
        path=path.as_posix(),
        sha256=sha256_file(path),
        filename=path.name,
        width=Image.open(path).width,
        height=Image.open(path).height,
        semantic_path=["文生图", "VI"],
        role=role,
        evidence_class=evidence,
        claims=["真实结果"] if evidence != EvidenceClass.SEMANTIC else [],
        tags=["VI"],
        quality=AssetQuality(status=status),
        provenance=Provenance(origin=origin, parent_asset_ids=parent_ids or []),
        metadata=metadata or {},
    )


def _timing() -> TimingLock:
    return TimingLock(
        case_id="demo",
        audio_path="voice.wav",
        audio_sha256="a" * 64,
        fps=30,
        duration_ms=5000,
        duration_frames=150,
        tokens=[
            TokenTiming(
                token_id="tok_1",
                text="展示VI结果",
                start_ms=0,
                end_ms=5000,
                start_frame=0,
                end_frame=150,
                beat_id="beat_1",
            )
        ],
        phrase_anchors=[],
        beat_spans=[BeatSpan(beat_id="beat_1", token_ids=["tok_1"], start_frame=0, end_frame=150)],
    )


def _narration() -> Narration:
    return Narration(
        case_id="demo",
        beats=[NarrationBeat(beat_id="beat_1", spoken_text="展示VI结果", asset_slots=["VI"])],
    )


def test_auto_visual_honors_materialized_preferred_windows(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    for path in (source_path, first_path, second_path):
        _png(path)
    source = _asset(
        "asset_source",
        source_path,
        origin="curated_result_library",
        evidence=EvidenceClass.SOURCE,
    )
    first = _asset(
        "asset_first",
        first_path,
        origin="deterministic_faithful_derivative",
        evidence=EvidenceClass.FAITHFUL,
        parent_ids=[source.asset_id],
        metadata={
            "derive_kind": DeriveKind.RESULT_DETAIL_CROP.value,
            "request_id": "req_first",
            "beat_id": "beat_1",
            "preferred_start_frame": 50,
            "preferred_end_frame": 100,
        },
    )
    second = _asset(
        "asset_second",
        second_path,
        origin="deterministic_faithful_derivative",
        evidence=EvidenceClass.FAITHFUL,
        parent_ids=[source.asset_id],
        metadata={
            "derive_kind": DeriveKind.RESULT_VERTICAL_LAYOUT.value,
            "request_id": "req_second",
            "beat_id": "beat_1",
            "preferred_start_frame": 100,
            "preferred_end_frame": 150,
        },
    )
    catalog = AssetCatalog(catalog_id="catalog", generated_at="now", source_root=".", assets=[source, first, second])

    visual = build_auto_visual_plan("demo", _narration(), _timing(), catalog)

    assert [shot.asset_bindings["primary"] for shot in visual.shots] == [source.asset_id, first.asset_id, second.asset_id]
    assert visual.shots[0].start.anchor_id == "timeline_start"
    assert visual.shots[0].end.offset_frames == 50
    assert visual.shots[1].start.offset_frames == 50
    assert visual.shots[1].end.offset_frames == 100
    assert visual.shots[2].start.offset_frames == 100
    assert visual.shots[2].end.anchor_id == "timeline_end"
    assert all(shot.callout_animation is None for shot in visual.shots)


def test_auto_visual_rejects_overlapping_materialized_windows(tmp_path: Path) -> None:
    source_path = tmp_path / "source.png"
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    for path in (source_path, first_path, second_path):
        _png(path)
    source = _asset("asset_source", source_path, origin="curated_result_library", evidence=EvidenceClass.SOURCE)
    first = _asset(
        "asset_first",
        first_path,
        origin="deterministic_faithful_derivative",
        evidence=EvidenceClass.FAITHFUL,
        parent_ids=[source.asset_id],
        metadata={
            "derive_kind": DeriveKind.RESULT_DETAIL_CROP.value,
            "beat_id": "beat_1",
            "preferred_start_frame": 40,
            "preferred_end_frame": 100,
        },
    )
    second = _asset(
        "asset_second",
        second_path,
        origin="deterministic_faithful_derivative",
        evidence=EvidenceClass.FAITHFUL,
        parent_ids=[source.asset_id],
        metadata={
            "derive_kind": DeriveKind.RESULT_VERTICAL_LAYOUT.value,
            "beat_id": "beat_1",
            "preferred_start_frame": 90,
            "preferred_end_frame": 150,
        },
    )
    catalog = AssetCatalog(catalog_id="catalog", generated_at="now", source_root=".", assets=[source, first, second])

    with pytest.raises(ValueError, match="preferred windows overlap"):
        build_auto_visual_plan("demo", _narration(), _timing(), catalog)


def test_site_keyframe_materialization_uses_gpt_image_and_requires_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "site.png"
    _png(source_path, (1920, 1080))
    source = _asset(
        "asset_site_source",
        source_path,
        origin="site_screenshot_library",
        evidence=EvidenceClass.SOURCE,
        role="feature_entry",
    )
    catalog = AssetCatalog(catalog_id="catalog", generated_at="now", source_root=".", assets=[source])
    plan = MaterializationPlan(
        case_id="demo",
        requests=[
            DerivedAssetRequest(
                request_id="site_entry",
                source_asset_id=source.asset_id,
                derive_kind=DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME,
                instruction="标记会议美陈入口",
                output_role="feature_entry",
                beat_id="beat_1",
                preferred_start_frame=30,
                preferred_end_frame=90,
            )
        ],
    )
    buffer = BytesIO()
    Image.new("RGB", (1080, 1920), (30, 40, 50)).save(buffer, format="PNG")
    monkeypatch.setattr(
        "video_agent.assets.materializer.edit_image",
        lambda *_: ImageEditResult(content=buffer.getvalue(), provider="test", model="gpt-image-test", response_id="img_1"),
    )
    repo_root = Path(__file__).resolve().parents[1]

    pending = materialize_assets(repo_root, catalog, plan, tmp_path / "derived")
    derived = pending.assets[-1]

    assert derived.evidence_class == EvidenceClass.SEMANTIC
    assert derived.provenance.origin == "gpt_image_site_keyframe"
    assert derived.metadata["preferred_start_frame"] == 30
    assert derived.metadata["preferred_end_frame"] == 90
    reviewed, report = review_materialized_assets(repo_root, pending)
    assert report["counts"]["needs_review"] == 1
    assert reviewed.assets[-1].quality.status == "unreviewed"


def test_site_screenshot_cannot_use_deterministic_callout_overlay(tmp_path: Path) -> None:
    source_path = tmp_path / "site.png"
    _png(source_path)
    source = _asset(
        "asset_site_source",
        source_path,
        origin="site_screenshot_library",
        evidence=EvidenceClass.SOURCE,
        role="feature_entry",
    )
    catalog = AssetCatalog(catalog_id="catalog", generated_at="now", source_root=".", assets=[source])
    plan = MaterializationPlan(
        case_id="demo",
        requests=[
            DerivedAssetRequest(
                request_id="legacy_callout",
                source_asset_id=source.asset_id,
                derive_kind=DeriveKind.CALLOUT_OVERLAY,
            )
        ],
    )

    with pytest.raises(ValueError, match="GPT Image site keyframe recipes"):
        materialize_assets(Path(__file__).resolve().parents[1], catalog, plan, tmp_path / "derived")


def test_site_entry_batch_outputs_final_gpt_image_without_layer_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from video_agent.assets.site_entry_batch import generate_site_entry_keyframes
    from video_agent.io import load_json

    source_dir = tmp_path / "sites"
    output_dir = tmp_path / "derived"
    source = source_dir / "柯幻熊猫_文生图_会议美陈_功能入口截图.png"
    _png(source, (1920, 1080))
    buffer = BytesIO()
    Image.new("RGB", (1080, 1920), (60, 70, 80)).save(buffer, format="PNG")
    monkeypatch.setattr(
        "video_agent.assets.site_entry_batch.edit_image",
        lambda *_: ImageEditResult(content=buffer.getvalue(), provider="test", model="gpt-image-test", response_id="img_2"),
    )

    result = generate_site_entry_keyframes(Path(__file__).resolve().parents[1], source_dir, output_dir, workers=1)
    manifest = load_json(Path(result["manifest"]))
    asset = manifest["assets"][0]

    assert manifest["workflow"] == "site_feature_entry_gpt_image_batch"
    assert asset["provider"] == "test"
    assert "callout_base_path" not in asset
    assert "callout_layer_path" not in asset

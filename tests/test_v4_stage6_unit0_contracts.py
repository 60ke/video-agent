from __future__ import annotations

from pathlib import Path

from video_agent.assets.v4 import LocalObjectStore, SQLiteAssetRepository
from video_agent.assets.v4.repository import AssetDraft
from video_agent.contracts.v4 import (
    STAGE6_ERROR_CODES,
    AnchoredTimingPlan,
    CompiledVideoTimeline,
    EvidenceClass,
    RemotionEffectProps,
    SourceKind,
    SpeechTimingLock,
    Stage6Error,
)
from video_agent.io import load_json
from video_agent.registries import CapabilityRegistryHub


ROOT = Path(__file__).parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "v4" / "stage6"
REGISTRY = ROOT / "config" / "registries" / "v4"


def test_stage6_error_codes_are_stable() -> None:
    assert "anchor_phrase_ambiguous" in STAGE6_ERROR_CODES
    err = Stage6Error(code="anchor_unresolved", message="missing", scene_id="s001")
    assert err.to_dict()["error_code"] == "anchor_unresolved"


def test_unit0_mock_fixtures_validate() -> None:
    SpeechTimingLock.model_validate(load_json(FIXTURE / "speech_timing_lock.mock.json"))
    AnchoredTimingPlan.model_validate(load_json(FIXTURE / "anchored_timing_plan.mock.json"))
    CompiledVideoTimeline.model_validate(load_json(FIXTURE / "compiled_video_timeline.mock.json"))
    RemotionEffectProps.model_validate(load_json(FIXTURE / "remotion_effect_props.mock.json"))


def test_effect_registry_requires_event_timing() -> None:
    hub = CapabilityRegistryHub.load(REGISTRY)
    entry = hub.require_entry("effect", "slide_gallery")
    caps = entry.capabilities
    assert "item_transition" in caps.event_timing
    assert caps.event_timing["item_transition"].variants[0].variant_id == "full"
    assert caps.event_timing["item_transition"].variants[0].minimum_interval_frames == 36
    none_entry = hub.require_entry("effect", "none")
    assert none_entry.capabilities.event_timing == {}


def test_snapshot_freeze_includes_evidence(tmp_path: Path) -> None:
    from PIL import Image

    hub = CapabilityRegistryHub.load(REGISTRY)
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    path = tmp_path / "a.png"
    Image.new("RGB", (8, 6), "red").save(path)
    info = repo.object_store.put_file(path, "a.png")
    asset = repo.register_asset(
        AssetDraft(
            filename="a.png",
            object_key=info.object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module="文生图",
            category_id="文生图/文化墙",
            category_path=["文化墙"],
            asset_role="result_image",
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=False,
            source_kind=SourceKind.ORIGINAL,
            origin_type="test",
            evidence_class=EvidenceClass.SOURCE,
            claims=["feature_can_generate_result"],
        )
    )
    snap = repo.freeze([asset.asset_ref], [])
    assert snap.repository_schema_version == 4
    assert snap.assets[0].evidence_class == EvidenceClass.SOURCE
    assert snap.assets[0].claims == ["feature_can_generate_result"]
    repo.validate_snapshot(snap)
    repo.close()

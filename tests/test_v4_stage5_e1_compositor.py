from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from video_agent.assets.v4 import LocalObjectStore, SQLiteAssetRepository
from video_agent.assets.v4.derivation_orchestrator import prepare_derivation
from video_agent.assets.v4.repository import AssetDraft
from video_agent.contracts.v4 import EvidenceClass, SourceKind
from video_agent.contracts.v4.resolved_assets import (
    DerivationNarrativeContext,
    DerivationRequest,
    RequiredGroupSpec,
)
from video_agent.derivation.v4.capability_resolver import RegistryDerivationCapabilityResolver
from video_agent.derivation.v4.e1_compositor import (
    apply_feature_entry_callout,
    fit_to_douyin_canvas,
    render_parameter_flower_frames,
)
from video_agent.derivation.v4.executors import DeterministicDerivationExecutor
from video_agent.registries import CapabilityRegistryHub


REPO_ROOT = Path(__file__).parents[1]


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(REPO_ROOT / "config" / "registries" / "v4")


def _png(path: Path, size: tuple[int, int] = (640, 480), color: str = "white") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_fit_and_callout_and_flower_are_distinct(tmp_path: Path) -> None:
    source = _png(tmp_path / "panel.png")
    base = tmp_path / "base.png"
    stage = tmp_path / "stage.png"
    final = tmp_path / "final.png"
    callout = tmp_path / "callout.png"
    fit = tmp_path / "fit.png"
    fit_to_douyin_canvas(source, fit)
    apply_feature_entry_callout(source, callout, target_label="文化墙")
    meta = render_parameter_flower_frames(
        source,
        callout_fields=["行业", "风格"],
        output_base=base,
        output_stage=stage,
        output_final=final,
    )
    assert meta["callout_text"] == "行业+风格"
    assert fit.stat().st_size > 0
    assert callout.read_bytes() != fit.read_bytes()
    assert final.read_bytes() != base.read_bytes()
    assert stage.read_bytes() != base.read_bytes()
    with Image.open(fit) as image:
        assert image.size == (1080, 1920)


def test_deterministic_flower_sequence_registers_three_members(
    tmp_path: Path,
    hub: CapabilityRegistryHub,
) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    source = _png(tmp_path / "params.png", size=(900, 1400), color="#f5f5f5")
    info = repo.object_store.put_file(source, "original/params.png")
    parent = repo.register_asset(
        AssetDraft(
            filename="params.png",
            object_key=info.object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module="文生图",
            category_id="文生图/文化墙",
            category_path=["文化墙"],
            asset_role="parameter_panel",
            description='{"registered_required_fields": ["行业", "风格"]}',
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=False,
            source_kind=SourceKind.ORIGINAL,
            origin_type="test",
            evidence_class=EvidenceClass.SOURCE,
            claims=[],
        )
    )
    session = repo.open_resolution_session()
    request = DerivationRequest(
        request_id="derivation://R0200",
        scene_id="s004",
        slot_id="p_base",
        derivation_type="site_params_flower_text_frame_sequence",
        category_id="文生图/文化墙",
        target_asset_role="parameter_panel",
        required_group=RequiredGroupSpec(
            group_type="process",
            pattern_id="parameter_callout_sequence",
            member_key="base",
        ),
        parent_asset_refs=[parent.asset_ref],
        evidence_ceiling="E1_faithful_derivative",
        narrative_context=DerivationNarrativeContext(
            scene_text="填上行业和风格，点击生成，",
            anchor_phrase="填上",
            spoken_operation_fields=["行业", "风格"],
            registered_required_fields=["行业", "风格"],
            callout_fields=["行业", "风格"],
        ),
    )
    binding = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT).resolve(request)
    prepared = prepare_derivation(request, binding, session)
    result = DeterministicDerivationExecutor(REPO_ROOT, hub).execute(request, binding, prepared, session)
    assert set(result.draft_member_keys) == {"base", "stage", "final"}
    assert len(result.drafts) == 3
    assert all(draft.evidence_class == EvidenceClass.FAITHFUL for draft in result.drafts)
    assert all(draft.lineage and draft.lineage.model == "e1_compositor_v1" for draft in result.drafts)
    hashes = {draft.content_sha256 for draft in result.drafts}
    assert len(hashes) == 3
    repo.close()


def test_v4_motion_and_stage_modules_do_not_import_v3_effects() -> None:
    import video_agent.motion.v4.assignment as assignment
    import video_agent.motion.v4.planner as planner
    import video_agent.v4.stage5 as stage5

    for module in (assignment, planner, stage5):
        assert "video_agent.effects" not in module.__dict__
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "video_agent.effects" not in source
        assert "from video_agent.effects" not in source
        assert "import EFFECTS" not in source

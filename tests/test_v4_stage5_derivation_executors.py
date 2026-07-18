from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from video_agent.ai.gpt_image import ImageEditResult
from video_agent.assets.v4 import LocalObjectStore, SQLiteAssetRepository
from video_agent.assets.v4.derivation_orchestrator import prepare_derivation
from video_agent.assets.v4.repository import AssetDraft
from video_agent.contracts.v4 import EvidenceClass, SourceKind
from video_agent.contracts.v4.resolved_assets import DerivationNarrativeContext, DerivationRequest
from video_agent.derivation.v4.capability_resolver import RegistryDerivationCapabilityResolver
from video_agent.derivation.v4.executors import (
    DeterministicDerivationExecutor,
    GptImageDerivationExecutor,
    Stage5DerivationExecutor,
)
from video_agent.derivation.v4.prompt_composer import compose_derivation_prompt
from video_agent.registries import CapabilityRegistryHub


REPO_ROOT = Path(__file__).parents[1]
REGISTRY_ROOT = REPO_ROOT / "config" / "registries" / "v4"


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(REGISTRY_ROOT)


@pytest.fixture
def repo(tmp_path: Path, hub: CapabilityRegistryHub) -> SQLiteAssetRepository:
    result = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    yield result
    result.close()


def _png(path: Path, color: str = "red", size: tuple[int, int] = (32, 24)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def _register_parent(repo: SQLiteAssetRepository, source: Path, role: str = "result_image") -> str:
    info = repo.object_store.put_file(source, f"original/{source.name}")
    asset = repo.register_asset(
        AssetDraft(
            filename=source.name,
            object_key=info.object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module="文生图",
            category_id="文生图/文化墙",
            category_path=["文化墙"],
            asset_role=role,
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
    return asset.asset_ref


def test_compose_prompt_loads_capability_template(hub: CapabilityRegistryHub) -> None:
    resolver = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT)
    request = DerivationRequest(
        request_id="derivation://R0001",
        scene_id="s007",
        slot_id="reference",
        derivation_type="result_to_reference_mock",
        category_id="文生图/文化墙",
        target_asset_role="reference_image",
        parent_asset_refs=["asset://A0001"],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="参考图", anchor_phrase="参考图"),
        target_orientation="landscape",
    )
    binding = resolver.resolve(request)
    composed = compose_derivation_prompt(
        repo_root=REPO_ROOT,
        hub=hub,
        request=request,
        binding=binding,
        parent_roles=["result_image"],
    )
    assert "reference_image" in composed.text
    assert composed.template_sha256 == binding.prompt_template_sha256
    assert (REPO_ROOT / "video_agent/prompts/v4/derivation/result_to_reference_mock/system.v1.md").is_file()


def test_deterministic_normalize_gallery(repo: SQLiteAssetRepository, hub: CapabilityRegistryHub, tmp_path: Path) -> None:
    parent_ref = _register_parent(repo, _png(tmp_path / "parent.png", size=(40, 20)), "result_image")
    session = repo.open_resolution_session()
    request = DerivationRequest(
        request_id="derivation://R0010",
        scene_id="s002",
        slot_id="g1",
        derivation_type="normalize_gallery_asset",
        category_id="文生图/文化墙",
        target_asset_role="result_image",
        parent_asset_refs=[parent_ref],
        evidence_ceiling="E1_faithful_derivative",
        target_orientation="portrait",
    )
    binding = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT).resolve(request)
    prepared = prepare_derivation(request, binding, session)
    result = DeterministicDerivationExecutor(REPO_ROOT, hub).execute(request, binding, prepared, session)
    assert len(result.drafts) == 1
    assert result.drafts[0].lineage is not None
    assert result.drafts[0].lineage.provider == "deterministic"
    assert result.drafts[0].evidence_class == EvidenceClass.FAITHFUL


def test_gpt_image_executor_uses_injected_editor(
    repo: SQLiteAssetRepository, hub: CapabilityRegistryHub, tmp_path: Path
) -> None:
    parent_ref = _register_parent(repo, _png(tmp_path / "result.png", "blue", (48, 32)))
    session = repo.open_resolution_session()
    request = DerivationRequest(
        request_id="derivation://R0020",
        scene_id="s007",
        slot_id="reference",
        derivation_type="result_to_reference_mock",
        category_id="文生图/文化墙",
        target_asset_role="reference_image",
        parent_asset_refs=[parent_ref],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="参考", anchor_phrase="参考"),
        target_orientation="landscape",
    )
    binding = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT).resolve(request)
    prepared = prepare_derivation(request, binding, session)

    def fake_edit(repo_root: Path, source: Path, prompt: str, *, size: str | None = None) -> ImageEditResult:
        assert "reference" in prompt.lower() or "Reference" in prompt or "reference_image" in prompt
        out = tmp_path / "edited.png"
        Image.new("RGB", (16, 9), "green").save(out)
        return ImageEditResult(content=out.read_bytes(), provider="mock", model="gpt-image-2", response_id="r1")

    result = GptImageDerivationExecutor(REPO_ROOT, hub, image_editor=fake_edit).execute(
        request, binding, prepared, session
    )
    assert result.drafts[0].asset_role == "reference_image"
    assert result.drafts[0].lineage is not None
    assert result.drafts[0].lineage.provider == "mock"
    assert result.drafts[0].evidence_class == EvidenceClass.SEMANTIC


def test_stage5_dispatcher_routes_deterministic(hub: CapabilityRegistryHub, repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    parent_ref = _register_parent(repo, _png(tmp_path / "site.png"), "site_home")
    session = repo.open_resolution_session()
    request = DerivationRequest(
        request_id="derivation://R0030",
        scene_id="s001",
        slot_id="home",
        derivation_type="site_faithful_reframe",
        target_asset_role="site_home",
        parent_asset_refs=[parent_ref],
        evidence_ceiling="E1_faithful_derivative",
        target_orientation="portrait",
    )
    binding = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT).resolve(request)
    prepared = prepare_derivation(request, binding, session)
    result = Stage5DerivationExecutor(REPO_ROOT, hub, image_editor=lambda *a, **k: None).execute(
        request, binding, prepared, session
    )
    assert result.drafts[0].lineage.provider == "deterministic"

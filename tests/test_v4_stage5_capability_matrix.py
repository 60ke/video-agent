"""Stage 0 s001-s010 Stage5 capability binding / fail-loud / derive matrix."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from video_agent.ai.gpt_image import ImageEditResult
from video_agent.assets.v4 import LocalObjectStore, SQLiteAssetRepository
from video_agent.assets.v4.derivation_orchestrator import (
    fulfill_derivation,
    member_derivation_signature,
    prepare_derivation,
)
from video_agent.assets.v4.repository import AssetDraft
from video_agent.assets.v4.stage4_errors import Stage4Error
from video_agent.contracts.v4 import EvidenceClass, RelationPatternEntry, SourceKind
from video_agent.contracts.v4.resolved_assets import (
    DerivationNarrativeContext,
    DerivationRequest,
    RequiredGroupSpec,
)
from video_agent.derivation.v4.capability_resolver import RegistryDerivationCapabilityResolver
from video_agent.derivation.v4.executors import Stage5DerivationExecutor
from video_agent.derivation.v4.handler_fingerprint import handler_source_fingerprint
from video_agent.registries import CapabilityRegistryHub


REPO_ROOT = Path(__file__).parents[1]
REGISTRY_ROOT = REPO_ROOT / "config" / "registries" / "v4"

# Scene → derivation capabilities that must bind (or explicit no-derivation).
SCENE_CAPABILITY_MATRIX: dict[str, list[tuple[str, str, str | None]]] = {
    "s001": [("site_faithful_reframe", "site_home", None)],
    "s002": [("normalize_gallery_asset", "result_image", None)],
    "s003": [("site_feature_entry_callout_keyframe", "feature_entry", None)],
    "s004": [
        (
            "site_params_flower_text_frame_sequence",
            "parameter_panel",
            "parameter_callout_sequence",
        )
    ],
    "s005": [],  # primary result via asset_query; no required derivation
    "s006": [("result_to_editor_process", "editor_page", "editor_sequence")],
    "s007": [("result_to_reference_mock", "reference_image", "reference_result_plan")],
    "s008": [("result_to_flat_plan", "flat_plan", "reference_result_plan")],
    "s009": [],  # no_asset — motion only, no derivation
    "s010": [],  # configured_asset default_outro — no derivation
}

GROUP_MEMBER_EXPECTATIONS = {
    "parameter_callout_sequence": ["base", "stage", "final"],
    "editor_sequence": ["source_result", "editor_page", "edited_result"],
    "reference_result_plan": ["reference_image", "result_image", "flat_plan"],
}


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


def _register(
    repo: SQLiteAssetRepository,
    source: Path,
    *,
    role: str,
    category_id: str | None = "文生图/文化墙",
) -> str:
    info = repo.object_store.put_file(source, f"original/{source.name}")
    asset = repo.register_asset(
        AssetDraft(
            filename=source.name,
            object_key=info.object_key,
            content_sha256=info.content_sha256,
            media_type=info.media_type,
            module=category_id.split("/", 1)[0] if category_id and "/" in category_id else None,
            category_id=category_id,
            category_path=[category_id.split("/", 1)[1]] if category_id and "/" in category_id else [],
            asset_role=role,
            width=info.width,
            height=info.height,
            orientation=info.orientation,
            animated=False,
            source_kind=SourceKind.ORIGINAL,
            origin_type="matrix",
            evidence_class=EvidenceClass.SOURCE,
            claims=["feature_can_generate_result"] if role == "result_image" else [],
        )
    )
    return asset.asset_ref


def _fake_editor(tmp_path: Path):
    def edit(repo_root: Path, source: Path, prompt: str, *, size: str | None = None) -> ImageEditResult:
        out = tmp_path / f"edited_{abs(hash(prompt)) % 10_000}.png"
        Image.new("RGB", (16, 9), "green").save(out)
        return ImageEditResult(
            content=out.read_bytes(),
            provider="mock",
            model="gpt-image-2",
            response_id="matrix",
        )

    return edit


def _group_spec(pattern_id: str, member_key: str) -> RequiredGroupSpec:
    group_type = "causal" if pattern_id == "reference_result_plan" else "process"
    return RequiredGroupSpec(group_type=group_type, pattern_id=pattern_id, member_key=member_key)


def test_stage0_s001_to_s010_capability_bindings(hub: CapabilityRegistryHub) -> None:
    resolver = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT)
    assert set(SCENE_CAPABILITY_MATRIX) == {f"s{index:03d}" for index in range(1, 11)}
    for scene_id, rows in SCENE_CAPABILITY_MATRIX.items():
        for derivation_type, role, pattern_id in rows:
            member_key = None
            if pattern_id == "editor_sequence":
                member_key = "editor_page"
            elif pattern_id == "parameter_callout_sequence":
                member_key = "base"
            elif pattern_id == "reference_result_plan":
                member_key = (
                    "reference_image" if derivation_type == "result_to_reference_mock" else "flat_plan"
                )
            request = DerivationRequest(
                request_id=f"derivation://{scene_id}-{derivation_type}",
                scene_id=scene_id,
                slot_id="slot",
                derivation_type=derivation_type,
                category_id="文生图/文化墙" if role != "site_home" else "网站/主页",
                target_asset_role=role,
                parent_asset_refs=["asset://A0001"],
                required_group=_group_spec(pattern_id, member_key) if pattern_id and member_key else None,
                evidence_ceiling="E2_semantic_derivative",
                target_orientation="portrait",
            )
            binding = resolver.resolve(request)
            assert binding.capability_id == derivation_type
            assert len(binding.execution_fingerprint) == 64


def test_relation_patterns_have_complete_required_members(hub: CapabilityRegistryHub) -> None:
    for pattern_id, expected_keys in GROUP_MEMBER_EXPECTATIONS.items():
        entry = hub.entry("relation_pattern", pattern_id)
        assert isinstance(entry, RelationPatternEntry)
        keys = [member.member_key for member in sorted(entry.members, key=lambda item: item.order)]
        assert keys == expected_keys
        assert all(member.required for member in entry.members if member.member_key in expected_keys)


def test_website_truth_fail_loud_for_gpt_on_site_roles(
    hub: CapabilityRegistryHub, repo: SQLiteAssetRepository, tmp_path: Path
) -> None:
    from video_agent.derivation.v4.executors import GptImageDerivationExecutor

    parent = _register(repo, _png(tmp_path / "result.png", "blue"), role="result_image")
    session = repo.open_resolution_session()
    resolver = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT)
    legal = DerivationRequest(
        request_id="derivation://truth-legal",
        scene_id="s007",
        slot_id="reference",
        derivation_type="result_to_reference_mock",
        category_id="文生图/文化墙",
        target_asset_role="reference_image",
        parent_asset_refs=[parent],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="参考", anchor_phrase="参考"),
        target_orientation="landscape",
    )
    binding = resolver.resolve(legal)
    prepared = prepare_derivation(legal, binding, session)
    forged = legal.model_copy(update={"target_asset_role": "site_home", "scene_id": "s001", "slot_id": "home"})
    with pytest.raises(Stage4Error) as exc:
        GptImageDerivationExecutor(REPO_ROOT, hub, image_editor=_fake_editor(tmp_path)).execute(
            forged, binding, prepared, session
        )
    assert exc.value.code == "website_truth_violation"


def test_faithful_site_derivation_requires_parent(
    hub: CapabilityRegistryHub, repo: SQLiteAssetRepository
) -> None:
    request = DerivationRequest(
        request_id="derivation://no-parent",
        scene_id="s001",
        slot_id="home",
        derivation_type="site_faithful_reframe",
        category_id="网站/主页",
        target_asset_role="site_home",
        parent_asset_refs=[],
        evidence_ceiling="E1_faithful_derivative",
        target_orientation="portrait",
    )
    with pytest.raises(Stage4Error) as exc:
        RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT).resolve(request)
    assert exc.value.code == "capability_not_applicable"


def test_default_outro_configured_asset_binding(hub: CapabilityRegistryHub, repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    outro_ref = _register(repo, _png(tmp_path / "outro.png", "black"), role="outro", category_id=None)
    repo.bind_configured_asset("default_outro", outro_ref)
    bound = repo.configured_asset("default_outro")
    assert bound is not None
    assert bound.asset_ref == outro_ref
    assert bound.asset_role == "outro"
    assert hub.entry("configured_asset", "default_outro") is not None


def test_group_member_signature_changes_with_callout_fields(
    hub: CapabilityRegistryHub, repo: SQLiteAssetRepository, tmp_path: Path
) -> None:
    parent = _register(repo, _png(tmp_path / "params.png"), role="parameter_panel", category_id="文生图/文化墙")
    session = repo.open_resolution_session()
    resolver = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT)
    base_kwargs = dict(
        request_id="derivation://sig",
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
        parent_asset_refs=[parent],
        evidence_ceiling="E1_faithful_derivative",
        target_orientation="portrait",
    )
    first = DerivationRequest(
        **base_kwargs,
        narrative_context=DerivationNarrativeContext(
            scene_text="填上行业和风格",
            anchor_phrase="填上",
            callout_fields=["行业", "风格"],
        ),
    )
    second = DerivationRequest(
        **base_kwargs,
        narrative_context=DerivationNarrativeContext(
            scene_text="填上行业和风格",
            anchor_phrase="填上",
            callout_fields=["尺寸"],
        ),
    )
    prepared_a = prepare_derivation(first, resolver.resolve(first), session)
    prepared_b = prepare_derivation(second, resolver.resolve(second), session)
    assert prepared_a.prompt_input_sha256 != prepared_b.prompt_input_sha256
    assert prepared_a.derivation_signature != prepared_b.derivation_signature
    sig_a = member_derivation_signature(prepared_a, member_key="stage", member_role="parameter_panel")
    sig_b = member_derivation_signature(prepared_b, member_key="stage", member_role="parameter_panel")
    assert sig_a != sig_b


def test_s004_s006_s007_s008_real_derive_and_register(
    hub: CapabilityRegistryHub, repo: SQLiteAssetRepository, tmp_path: Path
) -> None:
    resolver = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT)
    executor = Stage5DerivationExecutor(REPO_ROOT, hub, image_editor=_fake_editor(tmp_path))
    params_parent = _register(repo, _png(tmp_path / "panel.png"), role="parameter_panel")
    result_parent = _register(repo, _png(tmp_path / "result.png", "blue"), role="result_image")
    session = repo.open_resolution_session()

    flower_req = DerivationRequest(
        request_id="derivation://s004",
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
        parent_asset_refs=[params_parent],
        evidence_ceiling="E1_faithful_derivative",
        narrative_context=DerivationNarrativeContext(
            scene_text="填上行业和风格",
            anchor_phrase="填上",
            callout_fields=["行业", "风格"],
        ),
        target_orientation="portrait",
    )
    status, _, flower_group = fulfill_derivation(
        flower_req,
        session=session,
        resolver=resolver,
        executor=executor,
        allow_fake=False,
        requires_stage5=True,
        registry=hub,
    )
    assert status.status == "registered"
    assert flower_group is not None
    assert {m.member_key for m in flower_group.members} == {"base", "stage", "final"}

    editor_req = DerivationRequest(
        request_id="derivation://s006",
        scene_id="s006",
        slot_id="editor",
        derivation_type="result_to_editor_process",
        category_id="文生图/文化墙",
        target_asset_role="editor_page",
        required_group=RequiredGroupSpec(
            group_type="process",
            pattern_id="editor_sequence",
            member_key="editor_page",
        ),
        parent_asset_refs=[result_parent],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="继续编辑", anchor_phrase="继续编辑"),
        target_orientation="portrait",
    )
    status6, _, editor_group = fulfill_derivation(
        editor_req,
        session=session,
        resolver=resolver,
        executor=executor,
        allow_fake=False,
        requires_stage5=True,
        registry=hub,
    )
    assert status6.status == "registered"
    assert editor_group is not None
    assert {m.member_key for m in editor_group.members} == {
        "source_result",
        "editor_page",
        "edited_result",
    }

    causal_req = DerivationRequest(
        request_id="derivation://s007",
        scene_id="s007",
        slot_id="reference",
        derivation_type="result_to_reference_mock",
        category_id="文生图/文化墙",
        target_asset_role="reference_image",
        required_group=RequiredGroupSpec(
            group_type="causal",
            pattern_id="reference_result_plan",
            member_key="reference_image",
        ),
        parent_asset_refs=[result_parent],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="参考图", anchor_phrase="参考图"),
        target_orientation="landscape",
    )
    status7, _, causal_group = fulfill_derivation(
        causal_req,
        session=session,
        resolver=resolver,
        executor=executor,
        allow_fake=False,
        requires_stage5=True,
        registry=hub,
    )
    assert status7.status == "registered"
    assert causal_group is not None
    assert {m.member_key for m in causal_group.members} == {
        "reference_image",
        "result_image",
        "flat_plan",
    }

    # s008 reuses the same causal group (group_reuse) rather than re-deriving.
    flat_req = DerivationRequest(
        request_id="derivation://s008",
        scene_id="s008",
        slot_id="plan",
        derivation_type="result_to_flat_plan",
        category_id="文生图/文化墙",
        target_asset_role="flat_plan",
        required_group=RequiredGroupSpec(
            group_type="causal",
            pattern_id="reference_result_plan",
            member_key="flat_plan",
        ),
        parent_asset_refs=[result_parent],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="平面图", anchor_phrase="平面图"),
        target_orientation="landscape",
    )
    status8, _, reused = fulfill_derivation(
        flat_req,
        session=session,
        resolver=resolver,
        executor=executor,
        allow_fake=False,
        requires_stage5=True,
        registry=hub,
    )
    assert status8.status == "group_reuse"
    assert reused is not None
    assert reused.group_ref == causal_group.group_ref


def test_handler_source_fingerprint_stable_and_nonempty(hub: CapabilityRegistryHub) -> None:
    entry = hub.require_entry("derivation", "site_faithful_reframe")
    first = handler_source_fingerprint(entry.handler)
    second = handler_source_fingerprint(entry.handler)
    assert first == second
    assert len(first) == 64
    assert first != handler_source_fingerprint(None)


def test_execution_fingerprint_changes_with_handler_source(
    hub: CapabilityRegistryHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = RegistryDerivationCapabilityResolver(hub, repo_root=REPO_ROOT)
    request = DerivationRequest(
        request_id="derivation://fp",
        scene_id="s001",
        slot_id="home",
        derivation_type="site_faithful_reframe",
        category_id="网站/主页",
        target_asset_role="site_home",
        parent_asset_refs=["asset://A0001"],
        evidence_ceiling="E1_faithful_derivative",
        target_orientation="portrait",
    )
    monkeypatch.setattr(
        "video_agent.derivation.v4.capability_resolver.handler_source_fingerprint",
        lambda _ref: "a" * 64,
    )
    fp_a = resolver.resolve(request).execution_fingerprint
    monkeypatch.setattr(
        "video_agent.derivation.v4.capability_resolver.handler_source_fingerprint",
        lambda _ref: "b" * 64,
    )
    fp_b = resolver.resolve(request).execution_fingerprint
    assert fp_a != fp_b

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from video_agent.assets.v4 import (
    AssetDraft,
    AssetGroupDraft,
    AssetPlanResolver,
    LocalObjectStore,
    SQLiteAssetRepository,
)
from video_agent.assets.v4.derivation_orchestrator import (
    DerivationCapabilityBinding,
    FakeDerivationExecutor,
    PreparedDerivation,
    fulfill_derivation,
)
from video_agent.assets.v4.gap_policy import load_selection_config
from video_agent.assets.v4.parameter_fields import (
    extract_spoken_operation_fields,
    parameter_narrative_fields,
    resolve_callout_fields,
)
from video_agent.assets.v4.repository import AssetQuery, AssetResolutionSession, GroupQuery
from video_agent.assets.v4.selector import select_asset
from video_agent.assets.v4.stage4_errors import Stage4Error
from video_agent.contracts.v4 import (
    AssetGroupMember,
    AssetLineage,
    AssetQuerySource,
    EvidenceClass,
    MaterialSlot,
    RelationFromInputSource,
    SceneInput,
    SceneOutput,
    SceneSemanticPlan,
    SemanticScene,
    SourceKind,
)
from video_agent.contracts.v4.resolved_assets import (
    DerivationNarrativeContext,
    DerivationRequest,
    RequiredGroupSpec,
    Stage4SelectionConfig,
)
from video_agent.registries import CapabilityRegistryHub


def _image(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 3), color).save(path)
    return path


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(Path(__file__).parents[1] / "config" / "registries" / "v4")


@pytest.fixture
def selection_config() -> Stage4SelectionConfig:
    return load_selection_config(Path(__file__).parents[1] / "config" / "stage4_selection.v4.json")


def _draft(
    repo: SQLiteAssetRepository,
    source: Path,
    key: str,
    role: str = "result_image",
    *,
    category: str = "文生图/文化墙",
    claims: list[str] | None = None,
    evidence: EvidenceClass = EvidenceClass.SOURCE,
    description: str | None = None,
    lineage: AssetLineage | None = None,
) -> AssetDraft:
    info = repo.object_store.put_file(source, key)
    if "/" in category:
        module, rest = category.split("/", 1)
        category_path = [rest]
    else:
        module, category_path = category, [category]
    return AssetDraft(
        filename=Path(key).name,
        object_key=key,
        content_sha256=info.content_sha256,
        media_type=info.media_type,
        module=module,
        category_id=category,
        category_path=category_path,
        asset_role=role,
        description=description,
        width=info.width,
        height=info.height,
        orientation=info.orientation,
        animated=False,
        source_kind=SourceKind.DERIVED if lineage else SourceKind.ORIGINAL,
        origin_type="test",
        evidence_class=evidence,
        claims=claims or [],
        lineage=lineage,
    )


@dataclass
class CountingExecutor:
    inner: FakeDerivationExecutor = field(default_factory=FakeDerivationExecutor)
    calls: int = 0

    def execute(
        self,
        request: DerivationRequest,
        binding: DerivationCapabilityBinding,
        prepared: PreparedDerivation,
        session: AssetResolutionSession,
    ):
        self.calls += 1
        return self.inner.execute(request, binding, prepared, session)


class _FakeBindingResolver:
    def resolve(self, request: DerivationRequest) -> DerivationCapabilityBinding:
        return DerivationCapabilityBinding(
            capability_id="fake.capability",
            capability_version="1",
            execution_fingerprint="f" * 64,
            is_fake=True,
        )


def test_parameter_callout_field_intersection() -> None:
    spoken = extract_spoken_operation_fields("填上行业和风格，点击生成")
    assert spoken == ["行业", "风格"]
    assert resolve_callout_fields(
        spoken_operation_fields=spoken,
        registered_required_fields=["行业", "风格", "尺寸"],
    ) == ["行业", "风格"]
    assert resolve_callout_fields(
        spoken_operation_fields=spoken,
        registered_required_fields=[],
    ) == []


def test_parameter_narrative_from_parent_description(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    parent = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "p.png"),
            "p.png",
            role="parameter_panel",
            description='{"registered_required_fields": ["行业", "风格", "尺寸"]}',
        )
    )
    scene = SemanticScene(
        scene_id="s004",
        order=1,
        text="填上行业和风格，点击生成，",
        visual_structure="sequence",
        slots=[
            MaterialSlot(
                slot_id="p_base",
                anchor_phrase="填上",
                entry_policy="scene_start",
                hold_policy="scene_end",
                category_id="文生图/文化墙",
                asset_role="parameter_panel",
                source=AssetQuerySource(kind="asset_query"),
                subtitle_emphasis="none",
            )
        ],
        events=[],
        inputs=[],
        outputs=[],
        claims=[],
        no_asset=False,
    )
    spoken, registered, callouts = parameter_narrative_fields(scene, parent)
    assert spoken == ["行业", "风格"]
    assert registered == ["行业", "风格", "尺寸"]
    assert callouts == ["行业", "风格"]
    repo.close()


def test_signature_hit_skips_executor(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    parent = repo.register_asset(
        _draft(repo, _image(tmp_path / "p.png"), "p.png", claims=["feature_can_generate_result"])
    )
    session = repo.open_resolution_session()
    request = DerivationRequest(
        request_id="derivation://R0001",
        scene_id="s005",
        slot_id="result",
        derivation_type="text_to_result",
        category_id="文生图/文化墙",
        target_asset_role="result_image",
        parent_asset_refs=[parent.asset_ref],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="结果", anchor_phrase="结果"),
    )
    resolver = _FakeBindingResolver()
    counter = CountingExecutor()
    first, _, _ = fulfill_derivation(
        request.model_copy(deep=True),
        session=session,
        resolver=resolver,
        executor=counter,
        allow_fake=True,
        requires_stage5=False,
        registry=hub,
    )
    assert first.status == "registered"
    assert counter.calls == 1

    second_request = request.model_copy(deep=True)
    second, prepared, _ = fulfill_derivation(
        second_request,
        session=session,
        resolver=resolver,
        executor=counter,
        allow_fake=True,
        requires_stage5=False,
        registry=hub,
    )
    assert second.status == "signature_hit"
    assert counter.calls == 1
    assert session.find_by_derivation_signature(prepared.derivation_signature) is not None
    repo.close()


def test_group_reuse_distinct_from_signature_hit(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    primary = repo.register_asset(
        _draft(repo, _image(tmp_path / "p.png"), "p.png", claims=["feature_can_generate_result"])
    )
    editor = repo.register_asset(
        _draft(repo, _image(tmp_path / "e.png", "blue"), "e.png", role="editor_page")
    )
    edited = repo.register_asset(
        _draft(repo, _image(tmp_path / "ed.png", "green"), "ed.png", role="edited_result")
    )
    group = repo.register_group(
        AssetGroupDraft(
            group_type="process",
            pattern_id="editor_sequence",
            category_id="文生图/文化墙",
            members=[
                AssetGroupMember(member_key="source_result", asset_role="result_image", asset_ref=primary.asset_ref, order=1),
                AssetGroupMember(member_key="editor_page", asset_role="editor_page", asset_ref=editor.asset_ref, order=2),
                AssetGroupMember(member_key="edited_result", asset_role="edited_result", asset_ref=edited.asset_ref, order=3),
            ],
        )
    )
    session = repo.open_resolution_session()
    request = DerivationRequest(
        request_id="derivation://R0002",
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
        parent_asset_refs=[primary.asset_ref],
        evidence_ceiling="E2_semantic_derivative",
        narrative_context=DerivationNarrativeContext(scene_text="编辑", anchor_phrase="编辑"),
    )
    counter = CountingExecutor()
    status_request, _, reused = fulfill_derivation(
        request,
        session=session,
        resolver=_FakeBindingResolver(),
        executor=counter,
        allow_fake=True,
        requires_stage5=False,
        registry=hub,
    )
    assert status_request.status == "group_reuse"
    assert reused is not None and reused.group_ref == group.group_ref
    assert counter.calls == 0
    repo.close()


def test_atomic_derived_group_rolls_back(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    parent = repo.register_asset(
        _draft(repo, _image(tmp_path / "p.png"), "p.png", claims=["feature_can_generate_result"])
    )
    good = _draft(repo, _image(tmp_path / "a.png", "blue"), "a.png", role="editor_page")
    bad = _draft(
        repo,
        _image(tmp_path / "b.png", "green"),
        "b.png",
        role="edited_result",
        lineage=AssetLineage(
            parent_asset_refs=["asset://A9999"],
            derivation_type="result_to_editor_process",
            executor_id="fake",
            provider="fake",
            model="fixture",
            prompt_template_version="1",
            prompt_sha256="a" * 64,
            parameters_sha256="b" * 64,
            derivation_signature="c" * 64,
            created_at=datetime.now(timezone.utc),
        ),
    )
    before_assets = len(repo.query_assets(AssetQuery()))
    before_groups = len(repo.query_groups(GroupQuery()))
    with pytest.raises(Exception):
        repo.register_derived_group(
            drafts=[good, bad],
            draft_member_keys=["editor_page", "edited_result"],
            reuse_member_refs={"source_result": parent.asset_ref},
            group_type="process",
            pattern_id="editor_sequence",
            category_id="文生图/文化墙",
            member_specs=[
                ("source_result", "result_image", 1),
                ("editor_page", "editor_page", 2),
                ("edited_result", "edited_result", 3),
            ],
        )
    after_assets = len(repo.query_assets(AssetQuery()))
    after_groups = len(repo.query_groups(GroupQuery()))
    assert after_assets == before_assets
    assert after_groups == before_groups
    repo.close()


def test_e2_semantic_cannot_satisfy_website_claim(
    tmp_path: Path,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    seed = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "seed.png"),
            "seed.png",
            role="result_image",
            claims=["feature_can_generate_result"],
        )
    )
    # E2 cannot carry factual claims at registration; Stage4 must still reject it
    # for website roles via evidence post-filter (not as a real website source).
    repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "fake_home.png"),
            "fake_home.png",
            role="site_home",
            category="网站/主页",
            claims=[],
            evidence=EvidenceClass.SEMANTIC,
            lineage=AssetLineage(
                parent_asset_refs=[seed.asset_ref],
                derivation_type="site_faithful_reframe",
                executor_id="fake",
                provider="fake",
                model="fixture",
                prompt_template_version="1",
                prompt_sha256="a" * 64,
                parameters_sha256="b" * 64,
                derivation_signature="d" * 64,
                created_at=datetime.now(timezone.utc),
            ),
        )
    )
    plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="首页",
                visual_structure="single",
                slots=[
                    MaterialSlot(
                        slot_id="home",
                        anchor_phrase="首页",
                        entry_policy="scene_start",
                        hold_policy="scene_end",
                        category_id="网站/主页",
                        asset_role="site_home",
                        source=AssetQuerySource(kind="asset_query"),
                        subtitle_emphasis="none",
                    )
                ],
                events=[],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=False,
            )
        ]
    )
    with pytest.raises(Stage4Error) as exc:
        AssetPlanResolver(hub).resolve(
            plan,
            session=repo.open_resolution_session(),
            selection_config=selection_config,
            run_seed="e2",
            registry_snapshot_id="registry://e2",
            scene_plan_sha256="e" * 64,
            allow_fake_derivation=False,
        )
    assert exc.value.code == "missing_source_asset"
    repo.close()


def test_semantic_ranker_enabled_fails_loud(selection_config: Stage4SelectionConfig, tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    a = repo.register_asset(_draft(repo, _image(tmp_path / "a.png"), "a.png"))
    b = repo.register_asset(_draft(repo, _image(tmp_path / "b.png", "blue"), "b.png"))
    enabled = selection_config.model_copy(
        update={"semantic_ranker": selection_config.semantic_ranker.model_copy(update={"enabled": True})}
    )
    with pytest.raises(ValueError, match="semantic_ranker"):
        select_asset([a, b], config=enabled, run_seed="s", seed_material="m")
    repo.close()


def test_group_derivation_registers_atomically_and_requeries(
    tmp_path: Path,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    primary = repo.register_asset(
        _draft(repo, _image(tmp_path / "p.png"), "p.png", claims=["feature_can_generate_result"])
    )
    plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s005",
                order=1,
                text="结果",
                visual_structure="single",
                slots=[
                    MaterialSlot(
                        slot_id="result",
                        anchor_phrase="结果",
                        entry_policy="scene_start",
                        hold_policy="scene_end",
                        category_id="文生图/文化墙",
                        asset_role="result_image",
                        source=AssetQuerySource(kind="asset_query"),
                        subtitle_emphasis="none",
                    )
                ],
                events=[],
                inputs=[],
                outputs=[SceneOutput(output_name="primary_result", bound_slot="result", asset_role="result_image")],
                claims=[],
                no_asset=False,
            ),
            SemanticScene(
                scene_id="s006",
                order=2,
                text="编辑",
                visual_structure="sequence",
                slots=[
                    MaterialSlot(
                        slot_id="editor",
                        anchor_phrase="编辑",
                        entry_policy="scene_start",
                        hold_policy="scene_end",
                        category_id="文生图/文化墙",
                        asset_role="editor_page",
                        source=RelationFromInputSource(
                            kind="relation_from_input",
                            input_name="source_result",
                            group_alias="culture_wall_editing",
                            group_type="process",
                            pattern_id="editor_sequence",
                            member_key="editor_page",
                        ),
                        subtitle_emphasis="none",
                    )
                ],
                events=[],
                inputs=[
                    SceneInput(
                        input_name="source_result",
                        from_scene="s005",
                        from_output="primary_result",
                        required=True,
                    )
                ],
                outputs=[],
                claims=[],
                no_asset=False,
            ),
        ]
    )
    resolved = AssetPlanResolver(hub).resolve(
        plan,
        session=repo.open_resolution_session(),
        selection_config=selection_config,
        run_seed="atomic",
        registry_snapshot_id="registry://atomic",
        scene_plan_sha256="a" * 64,
        allow_fake_derivation=True,
    )
    assert resolved.scenes[0].outputs["primary_result"] == primary.asset_ref
    binding = resolved.group_bindings["culture_wall_editing"]
    group = repo.get_group(binding)
    assert group is not None
    assert {m.member_key for m in group.members} == {"source_result", "editor_page", "edited_result"}
    assert resolved.derivation_requests
    assert resolved.derivation_requests[0].status == "registered"
    repo.close()

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from video_agent.assets.v4 import (
    AssetDraft,
    AssetGroupDraft,
    AssetPlanResolver,
    AssetQuery,
    GroupQuery,
    LocalObjectStore,
    SQLiteAssetRepository,
    Stage4Error,
)
from video_agent.contracts.v4 import (
    AssetGroupMember,
    AssetQuerySource,
    EvidenceClass,
    MaterialSlot,
    RelationFromInputSource,
    SceneInput,
    SceneOutput,
    SceneSemanticPlan,
    SemanticScene,
    SourceKind,
    Stage4SelectionConfig,
)
from video_agent.assets.v4.gap_policy import load_selection_config
from video_agent.registries import CapabilityRegistryHub


def _image(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 3), color).save(path)
    return path


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(Path(__file__).parents[1] / "config" / "registries" / "v4")


@pytest.fixture
def repo(tmp_path: Path, hub: CapabilityRegistryHub) -> SQLiteAssetRepository:
    result = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    yield result
    result.close()


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
) -> AssetDraft:
    info = repo.object_store.put_file(source, key)
    return AssetDraft(
        filename=Path(key).name,
        object_key=key,
        content_sha256=info.content_sha256,
        media_type=info.media_type,
        module="文生图",
        category_id=category,
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
        lineage=None,
    )


def _slot(
    slot_id: str,
    phrase: str,
    role: str,
    source,
    *,
    category: str | None = "文生图/文化墙",
) -> MaterialSlot:
    return MaterialSlot(
        slot_id=slot_id,
        anchor_phrase=phrase,
        entry_policy="scene_start",
        hold_policy="scene_end",
        category_id=category,
        asset_role=role,
        source=source,
        subtitle_emphasis="none",
    )


def test_group_query_containing_asset_refs(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    result = repo.register_asset(_draft(repo, _image(tmp_path / "r.png"), "r.png", "result_image"))
    editor = repo.register_asset(_draft(repo, _image(tmp_path / "e.png", "blue"), "e.png", "editor_page"))
    edited = repo.register_asset(_draft(repo, _image(tmp_path / "d.png", "green"), "d.png", "edited_result"))
    other = repo.register_asset(_draft(repo, _image(tmp_path / "o.png", "yellow"), "o.png", "result_image"))
    group = repo.register_group(
        AssetGroupDraft(
            group_type="process",
            pattern_id="editor_sequence",
            category_id="文生图/文化墙",
            members=[
                AssetGroupMember(member_key="source_result", asset_role="result_image", asset_ref=result.asset_ref, order=1),
                AssetGroupMember(member_key="editor_page", asset_role="editor_page", asset_ref=editor.asset_ref, order=2),
                AssetGroupMember(member_key="edited_result", asset_role="edited_result", asset_ref=edited.asset_ref, order=3),
            ],
        )
    )
    repo.register_group(
        AssetGroupDraft(
            group_type="process",
            pattern_id="editor_sequence",
            category_id="文生图/文化墙",
            members=[
                AssetGroupMember(member_key="source_result", asset_role="result_image", asset_ref=other.asset_ref, order=1),
                AssetGroupMember(member_key="editor_page", asset_role="editor_page", asset_ref=editor.asset_ref, order=2),
                AssetGroupMember(member_key="edited_result", asset_role="edited_result", asset_ref=edited.asset_ref, order=3),
            ],
        )
    )
    found = repo.query_groups(
        GroupQuery(
            pattern_ids=("editor_sequence",),
            containing_asset_refs=(result.asset_ref,),
            required_member_keys=("editor_page", "edited_result"),
        )
    )
    assert [item.group_ref for item in found] == [group.group_ref]


def test_resolution_session_hides_concurrent_inserts(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    first = repo.register_asset(_draft(repo, _image(tmp_path / "a.png"), "a.png"))
    session = repo.open_resolution_session()
    base = session.base_revision
    assert base == repo.current_revision()
    outsider = repo.register_asset(_draft(repo, _image(tmp_path / "b.png", "blue"), "b.png"))
    visible = session.query_assets(AssetQuery(asset_roles=("result_image",)))
    refs = {item.asset_ref for item in visible}
    assert first.asset_ref in refs
    assert outsider.asset_ref not in refs
    overlay = session.register_asset(_draft(repo, _image(tmp_path / "c.png", "green"), "c.png"))
    visible2 = {item.asset_ref for item in session.query_assets(AssetQuery(asset_roles=("result_image",)))}
    assert overlay.asset_ref in visible2
    assert outsider.asset_ref not in visible2


def test_independent_query_dedup(
    repo: SQLiteAssetRepository,
    tmp_path: Path,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    first = repo.register_asset(_draft(repo, _image(tmp_path / "g.png"), "g.png"))
    second = repo.register_asset(_draft(repo, _image(tmp_path / "p.png", "blue"), "p.png"))
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s002",
                order=1,
                text="文化墙",
                visual_structure="gallery",
                slots=[_slot("g1", "文化墙", "result_image", AssetQuerySource(kind="asset_query"))],
                events=[],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=False,
            ),
            SemanticScene(
                scene_id="s005",
                order=2,
                text="一整面文化墙方案",
                visual_structure="single",
                slots=[_slot("result", "一整面文化墙方案", "result_image", AssetQuerySource(kind="asset_query"))],
                events=[],
                inputs=[],
                outputs=[SceneOutput(output_name="primary_result", bound_slot="result", asset_role="result_image")],
                claims=[],
                no_asset=False,
            ),
        ]
    )
    plan = AssetPlanResolver(hub).resolve(
        scene_plan,
        session=repo.open_resolution_session(),
        selection_config=selection_config,
        run_seed="seed-a",
        registry_snapshot_id="registry://test",
        scene_plan_sha256="a" * 64,
    )
    by_id = {scene.scene_id: scene for scene in plan.scenes}
    assert by_id["s002"].slots[0].asset_ref != by_id["s005"].slots[0].asset_ref
    assert {by_id["s002"].slots[0].asset_ref, by_id["s005"].slots[0].asset_ref} == {first.asset_ref, second.asset_ref}


def test_run_level_alias_reuse_for_s007_s008(
    repo: SQLiteAssetRepository,
    tmp_path: Path,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    primary = repo.register_asset(_draft(repo, _image(tmp_path / "p.png"), "p.png"))
    reference = repo.register_asset(_draft(repo, _image(tmp_path / "ref.png", "green"), "ref.png", "reference_image"))
    plan_img = repo.register_asset(_draft(repo, _image(tmp_path / "plan.png", "yellow"), "plan.png", "flat_plan"))
    causal = repo.register_group(
        AssetGroupDraft(
            group_type="causal",
            pattern_id="reference_result_plan",
            category_id="文生图/文化墙",
            members=[
                AssetGroupMember(member_key="reference_image", asset_role="reference_image", asset_ref=reference.asset_ref, order=1),
                AssetGroupMember(member_key="result_image", asset_role="result_image", asset_ref=primary.asset_ref, order=2),
                AssetGroupMember(member_key="flat_plan", asset_role="flat_plan", asset_ref=plan_img.asset_ref, order=3),
            ],
        )
    )
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s005",
                order=1,
                text="一整面文化墙方案",
                visual_structure="single",
                slots=[_slot("result", "一整面文化墙方案", "result_image", AssetQuerySource(kind="asset_query"))],
                events=[],
                inputs=[],
                outputs=[SceneOutput(output_name="primary_result", bound_slot="result", asset_role="result_image")],
                claims=[],
                no_asset=False,
            ),
            SemanticScene(
                scene_id="s007",
                order=2,
                text="上传实景参考图",
                visual_structure="comparison",
                slots=[
                    _slot(
                        "reference",
                        "上传实景参考图",
                        "reference_image",
                        RelationFromInputSource(
                            kind="relation_from_input",
                            input_name="source_result",
                            group_alias="culture_wall_reference_flow",
                            pattern_id="reference_result_plan",
                            group_type="causal",
                            member_key="reference_image",
                        ),
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
            SemanticScene(
                scene_id="s008",
                order=3,
                text="施工平面图",
                visual_structure="single",
                slots=[
                    _slot(
                        "plan",
                        "施工平面图",
                        "flat_plan",
                        RelationFromInputSource(
                            kind="relation_from_input",
                            input_name="source_result",
                            group_alias="culture_wall_reference_flow",
                            pattern_id="reference_result_plan",
                            group_type="causal",
                            member_key="flat_plan",
                        ),
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
    plan = AssetPlanResolver(hub).resolve(
        scene_plan,
        session=repo.open_resolution_session(),
        selection_config=selection_config,
        run_seed="seed-a",
        registry_snapshot_id="registry://test",
        scene_plan_sha256="a" * 64,
    )
    by_id = {scene.scene_id: scene for scene in plan.scenes}
    assert by_id["s005"].outputs["primary_result"] == primary.asset_ref
    assert plan.group_bindings["culture_wall_reference_flow"] == causal.group_ref
    assert by_id["s007"].slots[0].group_ref == causal.group_ref
    assert by_id["s008"].slots[0].group_ref == causal.group_ref
    assert by_id["s007"].slots[0].asset_ref == reference.asset_ref
    assert by_id["s008"].slots[0].asset_ref == plan_img.asset_ref


def test_relation_requires_containing_upstream(
    repo: SQLiteAssetRepository,
    tmp_path: Path,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    primary = repo.register_asset(_draft(repo, _image(tmp_path / "p.png"), "p.png"))
    other = repo.register_asset(_draft(repo, _image(tmp_path / "o.png", "blue"), "o.png"))
    reference = repo.register_asset(_draft(repo, _image(tmp_path / "ref.png", "green"), "ref.png", "reference_image"))
    plan_img = repo.register_asset(_draft(repo, _image(tmp_path / "plan.png", "yellow"), "plan.png", "flat_plan"))
    repo.register_group(
        AssetGroupDraft(
            group_type="causal",
            pattern_id="reference_result_plan",
            category_id="文生图/文化墙",
            members=[
                AssetGroupMember(member_key="reference_image", asset_role="reference_image", asset_ref=reference.asset_ref, order=1),
                AssetGroupMember(member_key="result_image", asset_role="result_image", asset_ref=other.asset_ref, order=2),
                AssetGroupMember(member_key="flat_plan", asset_role="flat_plan", asset_ref=plan_img.asset_ref, order=3),
            ],
        )
    )
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s005",
                order=1,
                text="结果",
                visual_structure="single",
                slots=[_slot("result", "结果", "result_image", AssetQuerySource(kind="asset_query"))],
                events=[],
                inputs=[],
                outputs=[SceneOutput(output_name="primary_result", bound_slot="result", asset_role="result_image")],
                claims=[],
                no_asset=False,
            ),
            SemanticScene(
                scene_id="s007",
                order=2,
                text="参考",
                visual_structure="comparison",
                slots=[
                    _slot(
                        "reference",
                        "参考",
                        "reference_image",
                        RelationFromInputSource(
                            kind="relation_from_input",
                            input_name="source_result",
                            group_alias="flow",
                            pattern_id="reference_result_plan",
                            group_type="causal",
                            member_key="reference_image",
                        ),
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
    # Force s005 to select primary by superseding other from active query... actually both active.
    # Register only primary as active result for first scene by superseding? Simpler: don't register other as selectable before s005.
    # other is in a group; s005 asset_query may pick primary or other. If it picks other, relation succeeds.
    # Supersede other so s005 must pick primary, then relation fails.
    repo.supersede_asset(other.asset_ref, _draft(repo, _image(tmp_path / "o2.png", "black"), "o2.png"))
    session = repo.open_resolution_session()
    resolver = AssetPlanResolver(hub)
    with pytest.raises(Stage4Error) as exc:
        resolver.resolve(
            scene_plan,
            session=session,
            selection_config=selection_config,
            run_seed="seed",
            registry_snapshot_id="registry://test",
            scene_plan_sha256="b" * 64,
        )
    assert exc.value.code == "missing_derivation_capability"
    assert primary.asset_ref


def test_missing_upstream_output_fail_loud(hub: CapabilityRegistryHub, selection_config: Stage4SelectionConfig, repo: SQLiteAssetRepository) -> None:
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s006",
                order=1,
                text="编辑",
                visual_structure="process",
                slots=[],
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
            )
        ]
    )
    session = repo.open_resolution_session()
    with pytest.raises(Stage4Error) as exc:
        AssetPlanResolver(hub).resolve(
            scene_plan,
            session=session,
            selection_config=selection_config,
            run_seed="x",
            registry_snapshot_id="registry://test",
            scene_plan_sha256="c" * 64,
        )
    assert exc.value.code == "invalid_scene_dependency"


def test_result_gap_can_derive_without_parent_asset(
    repo: SQLiteAssetRepository,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="生成主题公园效果图",
                visual_structure="single",
                slots=[
                    _slot(
                        "result",
                        "主题公园效果图",
                        "result_image",
                        AssetQuerySource(kind="asset_query"),
                        category="文生图/主题公园",
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
    plan = AssetPlanResolver(hub).resolve(
        scene_plan,
        session=repo.open_resolution_session(),
        selection_config=selection_config,
        run_seed="derive-without-parent",
        registry_snapshot_id="registry://test",
        scene_plan_sha256="d" * 64,
        allow_fake_derivation=True,
    )
    asset = repo.get_asset(plan.scenes[0].slots[0].asset_ref)
    assert asset is not None and asset.lineage is not None
    assert asset.lineage.parent_asset_refs == []
    assert plan.derivation_requests[0].status == "registered"


def test_no_asset_transition(
    repo: SQLiteAssetRepository,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s009",
                order=1,
                text="收束",
                visual_structure="no_asset_transition",
                slots=[],
                events=[],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=True,
            )
        ]
    )
    session = repo.open_resolution_session()
    plan = AssetPlanResolver(hub).resolve(
        scene_plan,
        session=session,
        selection_config=selection_config,
        run_seed="seed",
        registry_snapshot_id="registry://test",
        scene_plan_sha256="d" * 64,
    )
    assert plan.scenes[0].scene_id == "s009"
    assert plan.scenes[0].slots == []


def test_deterministic_same_seed(
    repo: SQLiteAssetRepository,
    tmp_path: Path,
    hub: CapabilityRegistryHub,
    selection_config: Stage4SelectionConfig,
) -> None:
    for index, color in enumerate(("red", "blue", "green")):
        repo.register_asset(_draft(repo, _image(tmp_path / f"{index}.png", color), f"{index}.png"))
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s005",
                order=1,
                text="结果",
                visual_structure="single",
                slots=[_slot("result", "结果", "result_image", AssetQuerySource(kind="asset_query"))],
                events=[],
                inputs=[],
                outputs=[SceneOutput(output_name="primary_result", bound_slot="result", asset_role="result_image")],
                claims=[],
                no_asset=False,
            )
        ]
    )
    session_a = repo.open_resolution_session()
    first = AssetPlanResolver(hub).resolve(
        scene_plan,
        session=session_a,
        selection_config=selection_config,
        run_seed="fixed",
        registry_snapshot_id="registry://test",
        scene_plan_sha256="e" * 64,
    )
    session_b = repo.open_resolution_session()
    second = AssetPlanResolver(hub).resolve(
        scene_plan,
        session=session_b,
        selection_config=selection_config,
        run_seed="fixed",
        registry_snapshot_id="registry://test",
        scene_plan_sha256="e" * 64,
    )
    assert first.scenes[0].slots[0].asset_ref == second.scenes[0].slots[0].asset_ref

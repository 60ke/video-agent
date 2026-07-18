from __future__ import annotations

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
from video_agent.assets.v4.gap_policy import load_selection_config
from video_agent.contracts.v4 import (
    AssetGroupMember,
    EvidenceClass,
    SceneSemanticPlan,
    SourceKind,
)
from video_agent.io import load_json
from video_agent.registries import CapabilityRegistryHub


FIXTURE = Path(__file__).parent / "fixtures" / "v4" / "stage0"


def _image(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6), color).save(path)
    return path


def _category_path(category_id: str) -> list[str]:
    return [category_id.split("/", 1)[1]] if "/" in category_id else [category_id]


def _module(category_id: str) -> str:
    return category_id.split("/", 1)[0] if "/" in category_id else category_id


def _draft(
    repo: SQLiteAssetRepository,
    source: Path,
    key: str,
    *,
    category_id: str | None,
    role: str,
    claims: list[str] | None = None,
) -> AssetDraft:
    info = repo.object_store.put_file(source, key)
    return AssetDraft(
        filename=Path(key).name,
        object_key=key,
        content_sha256=info.content_sha256,
        media_type=info.media_type,
        module=_module(category_id) if category_id else None,
        category_id=category_id,
        category_path=_category_path(category_id) if category_id else [],
        asset_role=role,
        width=info.width,
        height=info.height,
        orientation=info.orientation,
        animated=False,
        source_kind=SourceKind.ORIGINAL,
        origin_type="golden",
        evidence_class=EvidenceClass.SOURCE,
        claims=claims or [],
        lineage=None,
    )


@pytest.fixture
def hub() -> CapabilityRegistryHub:
    return CapabilityRegistryHub.load(Path(__file__).parents[1] / "config" / "registries" / "v4")


def _seed_golden_repo(repo: SQLiteAssetRepository, tmp_path: Path) -> dict[str, str]:
    home = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "home.png"),
            "home.png",
            category_id="网站/主页",
            role="site_home",
            claims=["real_website_screenshot"],
        )
    )
    cw1 = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "cw1.png", "blue"),
            "cw1.png",
            category_id="文生图/文化墙",
            role="result_image",
            claims=["feature_can_generate_result"],
        )
    )
    cw2 = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "cw2.png", "green"),
            "cw2.png",
            category_id="文生图/文化墙",
            role="result_image",
            claims=["feature_can_generate_result"],
        )
    )
    sign = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "sign.png", "yellow"),
            "sign.png",
            category_id="文生图/门头招牌",
            role="result_image",
            claims=["feature_can_generate_result"],
        )
    )
    decor = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "decor.png", "purple"),
            "decor.png",
            category_id="文生图/美陈",
            role="result_image",
            claims=["feature_can_generate_result"],
        )
    )
    entry = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "entry.png", "orange"),
            "entry.png",
            category_id="文生图/文化墙",
            role="feature_entry",
        )
    )
    p_base = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "pbase.png", "pink"),
            "pbase.png",
            category_id="文生图/文化墙",
            role="parameter_panel",
        )
    )
    p_stage = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "pstage.png", "cyan"),
            "pstage.png",
            category_id="文生图/文化墙",
            role="parameter_panel",
        )
    )
    p_final = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "pfinal.png", "brown"),
            "pfinal.png",
            category_id="文生图/文化墙",
            role="parameter_panel",
        )
    )
    params = repo.register_group(
        AssetGroupDraft(
            group_type="process",
            pattern_id="parameter_callout_sequence",
            category_id="文生图/文化墙",
            members=[
                AssetGroupMember(member_key="base", asset_role="parameter_panel", asset_ref=p_base.asset_ref, order=1),
                AssetGroupMember(member_key="stage", asset_role="parameter_panel", asset_ref=p_stage.asset_ref, order=2),
                AssetGroupMember(member_key="final", asset_role="parameter_panel", asset_ref=p_final.asset_ref, order=3),
            ],
        )
    )
    editor_refs = {}
    causal_refs = {}
    for result in (cw1, cw2):
        editor_page = repo.register_asset(
            _draft(
                repo,
                _image(tmp_path / f"editor_{result.asset_ref[-4:]}.png", "navy"),
                f"editor_{result.asset_ref[-4:]}.png",
                category_id="文生图/文化墙",
                role="editor_page",
            )
        )
        edited = repo.register_asset(
            _draft(
                repo,
                _image(tmp_path / f"edited_{result.asset_ref[-4:]}.png", "olive"),
                f"edited_{result.asset_ref[-4:]}.png",
                category_id="文生图/文化墙",
                role="edited_result",
            )
        )
        editor = repo.register_group(
            AssetGroupDraft(
                group_type="process",
                pattern_id="editor_sequence",
                category_id="文生图/文化墙",
                members=[
                    AssetGroupMember(member_key="source_result", asset_role="result_image", asset_ref=result.asset_ref, order=1),
                    AssetGroupMember(member_key="editor_page", asset_role="editor_page", asset_ref=editor_page.asset_ref, order=2),
                    AssetGroupMember(member_key="edited_result", asset_role="edited_result", asset_ref=edited.asset_ref, order=3),
                ],
            )
        )
        reference = repo.register_asset(
            _draft(
                repo,
                _image(tmp_path / f"ref_{result.asset_ref[-4:]}.png", "teal"),
                f"ref_{result.asset_ref[-4:]}.png",
                category_id="文生图/文化墙",
                role="reference_image",
            )
        )
        plan = repo.register_asset(
            _draft(
                repo,
                _image(tmp_path / f"plan_{result.asset_ref[-4:]}.png", "gray"),
                f"plan_{result.asset_ref[-4:]}.png",
                category_id="文生图/文化墙",
                role="flat_plan",
            )
        )
        causal = repo.register_group(
            AssetGroupDraft(
                group_type="causal",
                pattern_id="reference_result_plan",
                category_id="文生图/文化墙",
                members=[
                    AssetGroupMember(member_key="reference_image", asset_role="reference_image", asset_ref=reference.asset_ref, order=1),
                    AssetGroupMember(member_key="result_image", asset_role="result_image", asset_ref=result.asset_ref, order=2),
                    AssetGroupMember(member_key="flat_plan", asset_role="flat_plan", asset_ref=plan.asset_ref, order=3),
                ],
            )
        )
        editor_refs[result.asset_ref] = editor.group_ref
        causal_refs[result.asset_ref] = causal.group_ref

    outro = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "outro.png", "black"),
            "outro.png",
            category_id=None,
            role="outro",
        )
    )
    repo.bind_configured_asset("default_outro", outro.asset_ref)
    return {
        "home": home.asset_ref,
        "cw1": cw1.asset_ref,
        "cw2": cw2.asset_ref,
        "sign": sign.asset_ref,
        "decor": decor.asset_ref,
        "entry": entry.asset_ref,
        "params": params.group_ref,
        "outro": outro.asset_ref,
        **{f"editor:{ref}": group for ref, group in editor_refs.items()},
        **{f"causal:{ref}": group for ref, group in causal_refs.items()},
    }


def test_stage0_golden_s001_to_s010(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    seeded = _seed_golden_repo(repo, tmp_path)
    plan = SceneSemanticPlan.model_validate(load_json(FIXTURE / "scene_semantic_plan.payload.json"))
    selection = load_selection_config(Path(__file__).parents[1] / "config" / "stage4_selection.v4.json")
    resolved = AssetPlanResolver(hub).resolve(
        plan,
        session=repo.open_resolution_session(),
        selection_config=selection,
        run_seed="golden",
        registry_snapshot_id="registry://golden",
        scene_plan_sha256="f" * 64,
        allow_fake_derivation=False,
    )
    by_id = {scene.scene_id: scene for scene in resolved.scenes}
    assert set(by_id) == {f"s{index:03d}" for index in range(1, 11)}

    assert by_id["s001"].slots[0].asset_ref == seeded["home"]
    assert by_id["s002"].slots[0].asset_ref in {seeded["cw1"], seeded["cw2"]}
    assert by_id["s002"].slots[1].asset_ref == seeded["sign"]
    assert by_id["s002"].slots[2].asset_ref == seeded["decor"]
    assert by_id["s003"].slots[0].asset_ref == seeded["entry"]
    assert resolved.group_bindings["culture_wall_parameters"] == seeded["params"]
    assert [slot.member_key for slot in by_id["s004"].slots] == ["base", "stage", "final"]

    primary = by_id["s005"].outputs["primary_result"]
    assert primary in {seeded["cw1"], seeded["cw2"]}
    assert primary != by_id["s002"].slots[0].asset_ref

    assert resolved.group_bindings["culture_wall_editing"] == seeded[f"editor:{primary}"]
    assert resolved.group_bindings["culture_wall_reference_flow"] == seeded[f"causal:{primary}"]
    assert by_id["s007"].slots[0].group_ref == by_id["s008"].slots[0].group_ref == seeded[f"causal:{primary}"]
    assert by_id["s009"].slots == []
    assert by_id["s010"].slots[0].asset_ref == seeded["outro"]
    repo.close()


def test_group_derivation_with_fake_executor(tmp_path: Path, hub: CapabilityRegistryHub) -> None:
    repo = SQLiteAssetRepository(tmp_path / "repo.sqlite3", LocalObjectStore(tmp_path / "objects"), hub)
    primary = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "p.png"),
            "p.png",
            category_id="文生图/文化墙",
            role="result_image",
            claims=["feature_can_generate_result"],
        )
    )
    plan = SceneSemanticPlan.model_validate(
        {
            "scenes": [
                {
                    "scene_id": "s005",
                    "order": 1,
                    "text": "结果",
                    "visual_structure": "single",
                    "slots": [
                        {
                            "slot_id": "result",
                            "anchor_phrase": "结果",
                            "entry_policy": "scene_start",
                            "hold_policy": "scene_end",
                            "category_id": "文生图/文化墙",
                            "asset_role": "result_image",
                            "source": {"kind": "asset_query"},
                            "subtitle_emphasis": "none",
                        }
                    ],
                    "events": [],
                    "inputs": [],
                    "outputs": [{"output_name": "primary_result", "bound_slot": "result", "asset_role": "result_image"}],
                    "claims": [],
                    "no_asset": False,
                },
                {
                    "scene_id": "s006",
                    "order": 2,
                    "text": "编辑",
                    "visual_structure": "sequence",
                    "slots": [
                        {
                            "slot_id": "editor",
                            "anchor_phrase": "编辑",
                            "entry_policy": "scene_start",
                            "hold_policy": "scene_end",
                            "category_id": "文生图/文化墙",
                            "asset_role": "editor_page",
                            "source": {
                                "kind": "relation_from_input",
                                "input_name": "source_result",
                                "group_alias": "culture_wall_editing",
                                "group_type": "process",
                                "pattern_id": "editor_sequence",
                                "member_key": "editor_page",
                            },
                            "subtitle_emphasis": "none",
                        }
                    ],
                    "events": [],
                    "inputs": [
                        {
                            "input_name": "source_result",
                            "from_scene": "s005",
                            "from_output": "primary_result",
                            "required": True,
                        }
                    ],
                    "outputs": [],
                    "claims": [],
                    "no_asset": False,
                },
            ]
        }
    )
    selection = load_selection_config(Path(__file__).parents[1] / "config" / "stage4_selection.v4.json")
    resolved = AssetPlanResolver(hub).resolve(
        plan,
        session=repo.open_resolution_session(),
        selection_config=selection,
        run_seed="derive",
        registry_snapshot_id="registry://derive",
        scene_plan_sha256="1" * 64,
        allow_fake_derivation=True,
    )
    assert resolved.scenes[0].outputs["primary_result"] == primary.asset_ref
    assert "culture_wall_editing" in resolved.group_bindings
    assert resolved.scenes[1].slots[0].status == "resolved_group_member"
    assert resolved.derivation_requests
    repo.close()

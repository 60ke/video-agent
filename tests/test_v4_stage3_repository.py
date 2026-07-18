from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from video_agent.assets.v4 import (
    AssetConflictError,
    AssetDraft,
    AssetGroupDraft,
    AssetImportError,
    AssetQuery,
    GroupQuery,
    LocalObjectStore,
    ObjectConflictError,
    ObjectStoreError,
    SQLiteAssetRepository,
    audit_repository,
    import_manifest,
    migrate_legacy,
)
from video_agent.contracts.v4 import AssetGroupMember, AssetLineage, EvidenceClass, SourceKind
from video_agent.io import sha256_file
from video_agent.registries import CapabilityRegistryHub
from video_agent.cli import _exception_result


def _image(path: Path, color: str = "red") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 3), color).save(path)
    return path


def _ffmpeg_available() -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True, check=False).returncode == 0
    except FileNotFoundError:
        return False


@pytest.fixture
def repo(tmp_path: Path) -> SQLiteAssetRepository:
    result = SQLiteAssetRepository(
        tmp_path / "repo.sqlite3",
        LocalObjectStore(tmp_path / "objects"),
        CapabilityRegistryHub.load(Path(__file__).parents[1] / "config" / "registries" / "v4"),
    )
    yield result
    result.close()


def _draft(
    repo: SQLiteAssetRepository,
    source: Path,
    key: str,
    role: str = "result_image",
    *,
    lineage=None,
    category: bool = True,
) -> AssetDraft:
    info = repo.object_store.put_file(source, key)
    return AssetDraft(
        filename=Path(key).name,
        object_key=key,
        content_sha256=info.content_sha256,
        media_type=info.media_type,
        module="文生图" if category else None,
        category_id="文生图/文化墙" if category else None,
        category_path=["文化墙"] if category else [],
        asset_role=role,
        width=info.width,
        height=info.height,
        orientation=info.orientation,
        animated=False,
        source_kind=SourceKind.DERIVED if lineage else SourceKind.ORIGINAL,
        origin_type="test",
        evidence_class=EvidenceClass.SEMANTIC if lineage else EvidenceClass.SOURCE,
        claims=[],
        lineage=lineage,
    )


def test_schema_init_is_idempotent(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    hub = CapabilityRegistryHub.load(Path(__file__).parents[1] / "config" / "registries" / "v4")
    first = SQLiteAssetRepository(tmp_path / "repo.sqlite3", store, hub)
    first.close()
    second = SQLiteAssetRepository(tmp_path / "repo.sqlite3", store, hub)
    assert second.connection.execute("SELECT value FROM repository_meta WHERE key='schema_version'").fetchone()["value"] == "1"
    second.close()


def test_object_store_rejects_traversal_and_conflict(tmp_path: Path) -> None:
    store, first, second = LocalObjectStore(tmp_path / "objects"), _image(tmp_path / "a.png"), _image(tmp_path / "b.png", "blue")
    with pytest.raises(ObjectStoreError):
        store.resolve("../a.png")
    store.put_file(first, "results/a.png")
    with pytest.raises(ObjectConflictError):
        store.put_file(second, "results/a.png")


@pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg required for video object probe")
def test_object_store_accepts_video_and_rejects_audio(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    video = tmp_path / "clip.mp4"
    audio = tmp_path / "clip.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=16x16:d=0.1",
            "-pix_fmt",
            "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1", str(audio)],
        check=True,
        capture_output=True,
    )
    info = store.put_file(video, "outro/clip.mp4")
    assert info.media_type.startswith("video/")
    assert info.width == 16 and info.height == 16
    assert info.animated is True
    with pytest.raises(ObjectStoreError, match="audio"):
        store.put_file(audio, "sfx/clip.wav")


def test_register_query_supersede_signature_and_freeze(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    parent = repo.register_asset(_draft(repo, _image(tmp_path / "parent.png"), "results/parent.png"))
    lineage = AssetLineage(
        parent_asset_refs=[parent.asset_ref],
        derivation_type="test",
        executor_id="test",
        parameters_sha256="b" * 64,
        derivation_signature="c" * 64,
        created_at=parent.created_at,
    )
    child = repo.register_asset(_draft(repo, _image(tmp_path / "child.png"), "results/child.png", lineage=lineage))
    assert repo.query_assets(AssetQuery(asset_roles=("result_image",))) == [parent, child]
    assert repo.find_by_derivation_signature("c" * 64) == child
    replacement = repo.supersede_asset(
        parent.asset_ref, _draft(repo, _image(tmp_path / "replacement.png"), "results/replacement.png")
    )
    assert repo.get_asset(parent.asset_ref, include_superseded=False) is None
    assert repo.query_assets(AssetQuery()) == [replacement]
    assert repo.get_asset(child.asset_ref) == child
    first = repo.freeze([child.asset_ref, replacement.asset_ref, parent.asset_ref], [])
    second = repo.freeze([replacement.asset_ref, parent.asset_ref, child.asset_ref], [])
    assert first.content_sha256 == second.content_sha256
    restored_assets, _ = repo.restore_snapshot(first)
    assert {asset.asset_ref for asset in restored_assets} == {child.asset_ref, replacement.asset_ref, parent.asset_ref}
    assert any(asset.status.value == "superseded" for asset in restored_assets)
    # Tamper object bytes after freeze.
    path = repo.object_store.resolve(replacement.object_key)
    path.write_bytes(b"not-an-image-anymore")
    with pytest.raises(Exception):
        repo.validate_snapshot(first)


def test_group_pattern_validation(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    refs = []
    for role, name in (("reference_image", "reference.png"), ("result_image", "result.png"), ("flat_plan", "plan.png")):
        refs.append(repo.register_asset(_draft(repo, _image(tmp_path / name), f"results/{name}", role)))
    group = repo.register_group(
        AssetGroupDraft(
            "causal",
            "reference_result_plan",
            "文生图/文化墙",
            [
                AssetGroupMember(member_key="reference_image", asset_role="reference_image", asset_ref=refs[0].asset_ref, order=1),
                AssetGroupMember(member_key="result_image", asset_role="result_image", asset_ref=refs[1].asset_ref, order=2),
                AssetGroupMember(member_key="flat_plan", asset_role="flat_plan", asset_ref=refs[2].asset_ref, order=3),
            ],
        )
    )
    assert group.pattern_id == "reference_result_plan"


def test_import_does_not_persist_source_path(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    source = _image(tmp_path / "external" / "source.png")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {
                        "source": str(source),
                        "object_key": "results/imported.png",
                        "module": "文生图",
                        "category_id": "文生图/文化墙",
                        "category_path": ["文化墙"],
                        "asset_role": "result_image",
                        "source_kind": "original",
                        "origin_type": "imported",
                        "evidence_class": "E0_source_evidence",
                        "claims": [],
                    }
                ],
                "groups": [],
            }
        ),
        encoding="utf-8",
    )
    result = import_manifest(repo, manifest)
    assert str(source) not in json.dumps(repo.get_asset(result["assets"][0]).model_dump(mode="json"), ensure_ascii=False)


def test_import_derived_lineage_and_orphan_report(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    parent_src = _image(tmp_path / "external" / "parent.png", "red")
    child_src = _image(tmp_path / "external" / "child.png", "blue")
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {
                        "id": "parent",
                        "source": str(parent_src),
                        "object_key": "results/parent.png",
                        "module": "文生图",
                        "category_id": "文生图/文化墙",
                        "category_path": ["文化墙"],
                        "asset_role": "result_image",
                        "source_kind": "original",
                        "origin_type": "imported",
                        "evidence_class": "E0_source_evidence",
                        "claims": [],
                    },
                    {
                        "id": "child",
                        "source": str(child_src),
                        "object_key": "results/child.png",
                        "module": "文生图",
                        "category_id": "文生图/文化墙",
                        "category_path": ["文化墙"],
                        "asset_role": "flat_plan",
                        "source_kind": "derived",
                        "origin_type": "imported",
                        "evidence_class": "E2_semantic_derivative",
                        "claims": [],
                        "lineage": {
                            "parent_asset_refs": ["parent"],
                            "derivation_type": "test",
                            "executor_id": "test",
                            "parameters_sha256": "a" * 64,
                            "derivation_signature": "b" * 64,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        },
                    },
                ],
                "groups": [],
            }
        ),
        encoding="utf-8",
    )
    result = import_manifest(repo, good)
    child = repo.get_asset(result["assets"][1])
    assert child is not None and child.lineage is not None
    assert child.lineage.parent_asset_refs == [result["assets"][0]]

    bad_src = _image(tmp_path / "external" / "bad.png", "green")
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {
                        "source": str(bad_src),
                        "object_key": "results/orphan.png",
                        "module": "文生图",
                        "category_id": "文生图/文化墙",
                        "category_path": ["文化墙"],
                        "asset_role": "result_image",
                        "source_kind": "derived",
                        "origin_type": "imported",
                        "evidence_class": "E2_semantic_derivative",
                        "claims": [],
                    }
                ],
                "groups": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssetImportError) as exc:
        import_manifest(repo, bad)
    assert "lineage" in str(exc.value).lower() or exc.value.orphans is not None


def test_import_lineage_keeps_existing_refs_and_topologically_orders_local_parents(
    repo: SQLiteAssetRepository,
    tmp_path: Path,
) -> None:
    existing = repo.register_asset(
        _draft(repo, _image(tmp_path / "existing.png", "black"), "results/existing.png")
    )
    child_src = _image(tmp_path / "external" / "child-first.png", "blue")
    parent_src = _image(tmp_path / "external" / "parent-second.png", "red")
    external_child_src = _image(tmp_path / "external" / "external-child.png", "green")
    manifest = tmp_path / "lineage-order.json"
    common = {
        "module": "文生图",
        "category_id": "文生图/文化墙",
        "category_path": ["文化墙"],
        "origin_type": "imported",
        "claims": [],
    }
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [
                    {
                        "id": "child",
                        "source": str(child_src),
                        "object_key": "results/child-first.png",
                        "asset_role": "flat_plan",
                        "source_kind": "derived",
                        "evidence_class": "E2_semantic_derivative",
                        "lineage": {
                            "parent_asset_refs": ["parent"],
                            "derivation_type": "test",
                            "executor_id": "test",
                            "parameters_sha256": "1" * 64,
                            "derivation_signature": "2" * 64,
                        },
                        **common,
                    },
                    {
                        "id": "parent",
                        "source": str(parent_src),
                        "object_key": "results/parent-second.png",
                        "asset_role": "result_image",
                        "source_kind": "original",
                        "evidence_class": "E0_source_evidence",
                        **common,
                    },
                    {
                        "id": "external_child",
                        "source": str(external_child_src),
                        "object_key": "results/external-child.png",
                        "asset_role": "flat_plan",
                        "source_kind": "derived",
                        "evidence_class": "E2_semantic_derivative",
                        "lineage": {
                            "parent_asset_refs": [existing.asset_ref],
                            "derivation_type": "test",
                            "executor_id": "test",
                            "parameters_sha256": "3" * 64,
                            "derivation_signature": "4" * 64,
                        },
                        **common,
                    },
                ],
                "groups": [],
            }
        ),
        encoding="utf-8",
    )

    result = import_manifest(repo, manifest)
    child = repo.get_asset(result["assets"][0])
    parent = repo.get_asset(result["assets"][1])
    external_child = repo.get_asset(result["assets"][2])
    assert child is not None and child.lineage is not None and parent is not None
    assert child.lineage.parent_asset_refs == [parent.asset_ref]
    assert external_child is not None and external_child.lineage is not None
    assert external_child.lineage.parent_asset_refs == [existing.asset_ref]


def test_import_rejects_lineage_cycles_before_copy(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    first = _image(tmp_path / "external" / "first.png", "red")
    second = _image(tmp_path / "external" / "second.png", "blue")
    manifest = tmp_path / "cycle.json"

    def item(asset_id: str, source: Path, parent: str, signature: str) -> dict[str, object]:
        return {
            "id": asset_id,
            "source": str(source),
            "object_key": f"results/{asset_id}.png",
            "module": "文生图",
            "category_id": "文生图/文化墙",
            "category_path": ["文化墙"],
            "asset_role": "flat_plan",
            "source_kind": "derived",
            "origin_type": "imported",
            "evidence_class": "E2_semantic_derivative",
            "claims": [],
            "lineage": {
                "parent_asset_refs": [parent],
                "derivation_type": "test",
                "executor_id": "test",
                "parameters_sha256": "5" * 64,
                "derivation_signature": signature * 64,
            },
        }

    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": [item("first", first, "second", "6"), item("second", second, "first", "7")],
                "groups": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssetImportError, match="lineage cycle"):
        import_manifest(repo, manifest)
    assert not (tmp_path / "objects" / "results" / "first.png").exists()


def test_cli_preserves_import_orphan_diagnostics() -> None:
    result = _exception_result(AssetImportError("registration failed", orphans=["results/orphan.png"]))
    assert result == {
        "ok": False,
        "error": "AssetImportError",
        "message": "registration failed",
        "orphans": ["results/orphan.png"],
    }


def test_configured_bindings_enforce_roles_and_audit_stale_roles(
    repo: SQLiteAssetRepository,
    tmp_path: Path,
) -> None:
    result = repo.register_asset(_draft(repo, _image(tmp_path / "result.png"), "results/result.png"))
    logo = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "logo.png", "blue"),
            "brand/logo.png",
            role="brand_logo",
            category=False,
        )
    )
    outro = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "outro.png", "green"),
            "brand/outro.png",
            role="outro",
            category=False,
        )
    )
    with pytest.raises(AssetConflictError, match="requires one of"):
        repo.bind_configured_asset("default_outro", result.asset_ref)
    repo.bind_configured_asset("default_brand_logo", logo.asset_ref)
    repo.bind_configured_asset("default_outro", outro.asset_ref)
    assert audit_repository(repo)["ok"] is True

    repo.connection.execute(
        "UPDATE configured_asset_bindings SET asset_ref=? WHERE config_key='default_outro'",
        (logo.asset_ref,),
    )
    audit = audit_repository(repo)
    assert audit["ok"] is False
    assert any("default_outro" in failure and "requires one of" in failure for failure in audit["failures"])


def test_audit_detects_lineage_cycles(repo: SQLiteAssetRepository, tmp_path: Path) -> None:
    parent = repo.register_asset(_draft(repo, _image(tmp_path / "parent.png"), "results/parent.png"))

    def lineage(parent_ref: str, marker: str) -> AssetLineage:
        return AssetLineage(
            parent_asset_refs=[parent_ref],
            derivation_type="test",
            executor_id="test",
            parameters_sha256=marker * 64,
            derivation_signature=str(int(marker) + 1) * 64,
            created_at=datetime.now(timezone.utc),
        )

    first = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "first-derived.png", "blue"),
            "results/first-derived.png",
            role="flat_plan",
            lineage=lineage(parent.asset_ref, "1"),
        )
    )
    second = repo.register_asset(
        _draft(
            repo,
            _image(tmp_path / "second-derived.png", "green"),
            "results/second-derived.png",
            role="flat_plan",
            lineage=lineage(first.asset_ref, "3"),
        )
    )
    repo.connection.execute("DELETE FROM asset_parents WHERE asset_ref=?", (first.asset_ref,))
    repo.connection.execute(
        "INSERT INTO asset_parents VALUES (?,?,1)",
        (first.asset_ref, second.asset_ref),
    )
    logo = repo.register_asset(
        _draft(repo, _image(tmp_path / "cycle-logo.png"), "brand/cycle-logo.png", role="brand_logo", category=False)
    )
    outro = repo.register_asset(
        _draft(repo, _image(tmp_path / "cycle-outro.png"), "brand/cycle-outro.png", role="outro", category=False)
    )
    repo.bind_configured_asset("default_brand_logo", logo.asset_ref)
    repo.bind_configured_asset("default_outro", outro.asset_ref)
    audit = audit_repository(repo)
    assert audit["ok"] is False
    assert any("lineage cycle" in failure for failure in audit["failures"])


def _write_legacy_fixture(root: Path, *, incomplete_editor: bool = False) -> dict[str, Path]:
    paths = {
        "result": _image(root / "results" / "result.png", "red"),
        "reference": _image(root / "results" / "reference.png", "blue"),
        "plan": _image(root / "derived" / "generated" / "plan.png", "green"),
        "editor": _image(root / "derived" / "workflow" / "editor.png", "yellow"),
        "edited": _image(root / "derived" / "workflow" / "edited.png", "purple"),
        "logo": _image(root / "brand" / "kehuanxiongmao" / "logo" / "柯幻熊猫_LOGO.png", "white"),
        "outro": _image(root / "brand" / "outro.png", "black"),
        "base": _image(root / "derived" / "sites" / "seq_base.png", "#111111"),
        "stage": _image(root / "derived" / "sites" / "seq_stage.png", "#222222"),
        "final": _image(root / "derived" / "sites" / "seq_final.png", "#333333"),
        "source_shot": _image(root / "sites" / "source_entry.png", "#444444"),
        "entry_out": _image(root / "derived" / "sites" / "柯幻熊猫" / "文生图" / "功能入口" / "entry_out.png", "#555555"),
    }
    result_sha = sha256_file(paths["result"])
    editor_sha = sha256_file(paths["editor"])
    catalog = {
        "assets": [
            {
                "asset_id": "result",
                "path": "assets/results/result.png",
                "sha256": result_sha,
                "role": "result_image",
                "semantic_path": ["文生图", "文化墙"],
                "evidence_class": "E0_source_evidence",
                "claims": ["curated_result_image"],
                "provenance": {"origin": "result_library", "parent_asset_ids": []},
            },
            {
                "asset_id": "reference",
                "path": "assets/results/reference.png",
                "sha256": sha256_file(paths["reference"]),
                "role": "reference_image",
                "semantic_path": ["文生图", "文化墙"],
                "evidence_class": "E0_source_evidence",
                "claims": [],
                "provenance": {"origin": "result_library", "parent_asset_ids": []},
            },
            {
                "asset_id": "plan",
                "path": "assets/derived/generated/plan.png",
                "sha256": sha256_file(paths["plan"]),
                "role": "plane_result",
                "semantic_path": ["文生图", "文化墙"],
                "evidence_class": "E2_semantic_derivative",
                "claims": [],
                "derive_kind": "result_to_flat_plan",
                "provenance": {"origin": "generated", "parent_asset_ids": ["result"]},
            },
            {
                "asset_id": "editor",
                "path": "assets/derived/workflow/editor.png",
                "sha256": editor_sha,
                "role": "editor_workspace",
                "semantic_path": ["文生图", "文化墙"],
                "evidence_class": "E0_source_evidence",
                "claims": [],
                "provenance": {"origin": "workflow", "parent_asset_ids": []},
            },
            {
                "asset_id": "edited",
                "path": "assets/derived/workflow/edited.png",
                "sha256": sha256_file(paths["edited"]),
                "role": "result_image",
                "semantic_path": ["文生图", "文化墙"],
                "evidence_class": "E2_semantic_derivative",
                "claims": [],
                "derive_kind": "edited_result",
                "provenance": {"origin": "generated", "parent_asset_ids": ["result"]},
            },
            {
                "asset_id": "logo",
                "path": "assets/brand/kehuanxiongmao/logo/柯幻熊猫_LOGO.png",
                "sha256": sha256_file(paths["logo"]),
                "role": "brand_logo",
                "evidence_class": "E0_source_evidence",
                "claims": [],
                "provenance": {"origin": "brand", "parent_asset_ids": []},
            },
            {
                "asset_id": "outro",
                "path": "assets/brand/outro.png",
                "sha256": sha256_file(paths["outro"]),
                "role": "outro",
                "evidence_class": "E3_decorative",
                "claims": [],
                "provenance": {"origin": "decorative", "parent_asset_ids": []},
            },
            {
                "asset_id": "source_shot",
                "path": "assets/sites/source_entry.png",
                "sha256": sha256_file(paths["source_shot"]),
                "role": "feature_entry",
                "semantic_path": ["文生图", "文化墙"],
                "evidence_class": "E0_source_evidence",
                "claims": ["real_website_screenshot"],
                "provenance": {"origin": "site_screenshot_library", "parent_asset_ids": []},
            },
        ]
    }
    if incomplete_editor:
        relationships = {
            "relationships": [
                {
                    "relationship_id": "broken_editor",
                    "feature_path": ["文化墙"],
                    "result_asset_id": "editor",
                    "editor_composite_asset_id": "editor",
                }
            ]
        }
        workflow = {"assets": []}
    else:
        relationships = {
            "relationships": [
                {
                    "relationship_id": "causal_1",
                    "feature_path": ["文化墙"],
                    "reference_asset_id": "reference",
                    "result_asset_id": "result",
                    "flat_plan_asset_id": "plan",
                    "editor_composite_asset_id": "editor",
                    "edited_result_asset_id": "edited",
                },
                {
                    "relationship_id": "editor_dup",
                    "feature_path": ["文化墙"],
                    "result_asset_id": "editor",
                    "editor_composite_asset_id": "editor",
                    "edited_result_asset_id": "edited",
                },
                {
                    "relationship_id": "edited_probe",
                    "result_asset_id": "result",
                    "edited_asset_id": "edited",
                },
            ]
        }
        workflow = {
            "assets": [
                {
                    "path": str(paths["editor"]),
                    "sha256": editor_sha,
                    "role": "editor_workspace",
                    "semantic_path": ["文生图", "文化墙"],
                    "editor_flow_sequence_id": "editor_flow_test",
                    "editor_flow_role": "page",
                    "source_artwork_sha256": result_sha,
                    "workflow_step": "editor_page",
                },
                {
                    "path": str(paths["edited"]),
                    "sha256": sha256_file(paths["edited"]),
                    "role": "result_image",
                    "semantic_path": ["文生图", "文化墙"],
                    "editor_flow_sequence_id": "editor_flow_test",
                    "editor_flow_role": "edited_result",
                    "source_artwork_sha256": result_sha,
                    "derive_kind": "edited_result",
                    "workflow_step": "edited_result",
                },
            ]
        }
    sequences = {
        "sequences": [
            {
                "sequence_id": "seq_1",
                "feature_path": ["文化墙"],
                "frames": {
                    "base": {"path": "assets/derived/sites/seq_base.png", "sha256": sha256_file(paths["base"])},
                    "stage": {"path": "assets/derived/sites/seq_stage.png", "sha256": sha256_file(paths["stage"])},
                    "final": {"path": "assets/derived/sites/seq_final.png", "sha256": sha256_file(paths["final"])},
                },
            }
        ]
    }
    entry_manifest = {
        "assets": [
            {
                "output_path": str(paths["entry_out"]),
                "output_sha256": sha256_file(paths["entry_out"]),
                "source_sha256": sha256_file(paths["source_shot"]),
                "feature_path": ["文化墙"],
                "provider": "apiyi",
                "model": "gpt-image-2",
                "prompt_sha256": "d" * 64,
            }
        ]
    }
    (root / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
    (root / "relationships.json").write_text(json.dumps(relationships), encoding="utf-8")
    (root / "derived" / "workflow_scenes").mkdir(parents=True, exist_ok=True)
    (root / "derived" / "workflow_scenes" / "manifest.json").write_text(json.dumps(workflow), encoding="utf-8")
    seq_dir = root / "derived" / "sites" / "柯幻熊猫" / "文生图" / "参数面板序列"
    seq_dir.mkdir(parents=True, exist_ok=True)
    (seq_dir / "manifest.json").write_text(json.dumps(sequences), encoding="utf-8")
    entry_dir = root / "derived" / "sites" / "柯幻熊猫" / "文生图" / "功能入口"
    entry_dir.mkdir(parents=True, exist_ok=True)
    (entry_dir / "manifest.json").write_text(json.dumps(entry_manifest), encoding="utf-8")
    return paths


def test_legacy_migration_idempotent_groups_bindings_and_no_comparison(repo: SQLiteAssetRepository) -> None:
    root = repo.object_store.root
    _write_legacy_fixture(root)
    first = migrate_legacy(repo, root)
    second = migrate_legacy(repo, root)
    assert first == second
    patterns = {item["pattern_id"] for item in first["groups"]}
    assert "reference_result_plan" in patterns
    assert "editor_sequence" in patterns
    assert "parameter_callout_sequence" in patterns
    assert "comparison" not in patterns
    assert repo.configured_asset("default_brand_logo") is not None
    assert repo.configured_asset("default_outro") is not None
    entry = next(a for a in repo.query_assets(AssetQuery(active_only=False)) if a.filename == "entry_out.png")
    assert entry.lineage is not None
    assert entry.source_kind is SourceKind.DERIVED
    audit = audit_repository(repo)
    assert audit["ok"] is True
    assert repo.query_groups(GroupQuery(pattern_ids=("comparison",))) == []


def test_legacy_migration_dry_run_matches_write_validation(repo: SQLiteAssetRepository) -> None:
    root = repo.object_store.root
    _write_legacy_fixture(root, incomplete_editor=True)
    with pytest.raises(ValueError, match="incomplete editor_sequence|distinct editor_page"):
        migrate_legacy(repo, root, dry_run=True)
    assert repo.query_assets(AssetQuery(active_only=False)) == []
    with pytest.raises(ValueError, match="incomplete editor_sequence|distinct editor_page"):
        migrate_legacy(repo, root, dry_run=False)
    assert repo.query_assets(AssetQuery(active_only=False)) == []


def test_legacy_migration_dry_run_success_does_not_persist(repo: SQLiteAssetRepository) -> None:
    root = repo.object_store.root
    _write_legacy_fixture(root)
    report = migrate_legacy(repo, root, dry_run=True)
    assert report["dry_run"] is True
    assert report["bindings"]
    assert report["groups"]
    assert repo.query_assets(AssetQuery(active_only=False)) == []

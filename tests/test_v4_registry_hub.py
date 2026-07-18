from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_agent.contracts.v4 import FrozenRegistrySnapshot
from video_agent.registries import CapabilityRegistryHub, load_bootstrap_registry
from video_agent.registries.loaders import load_registry_directory, parse_registry_document


REGISTRY_ROOT = Path(__file__).parents[1] / "config" / "registries" / "v4"


def _documents():
    return load_registry_directory(REGISTRY_ROOT)


def test_registry_config_loads_and_resolves_categories() -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)

    assert hub.registry_ids == (
        "asset_role",
        "category",
        "claim",
        "configured_asset",
        "group_type",
        "operation_intent",
        "visual_structure",
    )
    assert hub.resolve_category("文化墙").id == "文生图/文化墙"
    assert hub.resolve_category("  文 化 墙  ").id == "文生图/文化墙"


def test_duplicate_registry_and_entry_ids_fail() -> None:
    documents = _documents()
    with pytest.raises(ValueError, match="duplicate registry_id"):
        CapabilityRegistryHub([*documents, documents[0]])

    category = next(document for document in documents if document.registry_id == "category")
    duplicate = category.model_copy(update={"entries": [*category.entries, category.entries[0]]})
    replaced = [duplicate if item.registry_id == "category" else item for item in documents]
    with pytest.raises(ValueError, match="duplicate entry ID"):
        CapabilityRegistryHub(replaced)


def test_normalized_alias_collisions_fail_within_and_across_categories() -> None:
    payload = json.loads((REGISTRY_ROOT / "category.json").read_text(encoding="utf-8"))
    payload["entries"][0]["aliases"] = ["ＡＢＣ", "abc"]
    category = parse_registry_document(payload)
    documents = [category if item.registry_id == "category" else item for item in _documents()]
    with pytest.raises(ValueError, match="duplicate category aliases after normalization"):
        CapabilityRegistryHub(documents)

    payload = json.loads((REGISTRY_ROOT / "category.json").read_text(encoding="utf-8"))
    payload["entries"][0]["aliases"] = ["共享别名"]
    payload["entries"][1]["aliases"] = [" 共 享 别 名 "]
    category = parse_registry_document(payload)
    documents = [category if item.registry_id == "category" else item for item in _documents()]
    with pytest.raises(ValueError, match="category alias collision after normalization"):
        CapabilityRegistryHub(documents)


def test_disabled_entries_are_hidden_but_frozen() -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)

    assert hub.entry("asset_role", "brand_ip") is None
    disabled = hub.entry("asset_role", "brand_ip", include_disabled=True)
    assert disabled is not None
    assert disabled.enabled is False

    snapshot = hub.snapshot()
    restored = CapabilityRegistryHub.from_snapshot(snapshot)
    assert restored.entry("asset_role", "brand_ip") is None
    assert restored.require_entry("asset_role", "brand_ip", include_disabled=True).enabled is False


def test_snapshot_hash_is_deterministic_and_content_sensitive() -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)
    first = hub.snapshot()
    second = hub.snapshot()

    assert first.content_sha256 == second.content_sha256
    assert first.snapshot_id == second.snapshot_id
    assert first.created_at <= second.created_at

    documents = _documents()
    visual = next(item for item in documents if item.registry_id == "visual_structure")
    changed_entry = visual.entries[0].model_copy(update={"description": "changed semantic content"})
    changed_visual = visual.model_copy(update={"entries": [changed_entry, *visual.entries[1:]]})
    changed_documents = [changed_visual if item.registry_id == "visual_structure" else item for item in documents]
    changed = CapabilityRegistryHub(changed_documents).snapshot()
    assert changed.content_sha256 != first.content_sha256


def test_freeze_round_trip_and_stage1_projection(tmp_path: Path) -> None:
    hub = CapabilityRegistryHub.load(REGISTRY_ROOT)
    output = tmp_path / "registry_snapshot.json"
    frozen = hub.freeze(output)
    parsed = FrozenRegistrySnapshot.model_validate_json(output.read_text(encoding="utf-8"))

    assert parsed.content_sha256 == frozen.content_sha256
    assert CapabilityRegistryHub.from_snapshot(parsed).snapshot().content_sha256 == frozen.content_sha256

    projected = load_bootstrap_registry(Path(__file__).parents[1])
    assert projected.category("文生图/文化墙") is not None
    assert projected.item("asset_roles", "brand_ip").enabled is False
    assert set(projected.registry_versions) == set(hub.registry_ids)


def test_snapshot_tampering_is_rejected() -> None:
    snapshot = CapabilityRegistryHub.load(REGISTRY_ROOT).snapshot()
    changed = snapshot.model_copy(deep=True)
    changed.registries[0].document["version"] = "tampered"

    with pytest.raises(ValueError, match="version mismatch"):
        CapabilityRegistryHub.from_snapshot(changed)


def test_invalid_handler_fails_during_hub_startup() -> None:
    documents = _documents()
    visual = next(item for item in documents if item.registry_id == "visual_structure")
    bad_entry = visual.entries[0].model_copy(update={"handler": "missing.module:handler"})
    bad_visual = visual.model_copy(update={"entries": [bad_entry, *visual.entries[1:]]})
    changed = [bad_visual if item.registry_id == "visual_structure" else item for item in documents]

    with pytest.raises(ValueError, match="handler not found"):
        CapabilityRegistryHub(changed)

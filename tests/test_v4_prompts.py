from __future__ import annotations

import json
from pathlib import Path

from video_agent.semantic.prompts import load_scene_prompt, load_scope_prompt
from video_agent.semantic.registry_payload import scene_registry_payload
from video_agent.registries import CapabilityRegistrySnapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_HEADINGS = (
    "# Role",
    "# Goal",
    "# Inputs",
    "# Allowed Decisions",
    "# Forbidden Decisions",
    "# Output Contract",
)
SCENE_REQUIRED_HEADINGS = (
    "# Role",
    "# Task",
    "# Core Principle",
    "# Forbidden",
    "# Output",
    "# Decision Hints",
    "# Registry Snapshot",
)


def test_scope_prompt_has_required_structure() -> None:
    prompt = load_scope_prompt(REPO_ROOT)
    assert all(heading in prompt.system_prompt for heading in REQUIRED_HEADINGS)
    assert "JSON" in prompt.system_prompt
    assert prompt.input_schema["additionalProperties"] is False
    assert prompt.output_schema["additionalProperties"] is False


def test_scene_prompt_injects_registry_and_decision_assets() -> None:
    registry = {
        "asset_roles": [{"item_id": "runtime_only_role"}],
        "visual_structures": [{"item_id": "single"}],
        "operation_intents": [],
        "claims": [],
        "group_types": [],
        "relation_patterns": [],
        "configured_assets": [],
    }
    prompt = load_scene_prompt(REPO_ROOT, registry)
    assert all(heading in prompt.system_prompt for heading in SCENE_REQUIRED_HEADINGS)
    assert "runtime_only_role" in prompt.system_prompt
    assert "{{" not in prompt.system_prompt
    assert json.dumps(registry, ensure_ascii=False, indent=2) in prompt.system_prompt
    assert "`group_member` 不能作为" in prompt.system_prompt
    assert "不确定时 `claims: []`" in prompt.system_prompt
    assert "不得使用 `no_asset_transition`" in prompt.system_prompt
    assert "Authoritative Role Resolution Rules" in prompt.system_prompt
    assert "Registered tool list" in prompt.system_prompt


def test_prompt_fingerprint_changes_with_registry() -> None:
    first = load_scene_prompt(REPO_ROOT, {"asset_roles": [{"item_id": "a"}]})
    second = load_scene_prompt(REPO_ROOT, {"asset_roles": [{"item_id": "b"}]})
    assert first.fingerprint != second.fingerprint


def test_scene_registry_payload_exposes_category_requirement() -> None:
    registry = CapabilityRegistrySnapshot.model_validate(
        {
            "categories": [
                {"category_id": "文生图/文化墙", "name": "文化墙"},
            ],
            "asset_roles": [
                {"item_id": "result_image", "requires_category": True},
                {"item_id": "site_home", "requires_category": False},
            ],
            "visual_structures": [],
            "operation_intents": [],
            "claims": [],
            "group_types": [],
            "relation_patterns": [],
            "configured_assets": [],
        }
    )

    payload = scene_registry_payload(registry)

    assert payload["asset_roles"] == [
        {"item_id": "result_image", "requires_category": True},
        {"item_id": "site_home", "requires_category": False},
    ]

from __future__ import annotations

import json
from pathlib import Path

from video_agent.semantic.prompts import load_scene_prompt, load_scope_prompt


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_HEADINGS = (
    "# Role",
    "# Goal",
    "# Inputs",
    "# Allowed Decisions",
    "# Forbidden Decisions",
    "# Output Contract",
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
        "group_patterns": [],
        "configured_assets": [],
    }
    prompt = load_scene_prompt(REPO_ROOT, registry)
    assert all(heading in prompt.system_prompt for heading in REQUIRED_HEADINGS)
    assert "# Decision Table" in prompt.system_prompt
    assert "runtime_only_role" in prompt.system_prompt
    assert "{{" not in prompt.system_prompt
    assert json.dumps(registry, ensure_ascii=False, indent=2) in prompt.system_prompt


def test_prompt_fingerprint_changes_with_registry() -> None:
    first = load_scene_prompt(REPO_ROOT, {"asset_roles": [{"item_id": "a"}]})
    second = load_scene_prompt(REPO_ROOT, {"asset_roles": [{"item_id": "b"}]})
    assert first.fingerprint != second.fingerprint
